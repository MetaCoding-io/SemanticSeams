"""In-process pub/sub for comm:Channel events, framed for Server-Sent Events.

``ChannelBus.publish(channel_iri, scope, event_name, data)`` fans an event out
to every subscriber of that (channel, scope). ``scope`` is the correlation
value, such as a conversation id, so one channel never leaks events across
conversations. ``subscribe`` returns an async iterator of SSE frames
(``event: <name>\\ndata: <json>\\n\\n``). It first replays the bounded backlog
of that (channel, scope), then yields live events.

``close(channel, scope)`` ends current iterators. A later subscriber to a
closed scope replays the backlog and then ends. The next ``publish`` reopens
the scope.

``publish`` is synchronous and thread-safe: frames reach each subscriber's
asyncio.Queue through its own loop's ``call_soon_threadsafe``. A subscriber
with ``queue_size`` frames unread is evicted: its iterator ends and it can
resubscribe to get the backlog.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import deque

log = logging.getLogger(__name__)

_CLOSE = object()


def sse_frame(event_name: str, data) -> str:
    if not event_name or any(c in event_name for c in "\r\n"):
        raise ValueError(f"invalid SSE event name {event_name!r}")
    return f"event: {event_name}\ndata: {json.dumps(data, sort_keys=True)}\n\n"


class Subscription:
    """Async iterator of SSE frames for one (channel, scope)."""

    def __init__(self, bus: ChannelBus, key: tuple, maxsize: int):
        self._bus = bus
        self._key = key
        self._loop = asyncio.get_running_loop()
        self._maxsize = maxsize
        # Unbounded on purpose: the limit is enforced in _offer, so the close
        # sentinel always fits behind the frames still queued.
        self._queue: asyncio.Queue = asyncio.Queue()
        self._done = False

    def _offer(self, item) -> None:
        """Runs on the subscriber's loop."""
        if self._done:
            return
        if item is _CLOSE:
            self._queue.put_nowait(_CLOSE)  # queued frames still drain first
            self._done = True
            return
        if self._queue.qsize() >= self._maxsize:
            log.warning("evicting slow subscriber of %s (%d frames queued)", self._key, self._maxsize)
            self._bus._unregister(self._key, self)
            while not self._queue.empty():
                self._queue.get_nowait()
            self._queue.put_nowait(_CLOSE)
            self._done = True
            return
        self._queue.put_nowait(item)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        item = await self._queue.get()
        if item is _CLOSE:
            self._bus._unregister(self._key, self)
            raise StopAsyncIteration
        return item

    def close(self) -> None:
        """Stop receiving (e.g. the HTTP client went away)."""
        self._bus._unregister(self._key, self)
        self._done = True


class ChannelBus:
    def __init__(self, backlog: int = 256, queue_size: int = 1024):
        self.backlog = backlog
        self.queue_size = max(queue_size, backlog + 1)
        self._lock = threading.Lock()
        self._backlogs: dict[tuple, deque] = {}
        self._subs: dict[tuple, list[Subscription]] = {}
        self._closed: set[tuple] = set()

    @staticmethod
    def _key(channel_iri, scope) -> tuple:
        return (str(channel_iri), str(scope))

    def publish(self, channel_iri, scope, event_name: str, data) -> str:
        """Frame and deliver one event; returns the frame."""
        frame = sse_frame(event_name, data)
        key = self._key(channel_iri, scope)
        with self._lock:
            self._closed.discard(key)
            self._backlogs.setdefault(key, deque(maxlen=self.backlog)).append(frame)
            subs = list(self._subs.get(key, ()))
        for sub in subs:
            self._deliver(sub, frame)
        return frame

    def subscribe(self, channel_iri, scope) -> Subscription:
        """Register now (inside a running loop), so nothing published between
        this call and the first ``__anext__`` is lost."""
        key = self._key(channel_iri, scope)
        sub = Subscription(self, key, self.queue_size)
        with self._lock:
            for frame in self._backlogs.get(key, ()):
                sub._queue.put_nowait(frame)
            if key in self._closed:
                sub._offer(_CLOSE)
            else:
                self._subs.setdefault(key, []).append(sub)
        return sub

    def close(self, channel_iri, scope) -> None:
        key = self._key(channel_iri, scope)
        with self._lock:
            self._closed.add(key)
            subs = self._subs.pop(key, [])
        for sub in subs:
            self._deliver(sub, _CLOSE)

    def subscriber_count(self, channel_iri, scope) -> int:
        with self._lock:
            return len(self._subs.get(self._key(channel_iri, scope), ()))

    def _unregister(self, key: tuple, sub: Subscription) -> None:
        with self._lock:
            subs = self._subs.get(key)
            if subs and sub in subs:
                subs.remove(sub)
                if not subs:
                    del self._subs[key]

    @staticmethod
    def _deliver(sub: Subscription, item) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is sub._loop:
            sub._offer(item)
        elif sub._loop.is_closed():
            sub._bus._unregister(sub._key, sub)
            sub._done = True
        else:
            sub._loop.call_soon_threadsafe(sub._offer, item)

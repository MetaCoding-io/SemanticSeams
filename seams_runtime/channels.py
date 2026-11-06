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

``PostgresChannelBus`` (ADR-0038) has the same API and reaches every runtime
on one PostgreSQL database and schema. ``publish`` stores the frame in the
store's ``channel_frames`` table and sends a ``NOTIFY`` on the schema's
channel in the same transaction (``PostgresStore.publish_frame``); a daemon
thread holds one ``LISTEN`` connection and fans each notification out to the
local subscriptions of its (channel, scope), the publisher's own frames
included, so each runtime delivers each frame once. A notification that
carries only an id is read back from the table; ``channel dropped <id>`` is
logged when the row is gone. ``subscribe`` replays the stored backlog,
dropping a live frame it already replayed. The listener logs
``channel listen <name>`` when it listens and ``channel reconnect <name>``
with the error before each retry, with backoff; frames published while it is
down reach a client only through the backlog when it resubscribes. ``stop``
ends the listener. ``bus_for(store)`` picks the bus from ``store.kind``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import deque
from typing import Any

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
        # PostgresChannelBus: live items held while the backlog is read (None once
        # replayed) and the ids replayed, so a live frame is not yielded twice
        self._held: list | None = None
        self._replayed: set[int] = set()

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
    kind = "in-process"

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

    def health(self) -> dict:
        """The /healthz channel report."""
        return {"kind": self.kind}

    def stop(self) -> None:
        """Nothing to stop in process."""

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


class PostgresChannelBus(ChannelBus):
    """``ChannelBus`` across runtimes sharing a ``PostgresStore`` (ADR-0038)."""

    kind = "postgresql"

    def __init__(
        self,
        store: Any,
        backlog: int = 256,
        queue_size: int = 1024,
        *,
        poll: float = 0.5,
        max_backoff: float = 10.0,
        ready_timeout: float | None = None,
    ):
        super().__init__(backlog, queue_size)
        self.store = store
        self.name: str = store.channel_name
        self.poll = poll
        self.max_backoff = max_backoff
        self.reconnects = 0
        self._stopping = threading.Event()
        self._listening = threading.Event()
        self._thread = threading.Thread(target=self._listen, name=f"seams-channel-{self.name}", daemon=True)
        self._thread.start()
        timeout = ready_timeout if ready_timeout is not None else float(getattr(store, "connect_timeout", 10))
        if not self._listening.wait(timeout):
            log.warning("channel %s not listening after %.1fs; frames reach clients once it is", self.name, timeout)

    def __repr__(self) -> str:
        return f"PostgresChannelBus({self.name!r}, {self.store!r})"

    @property
    def listening(self) -> bool:
        return self._listening.is_set()

    def health(self) -> dict:
        return {"kind": self.kind, "name": self.name, "listening": self.listening, "reconnects": self.reconnects}

    # ── the API ──

    def publish(self, channel_iri, scope, event_name: str, data) -> str:
        """Frame the event, store it and notify every runtime. Local
        subscribers get it from this runtime's listener, as all others do."""
        frame = sse_frame(event_name, data)
        channel, key_scope = self._key(channel_iri, scope)
        self.store.publish_frame(channel, key_scope, frame, self.backlog)
        return frame

    def close(self, channel_iri, scope) -> None:
        channel, key_scope = self._key(channel_iri, scope)
        self.store.publish_frame(channel, key_scope, None, self.backlog)

    def subscribe(self, channel_iri, scope) -> Subscription:
        """Register (live frames are held), read the stored backlog, then
        queue it and the held frames it does not already hold."""
        key = self._key(channel_iri, scope)
        sub = Subscription(self, key, self.queue_size)
        sub._held = []
        with self._lock:
            self._subs.setdefault(key, []).append(sub)
        try:
            rows = self.store.channel_backlog(*key)
        except BaseException:
            self._unregister(key, sub)
            raise
        with self._lock:
            held, sub._held = sub._held or [], None
            closed = False
            for row in rows:
                if row["frame"] is None:
                    closed = True
                    continue
                sub._replayed.add(row["id"])
                sub._queue.put_nowait(row["frame"])
            for frame_id, item in held:
                if item is _CLOSE:
                    closed = True
                elif frame_id not in sub._replayed:
                    sub._offer(item)
            if closed:
                subs = self._subs.get(key)
                if subs and sub in subs:
                    subs.remove(sub)
                    if not subs:
                        del self._subs[key]
                sub._offer(_CLOSE)
        return sub

    def stop(self, timeout: float = 5.0) -> None:
        """End the listener thread and close its connection."""
        self._stopping.set()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout)

    # ── the listener ──

    def _listen(self) -> None:
        import psycopg

        backoff = self.poll
        while not self._stopping.is_set():
            try:
                with self.store.listen() as con:
                    log.info("channel listen %s", self.name)
                    self._listening.set()
                    backoff = self.poll
                    while not self._stopping.is_set():
                        for note in con.notifies(timeout=self.poll):
                            self._receive(note.payload)
            except psycopg.Error as exc:
                self._listening.clear()
                if self._stopping.is_set():
                    break
                self.reconnects += 1
                log.warning("channel reconnect %s in %.1fs: %s", self.name, backoff, exc)
                self._stopping.wait(backoff)
                backoff = min(backoff * 2, self.max_backoff)
            except Exception:  # noqa: BLE001 - a bad notification must not end the listener
                log.exception("channel %s: listener failed; restarting", self.name)
                self._listening.clear()
                self._stopping.wait(self.poll)
        self._listening.clear()

    def _receive(self, payload: str) -> None:
        """Deliver one notification to the local subscriptions of its scope."""
        try:
            message = json.loads(payload)
            frame_id = int(message["id"])
        except (ValueError, KeyError, TypeError):
            log.warning("channel %s: ignoring a malformed notification %.200r", self.name, payload)
            return
        if "channel" not in message:  # the payload was over NOTIFY_LIMIT: the frame is in the table
            row = self.store.channel_frame(frame_id)
            if row is None:
                log.warning("channel dropped %s (no channel_frames row)", frame_id)
                return
            message = row
        key = (str(message["channel"]), str(message["scope"]))
        frame = message.get("frame")
        item = _CLOSE if frame is None else frame
        with self._lock:
            subs = list(self._subs.get(key, ()))
            if item is _CLOSE:
                self._subs.pop(key, None)
            live = []
            for sub in subs:
                if sub._held is not None:
                    sub._held.append((frame_id, item))
                elif item is _CLOSE or frame_id not in sub._replayed:
                    live.append(sub)
        for sub in live:
            self._deliver(sub, item)


def bus_for(store, **options) -> ChannelBus:
    """The bus ``store.kind`` calls for (ADR-0038 section 1): a
    ``PostgresChannelBus`` on a PostgreSQL store (the relational store of a
    ``SplitStore``), else the in-process ``ChannelBus``."""
    relational = getattr(store, "relational", store)
    if getattr(store, "kind", None) == "postgresql" and callable(getattr(relational, "publish_frame", None)):
        bus = PostgresChannelBus(relational, **options)
        log.info("channel bus postgresql on %s (%s)", bus.name, relational.location)
        return bus
    log.info("channel bus in-process (store kind %s)", getattr(store, "kind", None))
    return ChannelBus(**options)

"""The SemPKM webhook receiver (ADR-0027): an ``object.changed`` delivery on a
channel whose comm:transport is comm:SemPKMWebhook starts the processes
subscribed to it.

SemPKM signs nothing, so the body is a hint (section 6): the receiver acts only
on its ``event_iri``, and only after reading that event back from SemPKM with
the runtime's own service token. The objects, their class and their data
come from SemPKM through ``SemPKMStore``. ``receive`` handles one delivery in
the order of section 4:

1. the body must be a JSON object with string ``event_type`` and ``event_iri``,
   the latter a SemPKM event IRI: else 400;
2. an ``event_type`` other than the channel's comm:eventName is ignored (202);
3. the event's affected IRIs are read back (``SemPKMStore.affected``); an
   event SemPKM does not have is unverified (422);
4. the affected objects of the accepted shape's class are read
   (``SemPKMStore.read``); none left is ignored (202);
5. each object is validated against the accepted shape; one that fails is
   skipped (202, listed with its failing paths);
6. each subscribed process starts once per object, with the object's IRI as
   correlation key and the object as the accepted shape's current entity;
   a (process, event, object) that already started an instance starts
   nothing new (section 5) and answers that instance.

Failures answer ``application/problem+json`` naming the channel (section 8):
SemPKM unreachable, timing out, 429, 5xx, 401 or 403 is 503 and an
unreadable answer 502, both naming the store container. Every log line names
the channel, the event type and the event IRI; the token appears in none.
The SemPKM calls run in a thread, so the event loop keeps serving while they
wait (section 7).
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi.responses import JSONResponse

from .contracts import validate
from .errors import ContractViolation, ResolutionError, StoreError, StoreUnavailable
from .sempkm import _IRI, EVENT_PREFIX, SemPKMStore

log = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"  # RFC 9457
ACCEPTED = 202


def _answer(channel, event: str | None, started: list[dict], skipped: list[dict], note: str | None = None):
    body: dict = {
        "channel": str(channel),
        "event": event,
        "started": sorted(started, key=lambda s: (s["process"], s["object"])),
        "skipped": sorted(skipped, key=lambda s: s["object"]),
    }
    if note is not None:
        body["ignored"] = note
    return JSONResponse(body, status_code=ACCEPTED)


def _problem(channel, status: int, title: str, detail: str, **members) -> JSONResponse:
    body = {"type": "about:blank", "title": title, "status": status, "detail": detail, "channel": str(channel)}
    body.update(members)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def _parse(raw) -> tuple[str, str, dict] | str:
    """(event_type, event_iri, body) of a delivery, or why it is malformed."""
    if isinstance(raw, (bytes, bytearray, str)):
        try:
            raw = json.loads(raw)
        except ValueError:
            return "the body is not JSON"
    if not isinstance(raw, dict):
        return "the body is not a JSON object"
    event_type, event_iri = raw.get("event_type"), raw.get("event_iri")
    if not isinstance(event_type, str):
        return "event_type is missing or not a string"
    if not isinstance(event_iri, str):
        return "event_iri is missing or not a string"
    if not event_iri.startswith(EVENT_PREFIX) or not _IRI.fullmatch(event_iri):
        return f"event_iri {event_iri!r} is not a SemPKM event IRI ({EVENT_PREFIX}...)"
    return event_type, event_iri, raw


def _failing_paths(exc: ContractViolation) -> list[str]:
    return sorted({str(r.get("path") or r.get("message")) for r in exc.results})


class WebhookReceiver:
    """The receiver of every SemPKM webhook channel of ``runtime``'s model:
    ``channels`` as ``Runtime.load`` resolved them, else resolved now
    (``ModelGraph.webhook_channels``)."""

    def __init__(self, runtime, channels=None):
        self.runtime = runtime
        resolved = runtime.model.webhook_channels() if channels is None else channels
        self.channels = {ch.iri: ch for ch in resolved}
        self._lock = asyncio.Lock()  # one check-then-start at a time (section 5)
        for ch in self.channels.values():
            log.info(
                "SemPKM webhook channel %s at POST %s: %s of %s (%s in %s) starts %s",
                ch.iri,
                ch.path,
                ch.event_name,
                ch.target_class,
                ch.shape,
                ch.store,
                ", ".join(str(p) for p in ch.processes),
            )

    def client(self, ch) -> SemPKMStore | None:
        """The runtime's SemPKM client for the channel's store, else None
        (an injected or overriding store keeps the entities elsewhere)."""
        entities = getattr(self.runtime.store, "entities", None)
        if isinstance(entities, SemPKMStore) and entities.store == ch.store:
            return entities
        return None

    async def receive(self, channel, raw) -> JSONResponse:
        """Handle one delivery on ``channel`` (sections 4 to 8)."""
        ch = self.channels.get(self.runtime.model.curie(channel))
        if ch is None:
            raise ResolutionError(channel, "comm:transport", "not a comm:SemPKMWebhook channel of this model")
        parsed = _parse(raw)
        if isinstance(parsed, str):
            log.warning("webhook %s: delivery rejected (400): %s", ch.iri, parsed)
            return _problem(ch.iri, 400, "Bad webhook delivery", parsed)
        event_type, event, body = parsed
        what = f"webhook {ch.iri}: {event_type} {event}"
        log.info("%s received (command %s at %s)", what, body.get("command"), body.get("timestamp"))
        if event_type != ch.event_name:
            note = f"event type {event_type} is not the channel's comm:eventName {ch.event_name}"
            log.info("%s ignored: %s", what, note)
            return _answer(ch.iri, event, [], [], note)
        client = self.client(ch)
        try:
            if client is None:
                raise StoreUnavailable(
                    ch.store, "the runtime keeps no SemPKM client for this store (an injected or overriding store)"
                )
            affected = await asyncio.to_thread(client.affected, event)
            if affected is None:
                log.warning("%s rejected (422): unverified event, SemPKM %s has no such event", what, ch.store)
                return _problem(
                    ch.iri,
                    422,
                    "Unverified event",
                    f"SemPKM {ch.store} has no event {event}",
                    event=event,
                    store=str(ch.store),
                )
            objects = await asyncio.to_thread(client.read, ch.shape, affected) if affected else []
        except StoreError as exc:
            log.error("%s: store %s failed (%s): %s", what, exc.store, exc.http_status, exc.reason)
            return _problem(ch.iri, exc.http_status, exc.title, str(exc), event=event, store=exc.store)
        if not objects:
            note = f"no affected object is a {ch.target_class}"
            log.info("%s ignored: %s (affected %s)", what, note, ", ".join(affected) or "nothing")
            return _answer(ch.iri, event, [], [], note)
        started: list[dict] = []
        skipped: list[dict] = []
        async with self._lock:
            for iri, data in objects:
                try:
                    valid = dict(validate(self.runtime.model, ch.shape, data))
                except ContractViolation as exc:
                    paths = _failing_paths(exc)
                    log.warning("%s: object %s skipped, it fails %s at %s", what, iri, ch.shape, ", ".join(paths))
                    skipped.append({"object": iri, "reason": f"fails {ch.shape} at {', '.join(paths)}"})
                    continue
                for process in ch.processes:
                    started.append(await self._start(ch, what, process, event, iri, valid))
        return _answer(ch.iri, event, started, skipped)

    async def _start(self, ch, what: str, process, event: str, iri: str, data: dict) -> dict:
        record = {"channel": str(ch.iri), "event": event, "object": iri}
        row = {"process": str(process), "object": iri}
        rt = self.runtime
        try:
            existing = await asyncio.to_thread(self._existing, process, record)
            if existing is not None:
                log.info("%s: %s already started instance %s for %s", what, process, existing, iri)
                return {**row, "instance": existing}
            status: dict = {}
            if rt.model.has_lifecycle(ch.shape):
                status[str(ch.shape)] = data.get("status") or rt.model.lifecycle_for(ch.shape).initial
            current = {str(ch.shape): {"id": iri, "data": data}}
            instance = rt._start_subscribed(process, iri, current, status, origin=record)
        except Exception as exc:  # noqa: BLE001 - ADR-0010 failure isolation: the others still start
            log.exception("%s: starting %s for %s failed", what, process, iri)
            return {**row, "instance": None, "error": {"type": type(exc).__name__, "message": str(exc)}}
        log.info("%s: object %s started %s instance %s", what, iri, process, instance.id)
        return {**row, "instance": instance.id}

    def _existing(self, process, record: dict) -> str | None:
        """The id of an instance of ``process`` whose start record is ``record``, else None."""
        rt = self.runtime
        for meta in rt.store.list_instances(record["object"]):
            if str(meta["process"]) != str(process):
                continue
            wf = rt.engine.deserialize(rt.store.load_state(meta["instance_id"]))
            if wf.data.get("seams", {}).get("start") == record:
                return str(meta["instance_id"])
        return None

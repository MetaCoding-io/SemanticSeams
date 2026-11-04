"""The entities of SemPKM-stored shapes, kept in SemPKM over HTTP (ADR-0025).

``SemPKMStore`` is the entity backend ``store.SplitStore`` hands the shapes
``seam:storedIn`` a ``deploy:SemPKM`` store to; process state, open user tasks
and each entity's correlation key, instance and status stay in the relational
store (ADR-0025 section 2).

Everything it sends comes from the typed shape views (``seams.views.shapes``):

- **create** is one ``POST /api/commands`` request: an ``object.create`` typed
  by the shape's ``sh:targetClass`` with a map from each field's ``sh:path``
  to its value, then, for each flattened ``sh:node`` field, an
  ``object.create`` of the nested node (typed by the nested shape's
  ``sh:targetClass``, with its free and fixed properties) and an
  ``edge.create`` from the entity along the field's path. SemPKM commits the
  commands of one request in one event, and ``@slot:`` references let the
  edges name objects the same request creates. SemPKM mints the IRIs; the
  entity's IRI becomes its id (section 7), and a field named ``id`` (the
  identifier convention ``Runtime.write`` uses) is never sent but read back
  as that IRI.
- **values** are JSON, which SemPKM types itself: an integer field sends an
  int, a decimal, double or float field a number, a boolean field a bool,
  a category field its member's IRI (the label on the wire maps to it), and
  everything else a string.
- **reads** are ``POST /api/sparql`` queries scoped to the shape's class and
  paths, following SemPKM's edge resources one level to rebuild nested
  values, with sorted variables, so one model sends one query text.
- **events** (ADR-0027 section 4): ``affected`` reads the
  ``sempkm:affectedIRI``s of one event from its event graph, one
  ``all_graphs`` SPARQL query, which SemPKM allows only to a token whose
  user has the owner role.
- **update** is an ``object.patch`` of the top-level fields whose value
  changed (a lifecycle status, as the worker moves it). A nested value is
  written once; changing one raises ``ResolutionError`` naming the field
  (updates are out of ADR-0025's scope, section 12).

Failures (section 11): unreachable, a timeout, 5xx or 429 raise
``StoreUnavailable`` (503); 401 and 403 too, after a log line naming the
store and the token scope the call needs; any other 4xx, a body that is not
the API's JSON, or no IRI from ``object.create`` raise ``StoreReplyInvalid``
(502). Every error names the store container. The token is sent as a Bearer
header and appears in no log line, error, ``repr`` or report.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx
from rdflib import XSD, Literal, URIRef
from rdflib.namespace import SH

from .errors import ResolutionError, StoreReplyInvalid, StoreUnavailable
from .model import SEAM, ModelGraph
from .store import redact

log = logging.getLogger(__name__)

# SemPKM's API (its backend's app/commands, app/sparql and app/health routers).
COMMANDS_PATH = "/api/commands"
SPARQL_PATH = "/api/sparql"
HEALTH_PATH = "/api/health"
COMMANDS_SCOPE = "commands:execute"  # the token scope POST /api/commands requires
SPARQL_SCOPE = "sparql:read"  # the token scope POST /api/sparql requires
# edge.create makes an edge resource with these three properties (handlers/edge_create.py).
EDGE_SOURCE = URIRef("urn:sempkm:source")
EDGE_PREDICATE = URIRef("urn:sempkm:predicate")
EDGE_TARGET = URIRef("urn:sempkm:target")
# An event's named graph: <event> a sempkm:Event ; sempkm:affectedIRI <object> (app/events/models.py).
EVENT_PREFIX = "urn:sempkm:event:"
EVENT_CLASS = URIRef("urn:sempkm:Event")
EVENT_AFFECTED = URIRef("urn:sempkm:affectedIRI")
OWNER_ROLE = "owner"  # the role SemPKM requires for an all_graphs query (app/sparql/router.py)

ENTITY_SLOT = "entity"  # the @slot name of the entity's own object.create
ID_FIELD = "id"  # the identifier convention (Runtime.write): its value is the IRI
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
HEALTH_TIMEOUT = httpx.Timeout(2.0)

_INTEGERS = frozenset(
    {
        XSD.integer,
        XSD.int,
        XSD.long,
        XSD.short,
        XSD.byte,
        XSD.nonNegativeInteger,
        XSD.positiveInteger,
        XSD.nonPositiveInteger,
        XSD.negativeInteger,
        XSD.unsignedInt,
        XSD.unsignedLong,
        XSD.unsignedShort,
        XSD.unsignedByte,
    }
)
_NUMBERS = frozenset({XSD.decimal, XSD.double, XSD.float})
# What may sit between < and > in a SPARQL IRI reference.
_IRI = re.compile(r'[^<>"{}|^`\\\x00-\x20]+')


@dataclass(frozen=True)
class StoredField:
    """One field of a SemPKM-stored shape as the store sends and reads it:
    the typed view's ``field``, its SPARQL variable ``var`` and, for a
    flattened sh:node field, ``nested_class``, the nested shape's sh:targetClass."""

    field: object  # seams.views.shapes.Field
    var: str
    nested_class: URIRef | None = None


@dataclass(frozen=True)
class StoredShape:
    """A SemPKM-stored shape: its ``target`` sh:targetClass, the ``fields``
    it writes and reads (all but ``id``), and ``has_id``."""

    shape: URIRef
    target: URIRef
    fields: tuple[StoredField, ...]
    has_id: bool


def stored_shape(model: ModelGraph, shape) -> StoredShape:
    """The ``StoredShape`` of ``shape`` from its typed view. A shape or nested
    shape without a sh:targetClass raises ``ResolutionError`` (ADR-0025 section 11)."""
    view = model.shape(shape)
    target = view.target_class
    if target is None:
        raise ResolutionError(view.iri, SH.targetClass, "a shape stored in SemPKM needs sh:targetClass (ADR-0025)")
    fields = []
    has_id = False
    for f in view.fields():
        if f.name == ID_FIELD:
            has_id = True
            continue
        nested = None
        if f.node is not None:
            cls = model.shape(f.node.shape).target_class
            if cls is None:
                detail = f"{f.name}: the sh:node shape of a field stored in SemPKM needs sh:targetClass (ADR-0025)"
                raise ResolutionError(f.node.shape, SH.targetClass, detail)
            nested = cls.iri
        fields.append(StoredField(f, f"?f_{f.name}", nested))
    return StoredShape(view.iri, target.iri, tuple(fields), has_id)


def _iri(value: str, store, what: str) -> str:
    if not isinstance(value, str) or not _IRI.fullmatch(value):
        raise StoreReplyInvalid(store, f"{what}: {value!r} is not an IRI")
    return value


def _send(f, value):
    """The JSON value object.create takes for a payload value of field ``f``."""
    if isinstance(value, list):
        return [_send(f, v) for v in value]
    if f.members and str(value) in f.options:
        return str(f.members[f.options.index(str(value))])
    if isinstance(value, bool):
        return value
    if f.datatype in _INTEGERS:
        return int(value)
    if f.datatype in _NUMBERS:
        return float(value)
    if f.datatype == XSD.boolean:
        return str(value).strip().lower() in ("true", "1")
    if isinstance(value, (int, float)):
        return value
    return str(value)


def _same(a, b) -> bool:
    """Equal as SemPKM holds them: a multi-valued field is a set."""
    if isinstance(a, list) or isinstance(b, list):
        listed = (sorted(map(str, x if isinstance(x, list) else [x])) for x in (a, b))
        return next(listed) == next(listed)
    return a == b


def _fixed(value) -> object:
    """A fixed sh:hasValue of a nested node as a JSON value."""
    if isinstance(value, Literal):
        python = value.toPython()
        return python if isinstance(python, (bool, int, float)) else str(value)
    return str(value)


def _receive(f, binding: dict):
    """The payload value of field ``f`` for one SPARQL JSON binding: a
    member IRI becomes its label, an integer an int, a boolean a bool, a
    decimal its plain lexical form; anything else its string."""
    value = binding.get("value")
    if not isinstance(value, str):
        raise ValueError(f"binding without a string value: {binding!r}")
    if binding.get("type") == "uri":
        member = URIRef(value)
        return f.options[f.members.index(member)] if member in f.members else value
    if f.datatype in _INTEGERS:
        try:
            return int(value)
        except ValueError:
            return value
    if f.datatype == XSD.boolean:
        return value.strip().lower() in ("true", "1")
    if f.datatype in _NUMBERS:
        try:
            return format(Decimal(value), "f")
        except InvalidOperation:
            return value
    return value


class SemPKMStore:
    """The entities of the shapes stored in one deploy:SemPKM store, at ``url``
    with the service ``token`` (ADR-0025). ``plan`` is the seams
    ``SemPKMPlan``; ``transport`` an httpx transport (tests)."""

    kind = "sempkm"

    def __init__(self, model: ModelGraph, plan, url: str, token: str, *, transport=None, timeout=DEFAULT_TIMEOUT):
        self.model = model
        self.plan = plan
        self.store = plan.store
        self.url = url.rstrip("/")
        self.location = redact(self.url)
        self.transport = transport
        self.timeout = timeout
        self._token = token
        self.shapes = tuple(plan.shapes)
        self._stored = {str(s): stored_shape(model, s) for s in self.shapes}

    def __repr__(self) -> str:
        return f"SemPKMStore({self.location!r}, store={str(self.store)!r})"

    def stored(self, shape) -> StoredShape:
        found = self._stored.get(str(shape))
        if found is None:
            raise ResolutionError(shape, SEAM.storedIn, f"not stored in {self.store}")
        return found

    # ── what is sent ──

    def commands(self, shape, data: dict) -> list[dict]:
        """The commands that create one entity of ``shape`` from validated
        ``data``: the entity's object.create first (slot ``entity``), then
        each nested node's object.create, then the edges joining them."""
        stored = self.stored(shape)
        properties: dict[str, object] = {}
        nested: list[dict] = []
        edges: list[dict] = []
        for sf in stored.fields:
            f = sf.field
            if f.name not in data:
                continue
            value = data[f.name]
            if f.node is None:
                properties[str(f.path)] = _send(f, value)
                continue
            for index, v in enumerate(value if isinstance(value, list) else [value]):
                slot = f"{f.name}.{index}"
                node = {str(f.node.free_path): _send(f, v)}
                node.update({str(path): _fixed(fixed) for path, fixed in f.node.fixed})
                nested.append(
                    {
                        "command": "object.create",
                        "slot": slot,
                        "params": {"type": str(sf.nested_class), "properties": dict(sorted(node.items()))},
                    }
                )
                edges.append(
                    {
                        "command": "edge.create",
                        "params": {
                            "source": f"@slot:{ENTITY_SLOT}",
                            "target": f"@slot:{slot}",
                            "predicate": str(f.path),
                        },
                    }
                )
        entity = {
            "command": "object.create",
            "slot": ENTITY_SLOT,
            "params": {"type": str(stored.target), "properties": dict(sorted(properties.items()))},
        }
        return [entity, *nested, *edges]

    def select(self, shape, iris=None) -> str:
        """The SPARQL query reading entities of ``shape`` (only ``iris`` when
        given): scoped to its sh:targetClass and its fields' paths, nested
        values one edge away, variables sorted."""
        stored = self.stored(shape)
        variables = sorted(["?iri", *(sf.var for sf in stored.fields)])
        lines = [f"SELECT {' '.join(variables)} WHERE {{"]
        if iris is not None:
            lines.append(f"  VALUES ?iri {{ {' '.join(f'<{i}>' for i in sorted(iris))} }}")
        lines.append(f"  ?iri a <{stored.target}> .")
        for sf in stored.fields:
            f = sf.field
            if f.node is None:
                lines.append(f"  OPTIONAL {{ ?iri <{f.path}> {sf.var} . }}")
                continue
            edge, node = f"?e_{f.name}", f"?n_{f.name}"
            lines.append(
                f"  OPTIONAL {{ {edge} <{EDGE_SOURCE}> ?iri ; <{EDGE_PREDICATE}> <{f.path}> ; <{EDGE_TARGET}> {node} . "
                f"{node} a <{sf.nested_class}> ; <{f.node.free_path}> {sf.var} . }}"
            )
        lines += ["}", "ORDER BY ?iri"]
        return "\n".join(lines)

    # ── entity operations ──

    def create(self, shape, data: dict) -> tuple[str, dict]:
        """Create one entity; return its SemPKM-minted IRI and the stored data
        (``data`` with ``id`` set to the IRI when the shape has an id field)."""
        stored = self.stored(shape)
        body = self._post(COMMANDS_PATH, self.commands(shape, data), COMMANDS_SCOPE, f"create a {shape} entity")
        results = body.get("results") if isinstance(body, dict) else None
        first = results[0] if isinstance(results, list) and results else None
        iri = first.get("iri") if isinstance(first, dict) else None
        if not iri:
            log.error("SemPKM store %s: object.create of %s returned no IRI", self.store, shape)
            raise StoreReplyInvalid(self.store, f"POST {COMMANDS_PATH}: object.create returned no IRI")
        iri = _iri(iri, self.store, f"POST {COMMANDS_PATH}")
        log.info("SemPKM store %s: created %s entity %s", self.store, shape, iri)
        return iri, self._with_id(stored, iri, data)

    def update(self, iri: str, shape, data: dict) -> dict:
        """Patch the top-level fields of entity ``iri`` whose value differs from
        what SemPKM holds; return the stored data. A changed nested value
        raises ``ResolutionError`` naming the field."""
        stored = self.stored(shape)
        current = self.get(iri, shape) or {}
        changes: dict[str, object] = {}
        for sf in stored.fields:
            f = sf.field
            if f.name not in data:
                continue
            sent = _send(f, data[f.name])
            if f.name in current and _same(sent, _send(f, current[f.name])):
                continue  # compared as SemPKM holds them: "42.50" is 42.5
            if f.node is not None:
                detail = f"{f.name}: a nested value stored in SemPKM is not updated (ADR-0025 section 12)"
                raise ResolutionError(stored.shape, f.path, detail)
            changes[str(f.path)] = sent
        if changes:
            command = {"command": "object.patch", "params": {"iri": iri, "properties": dict(sorted(changes.items()))}}
            self._post(COMMANDS_PATH, [command], COMMANDS_SCOPE, f"patch {iri}")
            log.info("SemPKM store %s: patched %s (%s)", self.store, iri, ", ".join(sorted(changes)))
        return self._with_id(stored, iri, {**current, **data})

    def get(self, iri: str, shape) -> dict | None:
        """The data of entity ``iri``, or None when SemPKM has no such object of the shape's class."""
        found = self.read(shape, [iri])
        return found[0][1] if found else None

    def read(self, shape, iris=None) -> list[tuple[str, dict]]:
        """(IRI, data) of the entities of ``shape`` in SemPKM, by IRI; only
        ``iris`` when given (none: no request)."""
        if iris is not None:
            iris = [_iri(str(i), self.store, "entity id") for i in iris]
            if not iris:
                return []
        stored = self.stored(shape)
        body = self._post(SPARQL_PATH, {"query": self.select(shape, iris)}, SPARQL_SCOPE, f"read {shape} entities")
        try:
            bindings = body["results"]["bindings"]
            values: dict[str, dict[str, list]] = {}
            for b in bindings:
                iri = _iri(b["iri"]["value"], self.store, f"POST {SPARQL_PATH}")
                row = values.setdefault(iri, {})
                for sf in stored.fields:
                    found = b.get(sf.var[1:])
                    if found is not None:
                        v = _receive(sf.field, found)
                        if v not in row.setdefault(sf.field.name, []):
                            row[sf.field.name].append(v)
        except (KeyError, TypeError, ValueError) as exc:
            log.error("SemPKM store %s: unreadable SPARQL results for %s: %s", self.store, shape, exc)
            raise StoreReplyInvalid(self.store, f"POST {SPARQL_PATH}: not SPARQL JSON results ({exc})") from exc
        out = []
        for iri in sorted(values):
            data: dict = {}
            for sf in stored.fields:
                found = sorted(values[iri].get(sf.field.name, []), key=str)
                if found:
                    data[sf.field.name] = found[0] if sf.field.max_count == 1 else found
            out.append((iri, self._with_id(stored, iri, data)))
        return out

    def event_select(self, event: str) -> str:
        """The SPARQL query reading the affected IRIs of ``event`` from its
        event graph: one row per IRI, or one unbound row for an event with none."""
        return "\n".join(
            [
                "SELECT ?iri WHERE {",
                f"  GRAPH <{event}> {{ <{event}> a <{EVENT_CLASS}> . "
                f"OPTIONAL {{ <{event}> <{EVENT_AFFECTED}> ?iri . }} }}",
                "}",
                "ORDER BY ?iri",
            ]
        )

    def affected(self, event: str) -> list[str] | None:
        """The IRIs of the objects SemPKM event ``event`` changed, sorted, or
        None when SemPKM has no such event (ADR-0027 section 4, step 3). An
        affected value that is not an IRI is not an object and drops out."""
        event = _iri(event, self.store, "event IRI")
        if not event.startswith(EVENT_PREFIX):
            raise ValueError(f"{event!r} is not a SemPKM event IRI ({EVENT_PREFIX}...)")
        body = self._post(
            SPARQL_PATH,
            {"query": self.event_select(event), "all_graphs": True},
            SPARQL_SCOPE,
            f"read event {event}",
            role=OWNER_ROLE,
        )
        try:
            bindings = body["results"]["bindings"]
            if not bindings:
                return None
            found = {b["iri"]["value"] for b in bindings if "iri" in b and b["iri"].get("type") == "uri"}
        except (KeyError, TypeError, AttributeError) as exc:
            log.error("SemPKM store %s: unreadable SPARQL results for event %s: %s", self.store, event, exc)
            raise StoreReplyInvalid(self.store, f"POST {SPARQL_PATH}: not SPARQL JSON results ({exc})") from exc
        return sorted(i for i in found if isinstance(i, str) and _IRI.fullmatch(i))

    def reachable(self) -> bool:
        """True when ``GET /api/health`` answers 2xx with status healthy (no token sent)."""
        try:
            with httpx.Client(base_url=self.url, transport=self.transport, timeout=HEALTH_TIMEOUT) as client:
                resp = client.get(HEALTH_PATH)
            ok = resp.is_success and resp.json().get("status") == "healthy"
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            log.warning("SemPKM store %s at %s: health check failed: %s", self.store, self.location, exc)
            return False
        if not ok:
            log.warning(
                "SemPKM store %s at %s: GET %s answered %s", self.store, self.location, HEALTH_PATH, resp.status_code
            )
        return ok

    # ── HTTP ──

    @staticmethod
    def _with_id(stored: StoredShape, iri: str, data: dict) -> dict:
        out = {k: v for k, v in data.items() if k != ID_FIELD}
        if stored.has_id:
            out[ID_FIELD] = iri
        return dict(sorted(out.items()))

    def _post(self, path: str, body, scope: str, what: str, role: str | None = None):
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            with httpx.Client(
                base_url=self.url, transport=self.transport, timeout=self.timeout, headers=headers
            ) as client:
                resp = client.post(path, json=body)
        except httpx.TimeoutException as exc:
            log.error("SemPKM store %s at %s: POST %s timed out (%s)", self.store, self.location, path, what)
            raise StoreUnavailable(self.store, f"POST {path} timed out") from exc
        except httpx.HTTPError as exc:
            log.error("SemPKM store %s at %s: POST %s failed (%s): %s", self.store, self.location, path, what, exc)
            raise StoreUnavailable(self.store, f"POST {path}: unreachable ({type(exc).__name__})") from exc
        status = resp.status_code
        if status in (401, 403):
            needs = f"scope {scope}" + (f" and a user with the {role} role" if role else "")
            log.error(
                "SemPKM store %s refused the service token on POST %s (%s): %s %s; the token needs %s",
                self.store,
                path,
                what,
                status,
                _error_text(resp),
                needs,
            )
            raise StoreUnavailable(self.store, f"POST {path} answered {status}: the service token lacks {needs}")
        if status == 429 or status >= 500:
            log.error("SemPKM store %s: POST %s (%s) answered %s %s", self.store, path, what, status, _error_text(resp))
            raise StoreUnavailable(self.store, f"POST {path} answered {status}")
        if status >= 400:
            text = _error_text(resp)
            log.error("SemPKM store %s: POST %s (%s) rejected: %s %s", self.store, path, what, status, text)
            raise StoreReplyInvalid(self.store, f"POST {path} answered {status}: {text}")
        try:
            return resp.json()
        except ValueError as exc:
            log.error("SemPKM store %s: POST %s (%s) answered %s with no JSON body", self.store, path, what, status)
            raise StoreReplyInvalid(self.store, f"POST {path}: the answer is not JSON") from exc


def _error_text(resp: httpx.Response) -> str:
    """SemPKM's error message (``error`` or ``detail``), else the body's first 200 characters."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(body, dict):
        for key in ("error", "detail"):
            if key in body:
                return str(body[key])[:200]
    return str(body)[:200]

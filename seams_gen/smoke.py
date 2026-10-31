"""The smoke generator: a pytest file that calls every operation on a running app (backlog A9).

``extract_smoke`` reads each ``hydra:Operation`` that has a ``hydra:method``
and a ``comm:path`` (``model.operations``, by IRI) into a frozen
``ProbeModel``, and ``render_smoke`` renders them through
``tests_smoke.py.j2`` into ``test_smoke.py``: one test per operation, named
``test_smoke_<local name>``, that sends it to the app at
``SEAMS_SMOKE_BASE_URL`` as the identity ``SEAMS_SMOKE_USER`` /
``SEAMS_SMOKE_GROUPS`` and checks the answer (``seams_runtime.verify.smoke``):
a 2xx body conforms to the operation's ``seam:returnsShape`` (a
``seam:UIFragment``'s HTML is checked by status only), and any other status
is a declared error (``hydra:possibleStatus`` with a ``comm:errorCode``)
whose body conforms to the status's ``seam:returnsShape`` (ADR-0013).

What a probe sends comes from the model's examples (ADR-0014): each path
variable is the value its ``hydra:property`` has on the first
``verify:validExample`` (by IRI) of the shape the operation accepts, else of
the shape it returns; an operation that accepts a shape and is not a GET
sends that shape's first valid example as its form. When no example gives a
value, the test is skipped with a reason naming the variable and the
examples it looked at. The policies governing an operation are each
``odrl:permission`` whose ``odrl:target`` is the operation or a user task
completed on a form that submits to it (``seams_gen.tests.target_operation``);
their assignees are written out, and a test whose configured identity no
assignee admits is skipped at run time with a reason naming the policy.

Every value is a Python literal prepared here (principle 1, templates hold
text); operations are sorted by IRI, error statuses by code, policies by IRI
(principle 6). The file starts with the generator header and the model
hash, and ``load_model`` refuses a model with another hash. Generator-only
faults (the README lists them): a permission target that is missing or is
neither an operation nor a user task completed on a form with one
submitting operation (as the tests generator), and two operations whose
local names would give two tests one name.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from rdflib import URIRef
from seams import COMM, HYDRA, ODRL, SEAM, Model, Operation, PathTemplate, Shape, load

from . import GeneratorError
from ._views import required, view_errors
from .htmx import _environment
from .tests import _identifier, _py, target_operation

FILE = "test_smoke.py"
TEMPLATE = "tests_smoke.py.j2"
NO_BODY = ("GET", "HEAD")


# ── the smoke model ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProbeModel:
    """One operation's smoke test; every field after ``comment`` is a Python literal."""

    name: str  # the test function name
    constant: str  # the module-level name of its Probe
    comment: tuple[str, ...]  # the comment lines above it, without "# "
    iri: str
    method: str
    path: str
    data: str  # tuple literals from here on
    json: str
    returns: str
    errors: str
    policies: str
    parties: str
    any_party: str
    skip: str
    sources: tuple[str, ...]  # full IRIs of the model elements it comes from


@dataclass(frozen=True)
class SmokeModel:
    model_stem: str
    model_hash: str
    probes: tuple[ProbeModel, ...]
    generator: str = "smoke"


@dataclass(frozen=True)
class _Grant:
    """One odrl:permission governing an operation."""

    policy: URIRef
    assignee: URIRef | None
    anyone: bool


# ── extraction ──────────────────────────────────────────────────────────────


def _tuple(items: list[str]) -> str:
    """A tuple literal of already-rendered items."""
    if not items:
        return "()"
    if len(items) == 1:
        return f"({items[0]},)"
    return f"({', '.join(items)})"


def _grants(model: Model) -> dict[URIRef, list[_Grant]]:
    """{operation IRI: the permissions governing it}, policies by IRI, permissions in view order."""
    found: dict[URIRef, list[_Grant]] = {}
    for policy in model.policies:
        for permission in policy.permissions:
            if permission.target is None:
                raise GeneratorError(policy.iri, ODRL.target, "a permission needs an odrl:target")
            op = target_operation(model, policy, model.views.resolve(permission.target))
            anyone = permission.assignee is None or ODRL.PartyCollection in permission.assignee_types
            found.setdefault(op.iri, []).append(_Grant(policy.iri, permission.assignee, anyone))
    return found


def _first_example(shape: Shape | None) -> URIRef | None:
    return None if shape is None or not shape.valid_examples else shape.valid_examples[0]


def _fill(model: Model, op: Operation, template: PathTemplate, sources: set[str]) -> tuple[str, list[str]]:
    """(the path with each variable filled, why a variable could not be)."""
    shapes = list(dict.fromkeys(s for s in (op.accepts, op.returns) if s is not None))
    path, missing = template.template, []
    for mapping in template.mappings:
        value, looked = None, []
        for shape in shapes:
            node = _first_example(shape)
            if node is None:
                looked.append(f"{model.compact(shape.iri)} has no verify:validExample")
                continue
            values = [v for f, v in shape.example_values(node) if f.iri == mapping.property_iri]
            if values:
                value = values[0]
                sources.add(str(node))
                break
            looked.append(f"{model.compact(node)} has no {model.compact(mapping.property_iri)}")
        if value is None:
            reason = "; ".join(looked) or "the operation names no shape"
            missing.append(f"no example fills {{{mapping.variable}}}: {reason}")
        else:
            path = path.replace("{" + mapping.variable + "}", quote(str(value), safe=""))
    return path, missing


def _body(model: Model, op: Operation, method: str, sources: set[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """(the form fields the operation is sent with, why there are none when it needs some)."""
    shape = op.accepts
    if shape is None or method in NO_BODY:
        return [], []
    node = _first_example(shape)
    if node is None:
        return [], [f"{model.compact(shape.iri)} has no verify:validExample to send"]
    sources.add(str(node))
    return [(f.name, str(v)) for f, v in shape.example_values(node)], []


def _probe(model: Model, op: Operation, grants: list[_Grant]) -> ProbeModel:
    method = required(op.method, op.iri, HYDRA.method).upper()
    template = required(op.path, op.iri, COMM.path)
    sources = {str(op.iri)}
    path, missing = _fill(model, op, template, sources)
    data, no_body = _body(model, op, method, sources)
    returns = op.returns
    errors = sorted(
        ((required(s.status_code, s.iri, HYDRA.statusCode), s.returns, s.iri) for s in op.errors),
        key=lambda e: (e[0], str(e[2])),
    )
    json = op.media_kind != SEAM.UIFragment
    sources.update(str(s.iri) for s in (op.accepts, returns) if s is not None)
    sources.update(str(shape.iri) for _, shape, _ in errors if shape is not None)
    sources.update(str(g.policy) for g in grants)
    sources.update(str(g.assignee) for g in grants if g.assignee is not None)

    curie = model.compact
    shown = curie(returns.iri) if returns is not None else "no seam:returnsShape"
    comment = [f"{curie(op.iri)} {method} {template.template} -> {shown}" + ("" if json else " (seam:UIFragment)")]
    comment += [f"  {code} -> {curie(shape.iri) if shape else 'no seam:returnsShape'}" for code, shape, _ in errors]
    for g in grants:
        assignee = "any authenticated party" if g.anyone else curie(g.assignee)
        comment.append(f"  governed by {curie(g.policy)} (odrl:assignee {assignee})")
    policies = sorted({curie(g.policy) for g in grants})
    parties = sorted({str(g.assignee) for g in grants if g.assignee is not None and not g.anyone})
    skip = missing + no_body
    return ProbeModel(
        name=f"test_smoke_{_identifier(op.iri)}",
        constant=_identifier(op.iri).upper(),
        comment=tuple(comment),
        iri=_py(op.iri),
        method=_py(method),
        path=_py(path),
        data=_tuple([f"({_py(name)}, {_py(value)})" for name, value in data]),
        json=str(json),
        returns=_py(None if returns is None else returns.iri),
        errors=_tuple([f"({code}, {_py(None if shape is None else shape.iri)})" for code, shape, _ in errors]),
        policies=_tuple([_py(p) for p in policies]),
        parties=_tuple([_py(p) for p in parties]),
        any_party=str(any(g.anyone for g in grants)),
        skip=_py(f"{curie(op.iri)}: {'; '.join(skip)}" if skip else None),
        sources=tuple(sorted(sources)),
    )


def extract_smoke(model: Model) -> SmokeModel:
    """The smoke model of ``model``: one probe per operation with a method and a path, by IRI."""
    with view_errors():
        grants = _grants(model)
        ops = [op for op in model.operations if op.method is not None and op.path is not None]
        probes = tuple(_probe(model, op, grants.get(op.iri, [])) for op in ops)
    seen: set[str] = set()
    for probe in probes:
        if probe.name in seen:
            raise GeneratorError(
                model.subject, HYDRA.Operation, f"two tests would be named {probe.name}; rename one IRI"
            )
        seen.add(probe.name)
    return SmokeModel(model_stem=model.path.stem, model_hash=model.hash, probes=probes)


# ── rendering ───────────────────────────────────────────────────────────────


def render_smoke(smoke: SmokeModel) -> dict[str, str]:
    """{"test_smoke.py": text}."""
    return {FILE: _environment().get_template(TEMPLATE).render(t=smoke)}


def generate_smoke(trig_path) -> dict[str, str]:
    """{"test_smoke.py": text}: one smoke test per operation of the model at ``trig_path``."""
    return render_smoke(extract_smoke(load(trig_path)))


def smoke_sources(trig_path) -> dict[str, tuple[str, ...]]:
    """{"test_smoke.py": full IRIs}: each operation, the shapes it accepts and
    returns (with its error statuses'), the examples it sends and the
    policies and parties governing it."""
    smoke = extract_smoke(load(trig_path))
    return {FILE: tuple(sorted({iri for p in smoke.probes for iri in p.sources}))}


__all__ = ["FILE", "ProbeModel", "SmokeModel", "extract_smoke", "generate_smoke", "render_smoke", "smoke_sources"]

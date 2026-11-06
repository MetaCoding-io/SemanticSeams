"""The DDD profile, ``profiles/ddd`` beside expense chapter 11 (ADR-0033, M029/S02/T03).

Chapter 11 attaches the profile with ``seam:conformsTo``, and ``seams check`` passes on
it and names it. Each rule then has one inline negative fixture, checked through
``seams_cli.check.check_profile`` with an exact finding: the fixture graph is
validated against the profile that a minimal model in tmp_path attaches, with the
profile directory copied from chapter 11. The parity tests pin the three rules that
restate a gate query to that query: on chapter 11, on chapter 11 with the fact the
rule reads removed, and on the rule's fixture, the focus nodes the rule reports are
the query's rows.
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path
from typing import cast

import pyshacl
import pytest
import rdflib
import seams
from rdflib import RDF, URIRef
from seams_cli import load_project
from seams_cli.__main__ import main
from seams_cli.check import Finding, check_profile, model_graph

ROOT = Path(__file__).resolve().parents[1]
CHAPTER_11 = ROOT / "examples" / "expenses" / "chapter-11"
PROFILE_DIR = CHAPTER_11 / "profiles" / "ddd"
PROFILE = "https://example.org/profiles/ddd"
QUERIES = ROOT / "docs" / "queries"
SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
SEAM = rdflib.Namespace("https://w3id.org/seams/seam#")
DDD = rdflib.Namespace(PROFILE + "#")
EX = "https://example.org/expenses/"
X = "https://example.org/x/"

PREFIXES = f"""\
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix hydra: <http://www.w3.org/ns/hydra/core#> .
@prefix seam:  <https://w3id.org/seams/seam#> .
@prefix arch:  <https://w3id.org/seams/arch#> .
@prefix ifml:  <https://w3id.org/seams/ifml#> .
@prefix proc:  <https://w3id.org/seams/proc#> .
@prefix state: <https://w3id.org/seams/state#> .
@prefix :      <{X}> .
"""

# A UI event that starts a process whose task writes a shape, and no policy.
UNGOVERNED = """
:submit a ifml:Event ; seam:submitsTo :op ; seam:triggers :process .
:op a hydra:Operation .
:process seam:detailedBy :bpmn .
:persist seam:inModel :bpmn ; seam:writes :Shape .
"""

# A transition of a lifecycle that no element fires.
UNFIRED = """
:t_close a state:Transition ; seam:inModel :lifecycle .
"""

# Two contexts with no relationship; an element of one reads the other's shape.
UNTRANSLATED = """
:a a arch:BoundedContext ; seam:owns :a_data .
:b a arch:BoundedContext ; seam:owns :b_ui .
:Shape seam:inModel :a_data .
:list seam:inModel :b_ui ; seam:reads :Shape .
"""

# b is a conformist downstream of a, so its write is not untranslated, but a
# still owns the shape b writes.
TWO_WRITERS = """
:a a arch:BoundedContext ; seam:owns :a_data .
:b a arch:BoundedContext ; seam:owns :b_ui .
:a_to_b a arch:ContextRelationship ;
    arch:upstream :a ; arch:downstream :b ; arch:relationshipType arch:Conformist .
:Shape seam:inModel :a_data .
:form seam:inModel :b_ui ; seam:writes :Shape .
"""

TWO_LIFECYCLES = """
:Order seam:lifecycle :order_lifecycle , :shipping_lifecycle .
:OrderShape sh:targetClass :Order ; seam:storedIn :db .
"""

NO_STORE = """
:Order seam:lifecycle :order_lifecycle .
:OrderShape sh:targetClass :Order .
"""

TWO_STORES = """
:Order seam:lifecycle :order_lifecycle .
:OrderShape sh:targetClass :Order ; seam:storedIn :db .
:OrderSummaryShape sh:targetClass :Order ; seam:storedIn :cache .
"""

NO_KEY = """
:Order seam:lifecycle :order_lifecycle .
:OrderShape sh:targetClass :Order ; seam:storedIn :db .
:place seam:inModel :order_bpmn ; seam:writes :OrderShape .
:ordering seam:detailedBy :order_bpmn .
"""

TWO_KEYS = """
:Order seam:lifecycle :order_lifecycle .
:OrderShape sh:targetClass :Order ; seam:storedIn :db .
:place seam:inModel :order_bpmn ; seam:writes :OrderShape .
:ordering seam:detailedBy :order_bpmn ; proc:correlationKey :order .
:ship seam:inModel :shipping_bpmn ; seam:writes :OrderShape .
:shipping seam:detailedBy :shipping_bpmn ; proc:correlationKey :customer .
"""

# An aggregate whose members (ADR-0035) are not in one store: the order shape is
# its own and stored, the line shape is another class's and stored elsewhere, or
# nowhere. The aggregate's own shapes are in one store, so only the member rule fails.
TWO_MEMBER_STORES = """
:Order seam:lifecycle :order_lifecycle ; seam:aggregateMember :OrderShape , :LineShape .
:OrderShape sh:targetClass :Order ; seam:storedIn :db .
:LineShape sh:targetClass :Line ; seam:storedIn :cache .
"""

UNSTORED_MEMBER = """
:Order seam:lifecycle :order_lifecycle ; seam:aggregateMember :OrderShape , :LineShape .
:OrderShape sh:targetClass :Order ; seam:storedIn :db .
:LineShape sh:targetClass :Line .
"""

# One exact finding per rule (ADR-0033 section 2): focus node, no path, message.
NEGATIVE = [
    pytest.param(
        UNGOVERNED,
        f"{X}submit - reaches {X}persist, which seam:writes {X}Shape, and neither the event nor the operation "
        "it seam:submitsTo is seam:governedBy a policy",
        id="governed-writes",
    ),
    pytest.param(
        UNFIRED,
        f"{X}t_close - is a transition of {X}lifecycle that no element seam:fires, so no modeled behavior can cause it",
        id="fired-transitions",
    ),
    pytest.param(
        UNTRANSLATED,
        f"{X}list - in {X}b, seam:reads or seam:writes {X}Shape, which {X}a seam:owns, with no arch:Conformist or "
        "arch:SharedKernel relationship and no translating hydra:Operation",
        id="translated-access",
    ),
    pytest.param(
        TWO_WRITERS,
        f"{X}Shape - is seam:writes of {X}form, in {X}b, but {X}a seam:owns the shape's model",
        id="one-writing-context",
    ),
    pytest.param(
        TWO_LIFECYCLES,
        f"{X}Order - names two seam:lifecycle state machines, {X}order_lifecycle and {X}shipping_lifecycle",
        id="one-lifecycle",
    ),
    pytest.param(
        NO_STORE,
        f"{X}Order - is an aggregate none of whose shapes is seam:storedIn a store",
        id="no-store",
    ),
    pytest.param(
        TWO_STORES,
        f"{X}Order - is an aggregate whose shapes are seam:storedIn two stores, {X}cache and {X}db",
        id="two-stores",
    ),
    pytest.param(
        TWO_MEMBER_STORES,
        f"{X}Order - has seam:aggregateMember shapes seam:storedIn two stores, {X}cache and {X}db, "
        "so they cannot commit in one transaction",
        id="two-member-stores",
    ),
    pytest.param(
        UNSTORED_MEMBER,
        f"{X}Order - has seam:aggregateMember {X}LineShape, which is seam:storedIn no store, "
        "so it has no transaction to commit in",
        id="unstored-member",
    ),
    pytest.param(
        NO_KEY,
        f"{X}Order - is written by {X}ordering, and no process that writes the aggregate states a proc:correlationKey",
        id="no-correlation-key",
    ),
    pytest.param(
        TWO_KEYS,
        f"{X}Order - is written by processes keyed by two proc:correlationKey values, {X}customer and {X}order",
        id="two-correlation-keys",
    ),
]

# The rules that restate a query, the query and the variable naming the focus node.
BUNDLED = {
    DDD.GovernedWrites: (QUERIES / "gates" / "ungoverned-writes.rq", "event"),
    DDD.FiredTransitions: (QUERIES / "coverage" / "unfired-transitions.rq", "transition"),
    DDD.TranslatedAccess: (QUERIES / "gates" / "untranslated-cross-context-calls.rq", "element"),
}
FIXTURE = {DDD.GovernedWrites: UNGOVERNED, DDD.FiredTransitions: UNFIRED, DDD.TranslatedAccess: UNTRANSLATED}


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


@pytest.fixture(scope="module")
def attached(tmp_path_factory) -> Path:
    """A model with nothing in it but the profile attachment, beside a copy of profiles/ddd."""
    root = tmp_path_factory.mktemp("ddd")
    shutil.copytree(PROFILE_DIR, root / "profiles" / "ddd")
    model = root / "model.trig"
    model.write_text(
        f"<urn:seams:graph:seams> {{ <urn:seams:graph:manifest> <{SEAM.conformsTo}> <{PROFILE}> . }}\n",
        encoding="utf-8",
    )
    return model


@pytest.fixture(scope="module")
def chapter_11() -> rdflib.Graph:
    return model_graph(CHAPTER_11)


def _graph(turtle: str) -> rdflib.Graph:
    return rdflib.Graph().parse(data=PREFIXES + turtle, format="turtle")


def _shapes() -> rdflib.Graph:
    return rdflib.Graph().parse(PROFILE_DIR / "ddd-shapes.ttl", format="turtle")


def _focus(graph: rdflib.Graph, rule: URIRef) -> set[str]:
    """The focus nodes of ``rule``'s results on ``graph``."""
    _conforms, report, _text = pyshacl.validate(graph, shacl_graph=_shapes(), inference="none")
    results = cast(rdflib.Graph, report)
    return {
        str(results.value(result, SH.focusNode))
        for result in results.subjects(RDF.type, SH.ValidationResult)
        if results.value(result, SH.sourceShape) == rule
    }


def _rows(graph: rdflib.Graph, query: Path, variable: str) -> set[str]:
    return {str(row[variable]) for row in graph.query(query.read_text(encoding="utf-8"))}  # type: ignore[index]


def _without(graph: rdflib.Graph, predicate: URIRef, obj: URIRef | None = None) -> rdflib.Graph:
    copy = rdflib.Graph()
    for triple in graph:
        if triple[1] != predicate or (obj is not None and triple[2] != obj):
            copy.add(triple)
    return copy


def test_chapter_11_attaches_the_profile():
    model = load_project(CHAPTER_11).model
    profile = seams.resolve_profile(seams.load(model).ds, seams.model_dir(model))
    assert profile is not None
    assert str(profile.iri) == PROFILE
    assert profile.classes == () and profile.generators == ()


def test_seams_check_passes_on_chapter_11_and_names_the_profile(capsys):
    assert main(["check", str(CHAPTER_11)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert f"profile {PROFILE} 0 result(s)" in out
    assert [line for line in out if line.startswith(("profile ", "gate "))] == [f"profile {PROFILE} 0 result(s)"]


def test_chapter_11_lists_no_gate_the_profile_bundles():
    gates = tomllib.loads((CHAPTER_11 / "seams.toml").read_text(encoding="utf-8")).get("gates", [])
    bundled = {query.name for query, _variable in BUNDLED.values()}
    assert {Path(gate).name for gate in gates} & bundled == set()


def test_the_payment_shape_is_owned_by_the_context_that_writes_it(chapter_11):
    owners = {
        str(s) for s in chapter_11.subjects(SEAM.owns, chapter_11.value(URIRef(EX + "PaymentShape"), SEAM.inModel))
    }
    assert owners == {EX + "finance_context"}


@pytest.mark.parametrize(("turtle", "detail"), NEGATIVE)
def test_each_rule_fails_its_fixture_naming_the_fact(attached, turtle, detail):
    assert check_profile(attached, _graph(turtle)) == (PROFILE, [Finding("profile", detail)])


def test_a_dataset_with_no_facts_the_rules_read_holds(attached):
    assert check_profile(attached, _graph(":x seam:inModel :m .")) == (PROFILE, [])


def test_pill_shape_results_are_not_reported(attached):
    # A shape with no lifecycle and an operation no event submits to are not
    # aggregates or commands: pyshacl reports them, seams check does not.
    graph = _graph(":S a sh:NodeShape . :op a hydra:Operation . :feed a <https://w3id.org/seams/comm#Channel> .")
    assert _focus(graph, DDD.Aggregate) == {X + "S"}
    assert _focus(graph, DDD.Command) == {X + "op"}
    assert check_profile(attached, graph) == (PROFILE, [])


@pytest.mark.parametrize("rule", sorted(BUNDLED), ids=lambda rule: str(rule).rsplit("#", 1)[1])
def test_a_bundled_rule_reports_the_rows_of_its_query(chapter_11, rule):
    query, variable = BUNDLED[rule]
    graphs = {
        "chapter 11": chapter_11,
        "fixture": _graph(FIXTURE[rule]),
        # Chapter 11 without the fact the rule reads: its policies, its fired
        # transitions, its conformist relationship.
        "removed": {
            DDD.GovernedWrites: _without(chapter_11, SEAM.governedBy),
            DDD.FiredTransitions: _without(chapter_11, SEAM.fires),
            DDD.TranslatedAccess: _without(chapter_11, URIRef("https://w3id.org/seams/arch#relationshipType")),
        }[rule],
    }
    for name, graph in graphs.items():
        rows = _rows(graph, query, variable)
        assert _focus(graph, rule) == rows, name
        assert rows or name == "chapter 11", name


def test_the_viewer_health_of_chapter_11_reports_no_pill_and_no_unoffered_class():
    # The profile offers no classes, so it restricts nothing (ADR-0033 section 3),
    # and its pill shapes' results are not findings (section 4).
    from viewer import validation

    validation._clear_cache()
    model = load_project(CHAPTER_11).model
    ds = seams.load(model).ds
    profile = seams.resolve_profile(ds, seams.model_dir(model))
    assert profile is not None and profile.pills
    health = validation.get_model_conformance(ds, profile)
    validation._clear_cache()
    pills = {str(shape) for shape in profile.pill_sources()}
    assert health["violations"] == []
    assert [f for f in health["warnings"] + health["notes"] if f["sourceShape"] in pills] == []
    assert [f for f in health["warnings"] if "is not a class the profile" in (f["message"] or "")] == []

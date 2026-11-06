"""The runtime's data-health report on instance data (ADR-0036, M029/S05/T02).

A profile's sh:Warning shapes with a sh:sparql constraint are instance-data rules.
``Runtime.data_health`` lifts every stored entity to RDF through its shape contract
and runs those rules on it; a broken rule is reported, never a refused write. The
model and its profile are inline: payments name the invoice they pay, and the
profile's rule reports an invoice paid more than once.
"""

from __future__ import annotations

import logging

import pytest
from rdflib import RDF, URIRef

from seams_runtime import ContractViolation, Finding, ResolutionError, Runtime, SQLiteStore, Telemetry
from seams_runtime.invariants import entity_focus, instance_rules, lift

EX = "https://example.org/billing/"
PAYMENT_SHAPE = EX + "PaymentShape"
INVOICE_SHAPE = EX + "InvoiceShape"
PROFILE = "https://example.org/profiles/billing"
FX = "https://example.org/profiles/billing#"
SEAM = "https://w3id.org/seams/seam#"

MODEL = """\
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix :       <https://example.org/billing/> .

<urn:seams:graph:model:billing_ontology> {
    :billing_ontology a seam:Model , owl:Ontology ; seam:notation seam:Ontology .
    :Invoice a owl:Class ; rdfs:label "Invoice" ; seam:inModel :billing_ontology .
    :Payment a owl:Class ; rdfs:label "Payment" ; seam:inModel :billing_ontology .
}
<urn:seams:graph:model:billing_data> {
    :billing_data a seam:Model ; seam:notation seam:ShapeGraph .
    :InvoiceShape a sh:NodeShape ; rdfs:label "Invoice" ; sh:targetClass :Invoice ; seam:inModel :billing_data ;
        sh:property [ sh:path :id ; sh:name "id" ; sh:datatype xsd:string ; sh:maxCount 1 ] ,
            [ sh:path :number ; sh:name "number" ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] .
    :PaymentShape a sh:NodeShape ; rdfs:label "Payment" ; sh:targetClass :Payment ; seam:inModel :billing_data ;
        sh:property [ sh:path :id ; sh:name "id" ; sh:datatype xsd:string ; sh:maxCount 1 ] ,
            [ sh:path :invoice ; sh:name "invoice" ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] ,
            [ sh:path :amount ; sh:name "amount" ; sh:datatype xsd:decimal ; sh:maxCount 1 ] .
}
<urn:seams:graph:model:billing_architecture> {
    :billing_architecture a seam:Model ; seam:notation seam:Architecture .
    :db a arch:Container ; rdfs:label "Billing DB" ; deploy:storeKind deploy:SQLite .
}
"""

STORED = """
    :InvoiceShape seam:storedIn :db .
    :PaymentShape seam:storedIn :db .
"""

ATTACH = f"    <urn:seams:graph:manifest> seam:conformsTo <{PROFILE}> .\n"

PROFILE_TTL = f"""\
@prefix seam: <https://w3id.org/seams/seam#> .
<{PROFILE}> a seam:Profile ; seam:profileShapes "shapes.ttl" .
"""

# PaidOnce is the instance-data rule. The other shapes are not: a sh:Violation
# sh:sparql shape and a sh:Warning shape with only core constraints are model
# rules, so the report must not run them even though their targets match.
SHAPES_TTL = f"""\
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix fx: <{FX}> .

fx:PaidOnce a sh:NodeShape ; sh:severity sh:Warning ;
    sh:targetObjectsOf <{EX}invoice> ;
    sh:sparql [ a sh:SPARQLConstraint ;
        sh:message "invoice {{$this}} is paid more than once" ;
        sh:select \"\"\"
            SELECT $this WHERE {{
                ?a <{EX}invoice> $this .
                ?b <{EX}invoice> $this .
                FILTER (STR(?a) < STR(?b))
            }}\"\"\" ] .

fx:NoPayments a sh:NodeShape ; sh:severity sh:Violation ;
    sh:targetObjectsOf <{EX}invoice> ;
    sh:sparql [ a sh:SPARQLConstraint ; sh:message "a violation is a model rule" ;
        sh:select "SELECT $this WHERE {{ ?a <{EX}invoice> $this . }}" ] .

fx:Amounted a sh:NodeShape ; sh:severity sh:Warning ;
    sh:targetSubjectsOf <{EX}invoice> ;
    sh:property [ sh:path <{EX}reference> ; sh:minCount 1 ; sh:message "a core warning is a model rule" ] .
"""


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


def project(tmp_path, *, seams: str = STORED + ATTACH, profile: str | None = PROFILE_TTL, shapes=SHAPES_TTL):
    path = tmp_path / "billing.trig"
    path.write_text(MODEL + f"\n<urn:seams:graph:seams> {{{seams}}}\n", encoding="utf-8")
    if profile is not None:
        package = tmp_path / "profiles" / "billing"
        package.mkdir(parents=True)
        (package / "profile.ttl").write_text(profile, encoding="utf-8")
        if shapes is not None:
            (package / "shapes.ttl").write_text(shapes, encoding="utf-8")
    return path


def load(path, **kw) -> Runtime:
    return Runtime.load(path, store=SQLiteStore(path.parent / "s.sqlite"), templates_dir=path.parent, **kw)


def pay(rt: Runtime, invoice: str, amount: str = "10.00") -> dict:
    return rt.write(":PaymentShape", {"invoice": invoice, "amount": amount})


def warning(invoice: str) -> Finding:
    return Finding(FX + "PaidOnce", invoice, f"invoice {invoice} is paid more than once", "Warning")


def test_an_invoice_paid_twice_is_one_warning_and_both_payments_are_stored(tmp_path):
    rt = load(project(tmp_path))
    rt.write(":InvoiceShape", {"number": "INV-1"})
    first, second = pay(rt, "INV-1"), pay(rt, "INV-1", "12.50")
    assert [r["id"] for r in rt.query(":PaymentShape")] == [first["id"], second["id"]]
    assert rt.data_health() == [warning("INV-1")]


def test_findings_are_sorted_and_a_single_payment_is_no_finding(tmp_path):
    rt = load(project(tmp_path))
    for invoice in ("INV-9", "INV-2", "INV-9", "INV-5", "INV-2", "INV-9"):
        pay(rt, invoice)
    # INV-9's three payments make three pairs, and are still one finding.
    assert rt.data_health() == [warning("INV-2"), warning("INV-9")]


def test_an_empty_store_has_no_findings(tmp_path):
    assert load(project(tmp_path)).data_health() == []


def test_a_model_without_a_profile_reports_nothing(tmp_path, caplog):
    # The profile package is beside the model but is never read unless attached.
    rt = load(project(tmp_path, seams=STORED, shapes="this is not turtle"))
    pay(rt, "INV-1")
    pay(rt, "INV-1")
    with caplog.at_level(logging.INFO, logger="seams_runtime.runtime"):
        assert rt.data_health() == []
    assert "data health: the model attaches no profile" in caplog.text


def test_an_unknown_profile_raises_naming_seam_conforms_to(tmp_path):
    rt = load(project(tmp_path, profile=None))
    with pytest.raises(ResolutionError) as raised:
        rt.data_health()
    assert str(raised.value.predicate) == SEAM + "conformsTo"
    assert PROFILE in raised.value.detail


def test_a_missing_shapes_file_raises_naming_seam_profile_shapes(tmp_path):
    rt = load(project(tmp_path, shapes=None))
    with pytest.raises(ResolutionError) as raised:
        rt.data_health()
    assert (str(raised.value.subject), str(raised.value.predicate)) == (PROFILE, SEAM + "profileShapes")
    assert raised.value.detail == "profiles/billing/shapes.ttl: no such file"


def test_a_write_never_runs_the_report(tmp_path, monkeypatch):
    rt = load(project(tmp_path))

    def refuse(*_a, **_k):
        raise AssertionError("a write ran the data-health report")

    monkeypatch.setattr("seams_runtime.runtime._data_health", refuse)
    pay(rt, "INV-1")
    pay(rt, "INV-1")
    assert len(rt.query(":PaymentShape")) == 2


def test_the_report_logs_its_count(tmp_path, caplog):
    rt = load(project(tmp_path))
    pay(rt, "INV-1")
    pay(rt, "INV-1")
    with caplog.at_level(logging.INFO, logger="seams_runtime.runtime"):
        rt.data_health()
    assert f"data health {PROFILE} 1 warning(s)" in caplog.messages


def test_the_report_emits_a_data_health_span_with_its_count(tmp_path):
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    rt = load(project(tmp_path), telemetry=Telemetry(provider.get_tracer("test")))
    for invoice in ("INV-1", "INV-1", "INV-2", "INV-2"):
        pay(rt, invoice)
    rt.data_health()
    provider.shutdown()
    (span,) = [s for s in exporter.get_finished_spans() if s.name == "seams.data_health"]
    assert dict(span.attributes) == {"seams.profile.iri": PROFILE, "seams.data_health.count": 2}


def test_the_lift_uses_only_the_shape_paths(tmp_path):
    rt = load(project(tmp_path))
    rt.store.put_entity("a/b c", PAYMENT_SHAPE, {"invoice": "INV-1", "amount": "1.00"}, correlation_key="k1")
    data = lift(rt.model, rt.store)
    focus = entity_focus("a/b c")
    assert str(focus) == "urn:seams:entity:a%2Fb%20c"
    assert sorted(str(p) for p in data.predicates(focus, None)) == [EX + "amount", EX + "invoice"]
    assert (None, RDF.type, None) not in data
    assert not [t for t in data if any(str(term).startswith(SEAM) for term in t)]


def test_a_stored_entity_the_contract_refuses_is_named(tmp_path):
    rt = load(project(tmp_path))
    rt.store.put_entity("bad", PAYMENT_SHAPE, {"invoice": "INV-1", "amount": "lots"})
    with pytest.raises(ContractViolation) as raised:
        rt.data_health()
    assert raised.value.shape == PAYMENT_SHAPE
    assert str(raised.value.focus) == "urn:seams:entity:bad"


def test_only_sparql_warning_shapes_are_instance_rules(tmp_path):
    from seams import model_dir, resolve_profile

    rt = load(project(tmp_path))
    profile = resolve_profile(rt.model.ds, model_dir(rt.model.path))
    assert profile is not None
    assert instance_rules(profile.shapes) == [URIRef(FX + "PaidOnce")]

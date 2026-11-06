"""The ADR-0030 typed views: ``Domain`` and ``BoundedContext`` (M028/S03/T02)."""

from pathlib import Path

import pytest
import seams
from rdflib import URIRef
from seams import ARCH, SEAM, BoundedContext, Domain, ResolutionError

EX = "https://example.org/expenses/"

ARCHITECTURE = """
    :finance a arch:Domain ; rdfs:label "Finance" ;
        arch:classification arch:Core ;
        arch:contains :finance_context , :finance_system .
    :expense_management a arch:Domain ; rdfs:label "Expense Management" ;
        arch:classification arch:Supporting ;
        arch:contains :expense_system , :expense_context .
    :expense_system a arch:System ; rdfs:label "Expenses" ; arch:contains :expense_api , :expense_ui .
    :finance_system a arch:System ; rdfs:label "Finance" ; arch:contains :payout_worker .
    :expense_api a arch:Container ; rdfs:label "Expense API" .
    :expense_ui a arch:Container ; rdfs:label "Expense UI" .
    :payout_worker a arch:Container ; rdfs:label "Payout Worker" .
    :expense_context a arch:BoundedContext ; rdfs:label "Expenses" .
    :finance_context a arch:BoundedContext ; rdfs:label "Payouts" .
"""

SEAMS = """
    :expense_context seam:owns :expense_ontology , :expense_ifml , :approval_bpmn .
    :finance_context seam:owns :payout_bpmn , :finance_ontology .
    :expense_ui seam:presents :expense_ifml .
    :expense_api seam:executes :approval_process .
    :payout_worker seam:executes :payout_process .
    :expense_architecture seam:notation seam:C4 .
    :expense_ontology seam:notation seam:Ontology .
    :finance_ontology seam:notation seam:Ontology .
    :expense_ifml seam:notation seam:IFML .
    :approval_bpmn seam:notation seam:BPMN .
    :payout_bpmn seam:notation seam:BPMN .
    :approval_process seam:inModel :approval_bpmn .
    :payout_process seam:inModel :payout_bpmn .
"""


def trig(architecture: str = ARCHITECTURE, seams_graph: str = SEAMS) -> str:
    return f"""
@prefix : <{EX}> .
@prefix arch: <https://w3id.org/seams/arch#> .
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix proc: <https://w3id.org/seams/proc#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

<urn:seams:graph:model:expense_architecture> {{
    :expense_architecture a seam:Model .
{architecture}
}}
<urn:seams:graph:model:expense_ontology> {{ :expense_ontology a seam:Model , owl:Ontology . }}
<urn:seams:graph:model:finance_ontology> {{ :finance_ontology a seam:Model , owl:Ontology . }}
<urn:seams:graph:model:approval_bpmn> {{ :approval_process a proc:Process ; rdfs:label "Approval" . }}
<urn:seams:graph:model:payout_bpmn> {{ :payout_process a proc:Process ; rdfs:label "Payout" . }}
<urn:seams:graph:seams> {{
{seams_graph}
}}
"""


def load(tmp_path: Path, text: str) -> seams.Model:
    path = tmp_path / "model.trig"
    path.write_text(text)
    return seams.Model(path, check_versions=False, check_imports=False)


@pytest.fixture
def model(tmp_path: Path) -> seams.Model:
    return load(tmp_path, trig())


def context(model: seams.Model, name: str) -> BoundedContext:
    return model.architecture.contexts().by_iri(URIRef(EX + name))


def test_domains_and_contexts_are_listed_by_iri(model: seams.Model):
    arch = model.architecture
    assert [d.label for d in arch.domains()] == ["Expense Management", "Finance"]
    assert arch.contexts().iris() == (URIRef(EX + "expense_context"), URIRef(EX + "finance_context"))
    assert all(isinstance(d, Domain) for d in arch.domains())


def test_domain_classification_and_label(model: seams.Model):
    finance = model.architecture.domains().by_iri(URIRef(EX + "finance"))
    assert finance.classification == ARCH.Core
    # The label comes from the shipped arch vocabulary, not the local name.
    assert finance.classification_label == "core"
    support = model.architecture.domains().by_iri(URIRef(EX + "expense_management"))
    assert support.classification_label == "supporting"


def test_a_label_the_model_states_wins(tmp_path: Path):
    model = load(tmp_path, trig(ARCHITECTURE + '    arch:Core rdfs:label "kern" .\n'))
    assert model.architecture.domains().by_iri(URIRef(EX + "finance")).classification_label == "kern"


def test_domain_systems_and_contexts(model: seams.Model):
    support = model.architecture.domains().by_iri(URIRef(EX + "expense_management"))
    assert support.systems.iris() == (URIRef(EX + "expense_system"),)
    assert support.contexts.iris() == (URIRef(EX + "expense_context"),)
    # Same interned objects as the layer's own lists.
    assert support.contexts[0] is context(model, "expense_context")


def test_context_domain_models_and_ontology(model: seams.Model):
    expenses = context(model, "expense_context")
    assert expenses.domain.iri == URIRef(EX + "expense_management")
    assert expenses.models.iris() == tuple(
        URIRef(EX + m) for m in ("approval_bpmn", "expense_ifml", "expense_ontology")
    )
    assert expenses.ontology.iri == URIRef(EX + "expense_ontology")
    assert context(model, "finance_context").ontology.iri == URIRef(EX + "finance_ontology")


def test_containers_are_derived_from_presents_and_executes(model: seams.Model):
    # expense_ui presents the owned IFML model; expense_api executes a process
    # in the owned BPMN model.
    assert context(model, "expense_context").containers.iris() == (
        URIRef(EX + "expense_api"),
        URIRef(EX + "expense_ui"),
    )
    assert context(model, "finance_context").containers.iris() == (URIRef(EX + "payout_worker"),)


def test_a_model_without_contexts_has_none(tmp_path: Path):
    model = load(tmp_path, trig(architecture="", seams_graph=""))
    assert model.architecture.domains() == ()
    assert model.architecture.contexts() == ()


def test_chat_app_declares_no_domain():
    model = seams.load(Path(__file__).resolve().parent.parent / "examples/chat-app/chat-app.trig")
    assert model.architecture.domains() == ()
    assert model.architecture.contexts() == ()


# ── negative paths: each error names the element and the predicate ──


def test_context_with_no_ontology_raises(tmp_path: Path):
    model = load(tmp_path, trig(seams_graph=SEAMS.replace(" , :finance_ontology", "")))
    with pytest.raises(ResolutionError) as raised:
        _ = context(model, "finance_context").ontology
    assert raised.value.subject == str(URIRef(EX + "finance_context"))
    assert raised.value.predicate == str(SEAM.owns)
    assert "found none" in str(raised.value)


def test_context_with_two_ontologies_raises(tmp_path: Path):
    model = load(tmp_path, trig(seams_graph=SEAMS + "    :finance_context seam:owns :expense_ontology .\n"))
    with pytest.raises(ResolutionError) as raised:
        _ = context(model, "finance_context").ontology
    assert raised.value.subject == str(URIRef(EX + "finance_context"))
    assert raised.value.predicate == str(SEAM.owns)
    assert "expense_ontology" in str(raised.value) and "finance_ontology" in str(raised.value)


def test_context_in_no_domain_raises(tmp_path: Path):
    model = load(tmp_path, trig(ARCHITECTURE.replace(":finance_context , :finance_system", ":finance_system")))
    with pytest.raises(ResolutionError) as raised:
        _ = context(model, "finance_context").domain
    assert raised.value.subject == str(URIRef(EX + "finance_context"))
    assert raised.value.predicate == str(ARCH.contains)


def test_context_in_two_domains_raises(tmp_path: Path):
    model = load(tmp_path, trig(ARCHITECTURE + "    :expense_management arch:contains :finance_context .\n"))
    with pytest.raises(ResolutionError) as raised:
        _ = context(model, "finance_context").domain
    assert raised.value.predicate == str(ARCH.contains)


def test_domain_without_classification_raises(tmp_path: Path):
    model = load(tmp_path, trig(ARCHITECTURE.replace("arch:classification arch:Core ;", "")))
    with pytest.raises(ResolutionError) as raised:
        _ = model.architecture.domains().by_iri(URIRef(EX + "finance")).classification
    assert raised.value.subject == str(URIRef(EX + "finance"))
    assert raised.value.predicate == str(ARCH.classification)


def test_literal_classification_raises(tmp_path: Path):
    model = load(tmp_path, trig(ARCHITECTURE.replace("arch:classification arch:Core", 'arch:classification "core"')))
    with pytest.raises(ResolutionError) as raised:
        _ = model.architecture.domains().by_iri(URIRef(EX + "finance")).classification_label
    assert raised.value.predicate == str(ARCH.classification)

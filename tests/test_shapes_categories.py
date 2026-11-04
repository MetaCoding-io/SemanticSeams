"""Shapes target classes, sh:name, categories and flattened sh:node (ADR-0023) in the
typed shape view (``seams.views.shapes``) and the seam shapes.

Every model is inline TriG built from ``model()``: an ontology with a category of
expense states and one of approval outcomes, the expense lifecycle whose states are
typed with the category, and a shapes graph. The states are declared out of IRI order
and their IRIs sort differently from their lifecycle order, so the view's ordering is
what the tests see. Each negative case breaks one fact and asserts the error names
the subject, the predicate and the field."""

from __future__ import annotations

from pathlib import Path

import pyshacl
import pytest
import seams
from rdflib import RDF, RDFS, XSD, Graph, Literal, Namespace
from rdflib.namespace import SH
from seams import Field, FlatNode, ResolutionError

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
SHAPES_FILE = ONTOLOGY / "shapes" / "seam-shapes.ttl"
EX = Namespace("https://example.org/expenses/")
GIST = Namespace("https://w3id.org/semanticarts/ns/ontology/gist/")
SEAMSH = Namespace("https://w3id.org/seams/shapes#")

PREFIXES = """\
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix gist:  <https://w3id.org/semanticarts/ns/ontology/gist/> .
@prefix seam:  <https://w3id.org/seams/seam#> .
@prefix state: <https://w3id.org/seams/state#> .
@prefix verify: <https://w3id.org/seams/verify#> .
@prefix :      <https://example.org/expenses/> .
"""

ONTOLOGY_BODY = """
    :Expense a owl:Class ; rdfs:subClassOf gist:Transaction ; rdfs:label "Expense" ;
        seam:inModel :expense_ontology .
    :ExpenseState a owl:Class ; rdfs:subClassOf gist:Category ; rdfs:label "Expense state" ;
        seam:inModel :expense_ontology .
    :Outcome a owl:Class ; rdfs:subClassOf gist:Category ; rdfs:label "Outcome" ;
        seam:inModel :expense_ontology .
    # A category through the model's own class: ApprovalOutcome < Outcome < gist:Category.
    :ApprovalOutcome a owl:Class ; rdfs:subClassOf :Outcome ; rdfs:label "Approval outcome" ;
        seam:inModel :expense_ontology .
    :o_rejected a :ApprovalOutcome ; rdfs:label "rejected" ; seam:inModel :expense_ontology .
    :o_approved a :ApprovalOutcome ; rdfs:label "approved" ; seam:inModel :expense_ontology .
"""

# Lifecycle order is draft submitted approved rejected paid; IRI order is
# approved draft paid rejected submitted.
LIFECYCLE_BODY = """
    :s_paid      a state:State , :ExpenseState ; rdfs:label "paid"      ; seam:inModel :expense_lifecycle .
    :s_rejected  a state:State , :ExpenseState ; rdfs:label "rejected"  ; seam:inModel :expense_lifecycle .
    :s_submitted a state:State , :ExpenseState ; rdfs:label "submitted" ; seam:inModel :expense_lifecycle .
    :s_approved  a state:State , :ExpenseState ; rdfs:label "approved"  ; seam:inModel :expense_lifecycle .
    :s_draft     a state:State , :ExpenseState ; rdfs:label "draft"     ; seam:inModel :expense_lifecycle .
"""

EXPENSE_SHAPE = """
    :ExpenseShape a sh:NodeShape ; rdfs:label "Expense" ;
        sh:targetClass :Expense ;
        sh:property [ sh:path gist:description ; sh:datatype xsd:string ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:order 0 ; sh:name "description" ] ;
        sh:property [ sh:path gist:hasMagnitude ; sh:node :MoneyShape ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:order 1 ; sh:name "amount" ] ;
        sh:property [ sh:path gist:isCategorizedBy ; sh:class :ExpenseState ;
                      sh:maxCount 1 ; sh:order 3 ; sh:name "status" ] ;
        seam:lifecycle :expense_lifecycle ;
        verify:validExample :ex_lunch ;
        seam:inModel :expense_data .
"""

MONEY_SHAPE = """
    :MoneyShape a sh:NodeShape ; rdfs:label "Money" ; sh:class gist:Magnitude ;
        sh:property [ sh:path gist:numericValue ; sh:datatype xsd:decimal ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:minInclusive 0.01 ] ;
        sh:property [ sh:path gist:hasUnitOfMeasure ; sh:hasValue :USD ] ;
        sh:property [ sh:path gist:hasAspect ; sh:hasValue :monetary_value ] ;
        seam:inModel :expense_data .
"""

# The same fields as ExpenseShape in today's notation: flat paths, a copied list.
OLD_EXPENSE_SHAPE = """
    :OldExpenseShape a sh:NodeShape ; rdfs:label "Old expense" ;
        sh:property [ sh:path :description ; sh:datatype xsd:string ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:order 0 ] ;
        sh:property [ sh:path :amount ; sh:datatype xsd:decimal ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:order 1 ] ;
        sh:property [ sh:path :status ; sh:datatype xsd:string ; sh:maxCount 1 ; sh:order 3 ;
                      sh:in ( "draft" "submitted" "approved" "rejected" "paid" ) ] ;
        seam:inModel :expense_data .
"""

APPROVAL_SHAPE = """
    :ApprovalShape a sh:NodeShape ; rdfs:label "Approval" ;
        sh:property [ sh:path :decision ; sh:class :ApprovalOutcome ;
                      sh:minCount 1 ; sh:maxCount 1 ; sh:order 0 ] ;
        sh:property [ sh:path :verdict ; sh:in ( :o_rejected :o_approved ) ; sh:order 1 ;
                      rdfs:label "Verdict" ] ;
        seam:inModel :expense_data .
"""

EXAMPLE = """
    :ex_lunch gist:description "Team lunch" ;
        gist:hasMagnitude [ gist:numericValue 42.50 ; gist:hasUnitOfMeasure :USD ] ;
        gist:isCategorizedBy :s_submitted ;
        seam:inModel :expense_data .
"""

SHAPES_BODY = EXPENSE_SHAPE + MONEY_SHAPE + OLD_EXPENSE_SHAPE + APPROVAL_SHAPE + EXAMPLE


def model(
    shapes: str = SHAPES_BODY,
    lifecycle: str = LIFECYCLE_BODY,
    ontology: str = ONTOLOGY_BODY,
    extra: str = "",
) -> str:
    return f"""{PREFIXES}
<urn:seams:graph:model:expense_ontology> {{
    :expense_ontology a seam:Model , owl:Ontology ;
        seam:notation seam:Ontology ;
        rdfs:label "Expense Ontology" ;
        owl:versionIRI <https://example.org/expenses/expense_ontology/1.0> ;
        owl:imports <https://w3id.org/semanticarts/ontology/gistCore14.0.0> .
{ontology}}}

<urn:seams:graph:model:expense_lifecycle> {{
    :expense_lifecycle a state:StateMachine , seam:Model ;
        seam:notation seam:Statechart ;
        rdfs:label "Expense Lifecycle" ;
        state:initial :s_draft ;
        state:hasState :s_draft , :s_submitted , :s_approved , :s_rejected , :s_paid ;
        state:hasTransition :t_submit , :t_approve , :t_reject , :t_pay .
{lifecycle}
    :t_submit  a state:Transition ; state:from :s_draft     ; state:to :s_submitted ; seam:inModel :expense_lifecycle .
    :t_approve a state:Transition ; state:from :s_submitted ; state:to :s_approved  ; seam:inModel :expense_lifecycle .
    :t_reject  a state:Transition ; state:from :s_submitted ; state:to :s_rejected  ; seam:inModel :expense_lifecycle .
    :t_pay     a state:Transition ; state:from :s_approved  ; state:to :s_paid      ; seam:inModel :expense_lifecycle .
}}

<urn:seams:graph:model:expense_data> {{
    :expense_data a seam:Model ; seam:notation seam:ShapeGraph ; rdfs:label "Expense Data" .
{shapes}}}
{extra}"""


def load(tmp_path: Path, text: str) -> seams.Model:
    path = tmp_path / "model.trig"
    path.write_text(text, encoding="utf-8")
    return seams.load(path, ontology_dir=ONTOLOGY)


def fields(m: seams.Model, shape: str) -> dict[str, Field]:
    return {f.name: f for f in m.shapes.by_iri(EX[shape]).fields()}


def fields_error(tmp_path: Path, text: str, shape: str = "ExpenseShape") -> ResolutionError:
    m = load(tmp_path, text)
    with pytest.raises(ResolutionError) as err:
        m.shapes.by_iri(EX[shape]).fields()
    return err.value


def wire(f: Field) -> tuple[object, ...]:
    """What a form, a schema and a payload see of a field."""
    return (f.name, f.label, f.datatype, f.min_count, f.max_count, f.order, f.max_length, f.editor, f.options)


# ── positive: the view ──


def test_a_category_field_lists_its_members_labels_in_lifecycle_order(tmp_path: Path) -> None:
    status = fields(load(tmp_path, model()), "ExpenseShape")["status"]
    assert status.iri == GIST.isCategorizedBy
    assert status.category == EX.ExpenseState
    assert status.options == ("draft", "submitted", "approved", "rejected", "paid")
    assert status.members == (EX.s_draft, EX.s_submitted, EX.s_approved, EX.s_rejected, EX.s_paid)


def test_new_notation_fields_read_as_the_old_ones_on_the_wire(tmp_path: Path) -> None:
    m = load(tmp_path, model())
    new, old = fields(m, "ExpenseShape"), fields(m, "OldExpenseShape")
    assert list(new) == list(old) == ["description", "amount", "status"]
    for name in new:
        assert wire(new[name]) == wire(old[name]), name
    # A category field without sh:datatype carries its labels as xsd:string, as the copied list did.
    assert new["status"].datatype == old["status"].datatype == XSD.string


def test_a_category_of_non_states_is_in_iri_order_and_reached_through_own_subclasses(tmp_path: Path) -> None:
    decision = fields(load(tmp_path, model()), "ApprovalShape")["decision"]
    assert decision.category == EX.ApprovalOutcome
    assert decision.members == (EX.o_approved, EX.o_rejected)
    assert decision.options == ("approved", "rejected")


def test_an_sh_in_of_iris_keeps_list_order_and_reads_labels(tmp_path: Path) -> None:
    verdict = fields(load(tmp_path, model()), "ApprovalShape")["verdict"]
    assert verdict.members == (EX.o_rejected, EX.o_approved)
    assert verdict.options == ("rejected", "approved")
    assert verdict.category is None


def test_sh_name_is_the_name_and_rdfs_label_the_label(tmp_path: Path) -> None:
    m = load(tmp_path, model())
    expense, approval = fields(m, "ExpenseShape"), fields(m, "ApprovalShape")
    assert expense["description"].iri == GIST.description and expense["description"].label == "description"
    assert approval["verdict"].name == "verdict" and approval["verdict"].label == "Verdict"


def test_sh_name_is_no_longer_read_as_a_label(tmp_path: Path) -> None:
    shape = """
    :NamedShape a sh:NodeShape ;
        sh:property [ sh:path :paid_on ; sh:datatype xsd:date ; sh:name "paidOn" ] ;
        seam:inModel :expense_data .
"""
    (f,) = fields(load(tmp_path, model(shapes=shape)), "NamedShape").values()
    assert (f.name, f.label) == ("paidOn", "paidOn")


def test_a_flattened_field_takes_the_free_propertys_constraints(tmp_path: Path) -> None:
    amount = fields(load(tmp_path, model()), "ExpenseShape")["amount"]
    assert amount.iri == GIST.hasMagnitude
    assert (amount.datatype, amount.min_count, amount.max_count, amount.order) == (XSD.decimal, 1, 1, 1)
    assert amount.node == FlatNode(
        shape=EX.MoneyShape,
        node_class=GIST.Magnitude,
        free_path=GIST.numericValue,
        fixed=((GIST.hasAspect, EX.monetary_value), (GIST.hasUnitOfMeasure, EX.USD)),
    )


def test_a_flat_field_has_no_node_category_or_members(tmp_path: Path) -> None:
    for f in fields(load(tmp_path, model()), "OldExpenseShape").values():
        assert (f.node, f.category, f.members) == (None, None, ())


def test_a_flattened_category_free_property_gets_options(tmp_path: Path) -> None:
    shape = """
    :TaggedShape a sh:NodeShape ;
        sh:property [ sh:path :tag ; sh:node :TagShape ; sh:name "tag" ] ;
        seam:inModel :expense_data .
    :TagShape a sh:NodeShape ;
        sh:property [ sh:path gist:isCategorizedBy ; sh:class :ApprovalOutcome ; sh:maxCount 1 ] ;
        sh:property [ sh:path gist:hasAspect ; sh:hasValue :review ] ;
        seam:inModel :expense_data .
"""
    tag = fields(load(tmp_path, model(shapes=shape)), "TaggedShape")["tag"]
    assert tag.options == ("approved", "rejected") and tag.node is not None


def test_target_class_is_the_ontology_class(tmp_path: Path) -> None:
    m = load(tmp_path, model())
    target = m.shapes.by_iri(EX.ExpenseShape).target_class
    assert target is not None and target.iri == EX.Expense and target.label == "Expense"
    assert m.shapes.by_iri(EX.OldExpenseShape).target_class is None


def test_example_values_read_through_the_node_and_members_as_labels(tmp_path: Path) -> None:
    shape = load(tmp_path, model()).shapes.by_iri(EX.ExpenseShape)
    values = [(f.name, v) for f, v in shape.example_values(EX.ex_lunch)]
    assert values == [
        ("description", Literal("Team lunch")),
        ("amount", Literal("42.50", datatype=XSD.decimal)),
        ("status", Literal("submitted")),
    ]


def test_unreachable_states_come_last_by_iri(tmp_path: Path) -> None:
    lifecycle = (
        LIFECYCLE_BODY
        + """
    :expense_lifecycle state:hasState :s_archived , :s_abandoned .
    :s_archived  a state:State , :ExpenseState ; rdfs:label "archived"  ; seam:inModel :expense_lifecycle .
    :s_abandoned a state:State , :ExpenseState ; rdfs:label "abandoned" ; seam:inModel :expense_lifecycle .
"""
    )
    status = fields(load(tmp_path, model(lifecycle=lifecycle)), "ExpenseShape")["status"]
    assert status.options == ("draft", "submitted", "approved", "rejected", "paid", "abandoned", "archived")


def test_the_same_model_gives_the_same_fields(tmp_path: Path) -> None:
    first = fields(load(tmp_path, model()), "ExpenseShape")
    second = fields(load(tmp_path, model()), "ExpenseShape")
    assert first == second


# ── negative: the view names the fact ──


def test_an_empty_category_names_the_shape_and_sh_class(tmp_path: Path) -> None:
    lifecycle = LIFECYCLE_BODY.replace(" , :ExpenseState", "")
    err = fields_error(tmp_path, model(lifecycle=lifecycle))
    assert (err.subject, err.predicate) == (str(EX.ExpenseShape), str(SH["class"]))
    assert err.detail == "status: category :ExpenseState has no members"


def test_a_member_without_a_label_names_the_member_and_rdfs_label(tmp_path: Path) -> None:
    lifecycle = LIFECYCLE_BODY.replace(' ; rdfs:label "paid"     ', "")
    err = fields_error(tmp_path, model(lifecycle=lifecycle))
    assert (err.subject, err.predicate) == (str(EX.s_paid), str(RDFS.label))
    assert err.detail == "member of :ExpenseState (status of :ExpenseShape) needs exactly one rdfs:label, found none"


def test_a_member_with_two_labels_is_refused(tmp_path: Path) -> None:
    lifecycle = LIFECYCLE_BODY + ':s_paid rdfs:label "settled" .\n'
    err = fields_error(tmp_path, model(lifecycle=lifecycle))
    assert (err.subject, err.predicate) == (str(EX.s_paid), str(RDFS.label))
    assert "found 'paid', 'settled'" in err.detail


def test_two_members_with_one_label_name_both(tmp_path: Path) -> None:
    lifecycle = LIFECYCLE_BODY.replace('rdfs:label "paid"', 'rdfs:label "draft"')
    err = fields_error(tmp_path, model(lifecycle=lifecycle))
    assert (err.subject, err.predicate) == (str(EX.ExpenseShape), str(SH["class"]))
    assert err.detail == 'status: members :s_draft and :s_paid are both labelled "draft"'


def test_members_from_two_lifecycles_have_no_single_order(tmp_path: Path) -> None:
    extra = """
<urn:seams:graph:model:other_lifecycle> {
    :other_lifecycle a state:StateMachine , seam:Model ; rdfs:label "Other" ; state:initial :s_other .
    :s_other a state:State , :ExpenseState ; rdfs:label "other" ; seam:inModel :other_lifecycle .
}
"""
    err = fields_error(tmp_path, model(extra=extra))
    assert (err.subject, err.predicate) == (str(EX.ExpenseShape), str(SH["class"]))
    assert (
        err.detail
        == "status: members of :ExpenseState belong to :expense_lifecycle and :other_lifecycle; no single order"
    )


def test_states_mixed_with_other_members_have_no_single_order(tmp_path: Path) -> None:
    ontology = ONTOLOGY_BODY + ':s_extra a :ExpenseState ; rdfs:label "extra" .\n'
    err = fields_error(tmp_path, model(ontology=ontology))
    assert (err.subject, err.predicate) == (str(EX.ExpenseShape), str(SH["class"]))
    assert err.detail == "status: members of :ExpenseState mix lifecycle states with other members; no single order"


def test_an_sh_in_mixing_iris_and_literals_names_sh_in(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace("sh:in ( :o_rejected :o_approved )", 'sh:in ( :o_rejected "approved" )')
    err = fields_error(tmp_path, model(shapes=shapes), "ApprovalShape")
    assert (err.subject, err.predicate) == (str(EX.ApprovalShape), str(SH["in"]))
    assert err.detail == "verdict: sh:in mixes IRIs and literals"


def test_an_sh_node_with_two_free_properties_names_them(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace("sh:hasValue :USD", "sh:maxCount 1")
    err = fields_error(tmp_path, model(shapes=shapes))
    assert (err.subject, err.predicate) == (str(EX.ExpenseShape), str(SH.node))
    assert err.detail == (
        "amount: :MoneyShape has 2 free properties (gist:hasUnitOfMeasure, gist:numericValue); "
        "a flattened field needs exactly one"
    )


def test_an_sh_node_with_no_free_property_is_refused(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace(
        "sh:path gist:numericValue ; sh:datatype xsd:decimal ;\n                      sh:minCount 1 ; sh:maxCount 1 ; sh:minInclusive 0.01",
        "sh:path gist:numericValue ; sh:hasValue 1",
    )
    err = fields_error(tmp_path, model(shapes=shapes))
    assert (err.subject, err.predicate) == (str(EX.ExpenseShape), str(SH.node))
    assert err.detail == "amount: :MoneyShape has 0 free properties; a flattened field needs exactly one"


def test_an_sh_node_with_a_datatype_is_refused(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace("sh:node :MoneyShape ;", "sh:node :MoneyShape ; sh:datatype xsd:decimal ;")
    err = fields_error(tmp_path, model(shapes=shapes))
    assert (err.subject, err.predicate) == (str(EX.ExpenseShape), str(SH.node))
    assert err.detail.startswith("amount: sh:node :MoneyShape and sh:datatype on one property")


def test_a_free_property_without_max_count_one_is_refused(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace(
        "sh:minCount 1 ; sh:maxCount 1 ; sh:minInclusive 0.01", "sh:minCount 1 ; sh:minInclusive 0.01"
    )
    err = fields_error(tmp_path, model(shapes=shapes))
    assert (err.subject, err.predicate) == (str(EX.ExpenseShape), str(SH.node))
    assert err.detail == "amount: :MoneyShape's free property gist:numericValue needs sh:maxCount 1 and no sh:node"


def test_a_fixed_property_with_other_constraints_is_refused(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace("sh:hasValue :USD", "sh:hasValue :USD ; sh:nodeKind sh:IRI")
    err = fields_error(tmp_path, model(shapes=shapes))
    assert (err.subject, err.predicate) == (str(EX.ExpenseShape), str(SH.node))
    assert "gist:hasUnitOfMeasure needs exactly one sh:hasValue" in err.detail


@pytest.mark.parametrize("names", ['"amount" , "total"', '"paid on"'])
def test_a_bad_sh_name_names_the_shape_and_sh_name(tmp_path: Path, names: str) -> None:
    shapes = SHAPES_BODY.replace('sh:name "amount"', f"sh:name {names}")
    err = fields_error(tmp_path, model(shapes=shapes))
    assert (err.subject, err.predicate) == (str(EX.ExpenseShape), str(SH.name))
    assert err.detail.startswith("hasMagnitude: sh:name must be one name matching")


@pytest.mark.parametrize(
    ("target", "detail"),
    [
        ("gist:Magnitude", "gist:Magnitude is not an owl:Class of a seam:Ontology model"),
        (":Expense , :ExpenseState", "expected exactly one"),
    ],
)
def test_a_bad_target_class_names_the_shape_and_sh_target_class(tmp_path: Path, target: str, detail: str) -> None:
    shapes = SHAPES_BODY.replace("sh:targetClass :Expense ;", f"sh:targetClass {target} ;")
    shape = load(tmp_path, model(shapes=shapes)).shapes.by_iri(EX.ExpenseShape)
    with pytest.raises(ResolutionError) as err:
        _ = shape.target_class
    assert (err.value.subject, err.value.predicate) == (str(EX.ExpenseShape), str(SH.targetClass))
    assert detail in err.value.detail


# ── the seam shapes ──


def violations(tmp_path: Path, text: str) -> set[tuple[str, str, str]]:
    """(focus node, owning seam shape, message) of each result of the ADR-0023 seam shapes."""
    data = Graph()
    for graph in load(tmp_path, text).ds.graphs():
        data += graph
    for vocabulary in sorted(ONTOLOGY.glob("*.ttl")):
        data.parse(vocabulary)
    shapes = Graph().parse(SHAPES_FILE)
    _conforms, report, _text = pyshacl.validate(data, shacl_graph=shapes, inference="none")
    assert isinstance(report, Graph)
    ours = {SEAMSH[n] for n in ("TargetClassShape", "FieldNameShape", "CategoryFieldShape", "FlattenedFieldShape")}
    found: set[tuple[str, str, str]] = set()
    for result in report.subjects(RDF.type, SH.ValidationResult):
        source = report.value(result, SH.sourceShape)
        owner = next(iter(shapes.subjects(SH.property, source)), None) or next(
            iter(shapes.subjects(SH.sparql, source)), source
        )
        if owner in ours:
            found.add(
                (str(report.value(result, SH.focusNode)), str(owner), str(report.value(result, SH.resultMessage)))
            )
    return found


def test_the_new_notation_conforms_to_the_seam_shapes(tmp_path: Path) -> None:
    assert violations(tmp_path, model()) == set()


@pytest.mark.parametrize(
    ("change", "owner", "says"),
    [
        (("sh:targetClass :Expense ;", "sh:targetClass gist:Magnitude ;"), "TargetClassShape", "gist/Magnitude is not"),
        (
            ("sh:targetClass :Expense ;", "sh:targetClass :Expense , :Outcome ;"),
            "TargetClassShape",
            "more than one sh:targetClass",
        ),
        (('sh:name "amount"', 'sh:name "amount" , "total"'), "FieldNameShape", "more than one sh:name"),
        (('sh:name "amount"', 'sh:name "paid on"'), "FieldNameShape", "paid on is not a name"),
        (('sh:name "amount"', 'sh:name "description"'), "FieldNameShape", "two fields have the sh:name description"),
        (("sh:class :ApprovalOutcome", "sh:class :Outcome"), "CategoryFieldShape", "is a category with no members"),
        (('rdfs:label "Verdict"', 'rdfs:label "Verdict" ; sh:in ( :o_rejected "x" )'), "CategoryFieldShape", "mixes"),
        (("sh:hasValue :USD", "sh:maxCount 1"), "FlattenedFieldShape", "more than one free property"),
        (
            ("sh:node :MoneyShape ;", "sh:node :MoneyShape ; sh:datatype xsd:decimal ;"),
            "FlattenedFieldShape",
            "sh:datatype",
        ),
    ],
)
def test_each_fault_is_a_seam_shape_violation_naming_shape_and_field(
    tmp_path: Path, change: tuple[str, str], owner: str, says: str
) -> None:
    shapes = SHAPES_BODY.replace(*change)
    assert shapes != SHAPES_BODY
    found = violations(tmp_path, model(shapes=shapes))
    assert found, "no ADR-0023 seam shape fired"
    assert all(o == str(SEAMSH[owner]) for _, o, _ in found), found
    assert any(says in message and focus in message for focus, _, message in found), found


def test_a_member_fault_is_a_seam_shape_violation(tmp_path: Path) -> None:
    lifecycle = LIFECYCLE_BODY.replace(' ; rdfs:label "paid"     ', "").replace(
        'rdfs:label "rejected"', 'rdfs:label "draft"'
    )
    found = violations(tmp_path, model(lifecycle=lifecycle))
    messages = sorted(m for _, _, m in found)
    assert any(str(EX.s_paid) in m and "exactly one rdfs:label" in m for m in messages), messages
    assert any("labelled draft" in m and "status" in m for m in messages), messages


def test_an_sh_node_without_a_free_property_is_a_seam_shape_violation(tmp_path: Path) -> None:
    shapes = SHAPES_BODY.replace(
        "sh:path gist:numericValue ; sh:datatype xsd:decimal ;\n                      sh:minCount 1 ; sh:maxCount 1 ; sh:minInclusive 0.01",
        "sh:path gist:numericValue ; sh:hasValue 1",
    )
    found = violations(tmp_path, model(shapes=shapes))
    assert {(f, o) for f, o, _ in found} == {(str(EX.ExpenseShape), str(SEAMSH.FlattenedFieldShape))}
    assert all("has no free property" in m and "amount" in m for _, _, m in found)

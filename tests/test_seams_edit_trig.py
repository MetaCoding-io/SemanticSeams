"""The TriG text writer (ADR-0017): a patch edits only the text of the triples it changes.

Each case runs on a small inline fixture and pins the exact lines the edit changes, so
a writer that re-serialises, reorders or drops a comment fails here. The writer checks
every result itself (re-parse, per-graph isomorphism); the tests check the bytes.
"""

import difflib
from decimal import Decimal

import pytest
from rdflib import BNode, Literal, Namespace, URIRef
from rdflib.graph import DATASET_DEFAULT_GRAPH_ID
from rdflib.namespace import RDF, RDFS

import seams_edit.trig
from seams_edit import Patch, PatchError, apply_text, declared_graphs, text_quads

EX = Namespace("https://example.org/t/")
G = EX.g
COUNT = EX["count"]  # `EX.count` is str.count

TEXT = '''@prefix ex: <https://example.org/t/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

# The test graph.
ex:g {

    # About a.
    ex:a a ex:Thing ;
        rdfs:label "A" ;
        ex:links ex:b , ex:c , ex:d ;
        ex:count 3 .

    ex:b a ex:Thing ; rdfs:label "B" .

    # About c.
    ex:c ex:part [ a ex:Part ;
                   ex:size 2 ] ;
        ex:note """first line
second line""" ;
        ex:list ( ex:x ex:y ) .

    # About e.
    ex:e rdfs:label "E" .
}
'''


def q(s, p, o, g=G):
    return (s, p, o, g)


def changed(before: str, after: str) -> list[str]:
    diff = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), n=0)
    return [line for line in diff if line[:1] in "+-" and not line.startswith(("+++", "---"))]


def comments(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.lstrip().startswith("#")]


def edit(patch: Patch, text: str = TEXT) -> list[str]:
    after = apply_text(text, patch)
    assert comments(after) == comments(text)
    return changed(text, after)


def part_quads() -> tuple[tuple, list[tuple]]:
    """The `ex:part [ ... ]` quad, and the quads written inside its brackets."""
    quads = text_quads(TEXT)
    part = next(x for x in quads if x[1] == EX.part)
    return part, [x for x in quads if x[0] == part[2]]


# Reading ----------------------------------------------------------------------


def test_text_quads_reads_every_triple():
    quads = text_quads(TEXT)
    assert q(EX.a, COUNT, Literal(3)) in quads
    assert q(EX.c, EX.note, Literal("first line\nsecond line")) in quads
    assert len([x for x in quads if x[0] == EX.a]) == 6
    assert Patch(adds=quads).adds == quads  # sorted as a patch sorts its quads


def test_blank_nodes_have_stable_labels():
    assert text_quads(TEXT) == text_quads(TEXT)
    part, inner = part_quads()
    assert isinstance(part[2], BNode)
    assert sorted(x[1] for x in inner) == sorted([RDF.type, EX.size])


def test_relative_iris_resolve_against_the_base():
    text = "@prefix ex: <https://example.org/t/> .\nex:g { ex:m ex:payload <m.bpmn> . }\n"
    base = "file:///models/app.trig"
    assert q(EX.m, EX.payload, URIRef("file:///models/m.bpmn")) in text_quads(text, base=base)


def test_declared_graphs():
    assert declared_graphs(TEXT) == (G,)


# Empty patch ------------------------------------------------------------------


def test_empty_patch_returns_the_same_text():
    assert apply_text(TEXT, Patch()) is TEXT


# Removals ---------------------------------------------------------------------


def test_removing_a_pair_alone_on_its_line_drops_that_line():
    assert edit(Patch(removes=[q(EX.a, RDFS.label, Literal("A"))])) == ['-        rdfs:label "A" ;\n']


def test_removing_the_first_pair_keeps_the_subject():
    assert edit(Patch(removes=[q(EX.a, RDF.type, EX.Thing)])) == [
        "-    ex:a a ex:Thing ;\n",
        "+    ex:a\n",
    ]


def test_removing_the_last_pair_moves_the_final_dot():
    assert edit(Patch(removes=[q(EX.a, COUNT, Literal(3))])) == [
        "-        ex:links ex:b , ex:c , ex:d ;\n",
        "-        ex:count 3 .\n",
        "+        ex:links ex:b , ex:c , ex:d .\n",
    ]


@pytest.mark.parametrize(
    ("member", "left"),
    [(EX.b, "ex:c , ex:d"), (EX.c, "ex:b , ex:d"), (EX.d, "ex:b , ex:c")],
    ids=["first", "middle", "last"],
)
def test_removing_one_object_of_an_object_list(member, left):
    assert edit(Patch(removes=[q(EX.a, EX.links, member)])) == [
        "-        ex:links ex:b , ex:c , ex:d ;\n",
        f"+        ex:links {left} ;\n",
    ]


def test_removing_the_a_shorthand_from_a_one_line_statement():
    assert edit(Patch(removes=[q(EX.b, RDF.type, EX.Thing)])) == [
        '-    ex:b a ex:Thing ; rdfs:label "B" .\n',
        '+    ex:b rdfs:label "B" .\n',
    ]


def test_removing_the_last_pair_of_a_one_line_statement():
    assert edit(Patch(removes=[q(EX.b, RDFS.label, Literal("B"))])) == [
        '-    ex:b a ex:Thing ; rdfs:label "B" .\n',
        "+    ex:b a ex:Thing .\n",
    ]


def test_removing_a_statements_last_triple_removes_it_and_keeps_the_comment_above():
    assert edit(Patch(removes=[q(EX.e, RDFS.label, Literal("E"))])) == ['-    ex:e rdfs:label "E" .\n']


def test_removing_every_triple_of_a_statement_removes_it():
    patch = Patch(removes=[q(EX.b, RDF.type, EX.Thing), q(EX.b, RDFS.label, Literal("B"))])
    assert edit(patch) == ['-    ex:b a ex:Thing ; rdfs:label "B" .\n']


def test_removing_a_multi_line_literal_removes_all_its_lines():
    assert edit(Patch(removes=[q(EX.c, EX.note, Literal("first line\nsecond line"))])) == [
        '-        ex:note """first line\n',
        '-second line""" ;\n',
    ]


def test_removing_a_blank_node_object_with_its_triples():
    part, inner = part_quads()
    assert edit(Patch(removes=[part, *inner])) == [
        "-    ex:c ex:part [ a ex:Part ;\n",
        "-                   ex:size 2 ] ;\n",
        "+    ex:c\n",
    ]


def test_removing_a_pair_inside_a_blank_node():
    part, _ = part_quads()
    assert edit(Patch(removes=[q(part[2], EX.size, Literal(2))])) == [
        "-    ex:c ex:part [ a ex:Part ;\n",
        "-                   ex:size 2 ] ;\n",
        "+    ex:c ex:part [ a ex:Part ] ;\n",
    ]


def test_removing_a_collection_with_its_cells():
    quads = text_quads(TEXT)
    listed = next(x for x in quads if x[1] == EX.list)
    cells = [x for x in quads if x[1] in (RDF.first, RDF.rest)]
    assert edit(Patch(removes=[listed, *cells])) == [
        '-second line""" ;\n',
        "-        ex:list ( ex:x ex:y ) .\n",
        '+second line""" .\n',
    ]


def test_a_comment_among_removed_last_pairs_survives():
    text = "@prefix ex: <https://example.org/t/> .\nex:g {\n    ex:a ex:p 1 ;\n        # why q\n        ex:q 2 .\n}\n"
    after = apply_text(text, Patch(removes=[q(EX.a, EX.q, Literal(2))]))
    assert after == "@prefix ex: <https://example.org/t/> .\nex:g {\n    ex:a ex:p 1 .\n        # why q\n}\n"


def test_removals_in_a_default_graph_statement():
    text = "@prefix ex: <https://example.org/t/> .\nex:a ex:p 1 ;\n    ex:q 2 .\n"
    quad = (EX.a, EX.q, Literal(2), DATASET_DEFAULT_GRAPH_ID)
    assert apply_text(text, Patch(removes=[quad])) == "@prefix ex: <https://example.org/t/> .\nex:a ex:p 1 .\n"


# Additions --------------------------------------------------------------------


def test_an_addition_joins_its_subjects_statement_as_one_line():
    assert edit(Patch(adds=[q(EX.a, EX.extra, EX.z)])) == ["+        ex:extra ex:z ;\n"]


def test_several_additions_to_one_subject_go_in_sorted_order():
    patch = Patch(adds=[q(EX.a, EX.extra, EX.z), q(EX.a, EX.alpha, Literal(True))])
    assert edit(patch) == ["+        ex:alpha true ;\n", "+        ex:extra ex:z ;\n"]


def test_an_addition_to_a_one_line_statement_stays_on_its_line():
    assert edit(Patch(adds=[q(EX.b, EX.extra, EX.z)])) == [
        '-    ex:b a ex:Thing ; rdfs:label "B" .\n',
        '+    ex:b a ex:Thing ; rdfs:label "B" ; ex:extra ex:z .\n',
    ]


def test_a_new_subject_becomes_a_statement_before_the_closing_brace():
    assert edit(Patch(adds=[q(EX.n, RDFS.label, Literal("N"))])) == ['+    ex:n rdfs:label "N" .\n']


def test_new_statements_are_sorted_with_one_pair_per_line():
    patch = Patch(
        adds=[
            q(EX.n, RDFS.label, Literal("N")),
            q(EX.n, RDF.type, EX.Thing),
            q(EX.m, COUNT, Literal(Decimal("1.5"))),
        ]
    )
    assert edit(patch) == [
        "+    ex:m ex:count 1.5 .\n",
        "+    ex:n a ex:Thing ;\n",
        '+        rdfs:label "N" .\n',
    ]


def test_new_graph_blocks_are_laid_out_canonically_at_the_end():
    patch = Patch(
        adds=[
            q(EX.n, RDFS.label, Literal("N"), EX.h2),
            q(EX.m, EX.v, Literal(2.5), EX.h1),
            q(EX.m, EX.w, Literal("x\ny", lang="en"), EX.h1),
        ]
    )
    after = apply_text(TEXT, patch)
    assert after == TEXT + (
        "\nex:h1 {\n"
        '    ex:m ex:v "2.5"^^<http://www.w3.org/2001/XMLSchema#double> ;\n'
        '        ex:w "x\\ny"@en .\n'
        "}\n"
        "\nex:h2 {\n"
        '    ex:n rdfs:label "N" .\n'
        "}\n"
    )


def test_terms_are_spelled_with_the_files_prefixes_and_bare_literals():
    patch = Patch(
        adds=[
            q(EX.n, EX.i, Literal(-4)),
            q(EX.n, EX.f, Literal(False)),
            q(EX.n, EX.o, URIRef("https://other.example/x")),
            q(EX.n, EX.s, Literal('say "hi"')),
        ]
    )
    assert edit(patch) == [
        "+    ex:n ex:f false ;\n",
        "+        ex:i -4 ;\n",
        "+        ex:o <https://other.example/x> ;\n",
        '+        ex:s "say \\"hi\\"" .\n',
    ]


def test_an_iri_under_the_base_folder_is_written_relative():
    text = "@prefix ex: <https://example.org/t/> .\nex:g {\n    ex:m ex:payload <m.bpmn> .\n}\n"
    base = "file:///models/app.trig"
    quad = q(EX.n, EX.payload, URIRef("file:///models/n.bpmn"))
    assert changed(text, apply_text(text, Patch(adds=[quad]), base=base)) == ["+    ex:n ex:payload <n.bpmn> .\n"]


def test_a_new_blank_node_is_written_inline_under_its_parent():
    node = BNode("new")
    patch = Patch(adds=[q(EX.e, EX.part, node), q(node, RDF.type, EX.Part), q(node, EX.size, Literal(5))])
    assert edit(patch) == [
        '-    ex:e rdfs:label "E" .\n',
        '+    ex:e rdfs:label "E" ; ex:part [ a ex:Part ; ex:size 5 ] .\n',
    ]


def test_an_addition_to_an_existing_blank_node_goes_inside_its_brackets():
    part, _ = part_quads()
    assert edit(Patch(adds=[q(part[2], EX.color, Literal("red"))])) == [
        "-                   ex:size 2 ] ;\n",
        '+                   ex:size 2 ; ex:color "red" ] ;\n',
    ]


def test_an_addition_after_a_last_statement_with_no_dot():
    text = "@prefix ex: <https://example.org/t/> .\nex:g { ex:a ex:p 1 }\n"
    after = apply_text(text, Patch(adds=[q(EX.b, EX.p, Literal(2))]))
    assert after == "@prefix ex: <https://example.org/t/> .\nex:g { ex:a ex:p 1 . \n    ex:b ex:p 2 .\n}\n"


def test_an_addition_to_the_default_graph_goes_at_the_end():
    text = "@prefix ex: <https://example.org/t/> .\nex:a ex:p 1 .\n"
    quad = (EX.b, EX.p, Literal(2), DATASET_DEFAULT_GRAPH_ID)
    assert apply_text(text, Patch(adds=[quad])) == text + "ex:b ex:p 2 .\n"


def test_remove_and_add_in_one_patch():
    patch = Patch(removes=[q(EX.a, COUNT, Literal(3))], adds=[q(EX.a, COUNT, Literal(4))])
    assert edit(patch) == [
        "-        ex:links ex:b , ex:c , ex:d ;\n",
        "-        ex:count 3 .\n",
        "+        ex:count 4 ;\n",
        "+        ex:links ex:b , ex:c , ex:d .\n",
    ]


def test_the_same_patch_gives_the_same_bytes_whatever_its_input_order():
    adds = [q(EX.a, EX.extra, EX.z), q(EX.n, RDFS.label, Literal("N")), q(EX.a, EX.alpha, Literal(1))]
    removes = [q(EX.a, EX.links, EX.c), q(EX.b, RDF.type, EX.Thing)]
    one = apply_text(TEXT, Patch(adds=adds, removes=removes))
    two = apply_text(TEXT, Patch(adds=reversed(adds), removes=reversed(removes)))
    assert one == two


# The patch value --------------------------------------------------------------


def test_patch_sorts_and_dedupes_and_inverts():
    a, b = q(EX.b, EX.p, Literal(1)), q(EX.a, EX.p, Literal(1))
    patch = Patch(adds=[a, b, a], removes=[q(EX.c, EX.p, EX.d)])
    assert patch.adds == (b, a)
    assert patch == Patch(adds=[b, a], removes=[q(EX.c, EX.p, EX.d)])
    assert patch.inverse() == Patch(adds=[q(EX.c, EX.p, EX.d)], removes=[b, a])
    assert patch.inverse().inverse() == patch
    assert not patch.is_empty and Patch().is_empty


def test_patch_is_frozen():
    with pytest.raises(AttributeError):
        Patch().adds = ()  # type: ignore[misc]


# Errors: the writer refuses, naming subject, predicate and reason -------------


def test_removing_a_quad_not_in_the_model_is_refused():
    with pytest.raises(PatchError, match="is not in the model") as info:
        apply_text(TEXT, Patch(removes=[q(EX.a, COUNT, Literal(99))]))
    assert (info.value.subject, info.value.predicate) == (str(EX.a), str(COUNT))


def test_adding_a_quad_already_in_the_model_is_refused():
    with pytest.raises(PatchError, match="is already in the model") as info:
        apply_text(TEXT, Patch(adds=[q(EX.a, COUNT, Literal(3))]))
    assert (info.value.subject, info.value.predicate) == (str(EX.a), str(COUNT))


def test_a_patch_that_adds_and_removes_one_quad_is_refused():
    quad = q(EX.a, COUNT, Literal(3))
    with pytest.raises(PatchError, match="both adds and removes"):
        Patch(adds=[quad], removes=[quad])


def test_removing_a_blank_node_object_without_its_triples_is_refused():
    part, _ = part_quads()
    with pytest.raises(PatchError, match="holding 2 more triples") as info:
        apply_text(TEXT, Patch(removes=[part]))
    assert (info.value.subject, info.value.predicate) == (str(EX.c), str(EX.part))


def test_removing_one_cell_of_a_collection_is_refused():
    cell = next(x for x in text_quads(TEXT) if x[1] == RDF.first)
    with pytest.raises(PatchError, match="inside a collection"):
        apply_text(TEXT, Patch(removes=[cell]))


def test_adding_to_a_collection_cell_is_refused():
    cell = next(x for x in text_quads(TEXT) if x[1] == RDF.first)
    with pytest.raises(PatchError, match="collection cell"):
        apply_text(TEXT, Patch(adds=[q(cell[0], EX.p, Literal(1))]))


def test_a_new_blank_node_with_no_parent_is_refused():
    with pytest.raises(PatchError, match="no added quad has it as its object"):
        apply_text(TEXT, Patch(adds=[q(BNode("orphan"), RDF.type, EX.Part)]))


def test_referring_again_to_an_unlabelled_blank_node_is_refused():
    part, _ = part_quads()
    with pytest.raises(PatchError, match="unlabelled blank node") as info:
        apply_text(TEXT, Patch(adds=[q(EX.e, EX.part, part[2])]))
    assert info.value.subject == str(EX.e)


def test_an_invalid_iri_is_refused():
    with pytest.raises(PatchError, match="not a valid IRI"):
        apply_text(TEXT, Patch(adds=[q(EX.a, EX.p, URIRef("https://example.org/a b"))]))


def test_text_the_writer_cannot_read_is_refused_naming_the_line():
    with pytest.raises(PatchError, match="line 2"):
        apply_text(
            "@prefix ex: <https://example.org/t/> .\nex:g { ex:a ex:p ) }\n", Patch(removes=[q(EX.a, EX.p, EX.b)])
        )
    with pytest.raises(PatchError, match="undeclared prefix"):
        text_quads("nope:a nope:b nope:c .\n")


def test_an_edit_that_would_not_reparse_to_the_patched_model_is_refused(monkeypatch: pytest.MonkeyPatch):
    # The writer's safety net: a wrong edit raises instead of returning text.
    monkeypatch.setattr(seams_edit.trig._Edits, "result", lambda self: self.text)
    with pytest.raises(PatchError, match="does not mean the patched model in graph <https://example.org/t/g>"):
        apply_text(TEXT, Patch(removes=[q(EX.a, COUNT, Literal(3))]))


def test_an_edit_that_would_not_parse_is_refused(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(seams_edit.trig._Edits, "result", lambda self: self.text + "ex:g {")
    with pytest.raises(PatchError, match="does not parse"):
        apply_text(TEXT, Patch(removes=[q(EX.a, COUNT, Literal(3))]))

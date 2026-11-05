"""Structural edit proposals (backlog T5, M021/S02): viewer.structural.

Each test copies the chat app, and the compose files it generates at the
repository root, into tmp_path with the same layout (as test_viewer_writeback
does), then edits the committed chat page as a whole. Edited blocks are either
spliced from what the generator emits for a model with the binding, or written
to differ from it on purpose; the facts asserted are read from the copied model.
"""

import difflib
import shutil
import sys
from pathlib import Path

import pytest
import seams
from rdflib import RDF, RDFS, SH, Literal, URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_edit import Patch  # noqa: E402
from tests.workspace_copy import copy_workspace  # noqa: E402
from viewer import generation, structural, writeback  # noqa: E402

CHAT = ROOT / "examples" / "chat-app"
PAGE = "generated/templates/chat_page.html"
IFML = "https://w3id.org/seams/ifml#"
SEAM = "https://w3id.org/seams/seam#"
HAS_PARAMETER = URIRef(IFML + "hasParameter")
BOUND_TO = URIRef(IFML + "boundTo")
PARAMETER = URIRef(IFML + "Parameter")
IN_MODEL = URIRef(SEAM + "inModel")
WRITES = URIRef(SEAM + "writes")


@pytest.fixture(autouse=True)
def clear_cache():
    generation._clear_cache()
    yield
    generation._clear_cache()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """The chat app at tmp_path/examples/chat-app, its compose files at tmp_path."""
    copy = tmp_path / "examples" / "chat-app"
    shutil.copytree(CHAT, copy, ignore=shutil.ignore_patterns("__pycache__"))
    copy_workspace(tmp_path)
    for compose in sorted(ROOT.glob("compose.*.yaml*")):
        shutil.copyfile(compose, tmp_path / compose.name)
    return copy


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _model(project: Path) -> seams.Model:
    return seams.load(project / "chat-app.trig")


def _page(project: Path) -> list[str]:
    return (project / PAGE).read_text(encoding="utf-8").splitlines(keepends=True)


def _form(project: Path) -> tuple[URIRef, URIRef, URIRef]:
    """The chat page's one form that writes a shape, its graph and the shape."""
    ds = _model(project).ds
    ((form, shape),) = [(s, o) for s, o in ds.subject_objects(WRITES) if (s, RDF.type, URIRef(IFML + "Form")) in ds]
    ((graph,),) = {(g,) for _s, _p, _o, g in ds.quads((form, RDF.type, None, None))}
    return form, graph, shape


def _propose(project: Path, edited: str) -> structural.Structural:
    return structural.propose(
        generation.get_index(project), _model(project).ds, project, project / "chat-app.trig", PAGE, edited
    )


def _spliced(project: Path, patch: Patch) -> str:
    """The committed page with the one form block the generator writes for ``patch``
    spliced in: every changed line but the model-hash lines."""
    model = _model(project)
    regenerated = writeback.regenerate(project, project / "chat-app.trig", patch, PAGE, "output")
    old = _page(project)
    new = regenerated.texts[PAGE].splitlines(keepends=True)
    new_hex = regenerated.new_hash.removeprefix("sha256:")
    old_hex = model.hash.removeprefix("sha256:")
    ops = [
        op
        for op in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
        if op[0] != "equal" and not all(new_hex in line for line in new[op[3] : op[4]])
    ]
    assert len(ops) == 1, ops
    _tag, i1, i2, j1, j2 = ops[0]
    return "".join(old[:i1] + [line.replace(new_hex, old_hex) for line in new[j1:j2]] + old[i2:])


def _block(project: Path, needle: str) -> tuple[int, int]:
    """0-based [start, end) of the label and control lines of the input named ``needle``."""
    lines = _page(project)
    start = next(n for n, t in enumerate(lines) if '<label for="' in t and f">{needle}</label>" in t)
    end = next(n for n in range(start, len(lines)) if lines[n].rstrip().endswith(">") and n > start) + 1
    return start, end


def test_removing_the_message_input_block_drops_the_parameter(project: Path):
    form, graph, _shape = _form(project)
    ds = _model(project).ds
    ((param, path),) = [(p, ds.value(p, BOUND_TO)) for p in ds.objects(form, HAS_PARAMETER)]
    assert path is not None
    name = str(path).rsplit("/", 1)[-1]
    # what the generator writes once the parameter is gone: the input block goes
    # and the unbound-fields comment below it names the field
    removes = [*ds.quads((param, None, None, None)), (form, HAS_PARAMETER, param, graph)]
    expected = _spliced(project, Patch(removes=removes))

    result = _propose(project, expected)

    assert (result.kind, result.field, result.parameter, result.form) == ("remove", name, str(param), str(form))
    assert result.patch.adds == ()
    assert {q[0] for q in result.patch.removes} == {param, form}
    assert (form, HAS_PARAMETER, param, graph) in result.patch.removes
    assert set(ds.quads((param, None, None, None))) <= set(result.patch.removes)
    assert result.files == ("chat-app.trig",)
    assert not any(e.output == PAGE for e in result.effects)


def test_removing_the_block_without_its_comment_line_is_refused(project: Path):
    lines = _page(project)
    start, end = _block(project, "content")
    with pytest.raises(writeback.Refusal) as err:
        _propose(project, "".join(lines[:start] + lines[end:]))
    assert err.value.predicate == str(HAS_PARAMETER)
    assert f"regenerating gives {PAGE} line {start + 1}" in err.value.detail


def test_adding_an_input_for_a_shape_path_binds_it(project: Path):
    form, graph, shape = _form(project)
    ds = _model(project).ds
    bound = {ds.value(p, BOUND_TO) for p in ds.objects(form, HAS_PARAMETER)}
    paths = sorted({ds.value(n, SH.path) for n in ds.objects(shape, SH.property) if ds.value(n, SH.datatype)} - bound)
    path = next(p for p in paths if str(p).endswith("/role"))
    # the generator's own output for a model where the form binds the path
    witness = URIRef(str(form) + "_witness")
    edited = _spliced(
        project,
        Patch(
            adds=[
                (form, HAS_PARAMETER, witness, graph),
                (witness, RDF.type, PARAMETER, graph),
                (witness, RDFS.label, Literal("witness"), graph),
                (witness, BOUND_TO, path, graph),
            ]
        ),
    )

    result = _propose(project, edited)

    param = URIRef(str(form).rsplit("/", 1)[0] + "/role_input")
    assert (result.kind, result.field, result.parameter, result.path) == ("add", "role", str(param), str(path))
    (in_model,) = ds.objects(form, IN_MODEL)
    assert set(result.patch.adds) == {
        (form, HAS_PARAMETER, param, graph),
        (param, RDF.type, PARAMETER, graph),
        (param, RDFS.label, Literal("role input"), graph),
        (param, BOUND_TO, path, graph),
        (param, IN_MODEL, in_model, graph),
    }
    assert result.patch.removes == ()


def test_adding_an_input_for_a_new_path_adds_a_shape_property(project: Path):
    from rdflib import XSD  # imported here: pytest probes module-level namespaces and XSD warns

    form, _graph, shape = _form(project)
    lines = _page(project)
    start, end = _block(project, "content")
    # the generator ids a control <form prefix>_<name>; read the prefix off the content control
    (opening,) = [t for t in lines[start:end] if 'id="' in t]
    form_prefix = opening.split('id="')[1].split('"')[0].removesuffix("_content")
    block = [
        f'    <label for="{form_prefix}_subject">subject</label>\n',
        f'    <input id="{form_prefix}_subject"\n',
        '           name="subject"\n',
        '           type="text"\n',
        '           maxlength="80"\n',
        "           required>\n",
    ]

    result = _propose(project, "".join(lines[:end] + block + lines[end:]))

    ds = _model(project).ds
    ((shape_graph,),) = {(g,) for _s, _p, _o, g in ds.quads((shape, RDF.type, SH.NodeShape, None))}
    path = URIRef(str(shape).rsplit("/", 1)[0] + "/subject")
    assert (result.kind, result.path) == ("add", str(path))
    (node,) = [o for s, p, o, g in result.patch.adds if (s, p, g) == (shape, SH.property, shape_graph)]
    on_node = {(p, o) for s, p, o, g in result.patch.adds if s == node and g == shape_graph}
    assert on_node == {
        (SH.path, path),
        (SH.datatype, XSD.string),
        (SH.maxLength, Literal(80)),
        (SH.minCount, Literal(1)),
        (SH.name, Literal("subject")),
    }
    assert (path, RDF.type, RDF.Property, shape_graph) in result.patch.adds
    # the Details of the same shape on the page shows the new field: an effect, not a refusal
    assert any(e.output == PAGE and 'class="subject"' in e.after for e in result.effects)


def test_two_separate_changed_blocks_are_refused(project: Path):
    lines = _page(project)
    start, end = _block(project, "content")
    title = next(n for n, t in enumerate(lines) if "<title>" in t)
    edited = list(lines)
    edited[title] = edited[title].replace("</title>", " now</title>")
    with pytest.raises(writeback.Refusal) as err:
        _propose(project, "".join(edited[:start] + edited[end:]))
    assert err.value.predicate == "lines"
    assert "changes 2" in err.value.detail


def test_an_input_that_regenerates_differently_is_refused_at_the_first_difference(project: Path):
    lines = _page(project)
    _start, end = _block(project, "content")
    # role binds an existing path, but the generator writes ids, not this one
    block = ['    <label for="role">role</label>\n', '    <input id="role" name="role" type="text">\n']
    with pytest.raises(writeback.Refusal) as err:
        _propose(project, "".join(lines[:end] + block + lines[end:]))
    assert err.value.predicate == str(HAS_PARAMETER)
    assert f"regenerating gives {PAGE} line {end + 1}" in err.value.detail


def test_a_minted_parameter_iri_that_exists_is_refused(project: Path):
    form, _graph, _shape = _form(project)
    ds = _model(project).ds
    (existing,) = ds.objects(form, HAS_PARAMETER)
    name = str(existing).rsplit("/", 1)[-1].removesuffix("_input")
    lines = _page(project)
    _start, end = _block(project, "content")
    block = [f'    <input name="{name}" type="text">\n']
    with pytest.raises(writeback.Refusal) as err:
        _propose(project, "".join(lines[:end] + block + lines[end:]))
    assert (err.value.subject, err.value.predicate) == (str(existing), str(RDF.type))
    assert "already" in err.value.detail


def test_an_input_outside_any_form_is_refused(project: Path):
    lines = _page(project)
    title = next(n for n, t in enumerate(lines) if "<title>" in t)
    edited = lines[: title + 1] + ['  <input name="subject" type="text">\n'] + lines[title + 1 :]
    with pytest.raises(writeback.Refusal) as err:
        _propose(project, "".join(edited))
    assert err.value.predicate == IFML + "Form"
    assert "inside no ifml:Form" in err.value.detail


def test_an_edit_that_adds_no_control_is_refused(project: Path):
    lines = _page(project)
    start, _end = _block(project, "content")
    edited = lines[:start] + ["    <p>hint</p>\n"] + lines[start:]
    with pytest.raises(writeback.Refusal) as err:
        _propose(project, "".join(edited))
    assert err.value.predicate == "controls"


def test_proposals_never_write_the_real_files(project: Path, tmp_path: Path):
    before = _snapshot(tmp_path)
    lines = _page(project)
    start, end = _block(project, "content")
    (opening,) = [t for t in lines[start:end] if 'id="' in t]
    form_prefix = opening.split('id="')[1].split('"')[0].removesuffix("_content")
    accepted = [
        f'    <label for="{form_prefix}_subject">subject</label>\n',
        f'    <input id="{form_prefix}_subject"\n',
        '           name="subject"\n',
        '           type="text">\n',
    ]
    assert _propose(project, "".join(lines[:end] + accepted + lines[end:])).kind == "add"
    for edited in (
        "".join(
            lines[:end] + ['    <input id="x" name="subject" type="text">\n'] + lines[end:]
        ),  # regenerates differently
        "".join(lines[:start] + lines[end:]),  # the comment line is stale
    ):
        with pytest.raises(writeback.Refusal):
            _propose(project, edited)
    assert _snapshot(tmp_path) == before

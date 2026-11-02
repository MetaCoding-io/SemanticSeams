"""The health panel's lifted-IRI check (ADR-0002 rule 4, M019/S04).

Every IRI of a BPMN or DMN model of the form ``modelIRI#fragment`` must name an id
in the model's payload XML. Every committed example passes; a tmp copy of the
expense tutorial's chapter 9 with one lifted element's id changed in the XML
reports that IRI by name, in the shell's health panel only (MEM009).

The element is found by querying the loaded model, not by naming domain IRIs.
"""

import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
import seams
from fastapi.testclient import TestClient
from rdflib import URIRef

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viewer import app as viewer_app  # noqa: E402
from viewer import validation  # noqa: E402

CHAPTER = ROOT / "examples" / "expenses" / "chapter-09"
TRIGS = sorted(p for p in (ROOT / "examples").rglob("*.trig") if "generated" not in p.parts)
# examples/checkout.trig is the authoring guide's TriG sample: it names payload
# files that were never committed, so it is checked on its own below.
SAMPLE = ROOT / "examples" / "checkout.trig"
EXAMPLE_MODELS = [p for p in TRIGS if p != SAMPLE]


@pytest.fixture(autouse=True)
def clear_cache():
    """id()-keyed caches: clear before each test so a recycled id cannot serve a
    stale result (MEM010)."""
    validation._clear_cache()
    yield
    validation._clear_cache()


@pytest.fixture
def restore_viewer():
    original = viewer_app.MODEL_PATH
    yield
    viewer_app.configure(original)


def _lifted(model: seams.Model) -> tuple[str, Path, str]:
    """The first BPMN/DMN model with a payload and a lifted IRI, as
    (lifted IRI, payload path, fragment)."""
    for notation in validation.LIFTED_NOTATIONS:
        for m in sorted(model.ds.subjects(validation.SEAM.notation, notation), key=str):
            if model.ds.value(m, validation.SEAM.renderPayload) is None:
                continue
            prefix = f"{m}#"
            iris = sorted(
                str(t)
                for s, _p, o, _c in model.ds.quads((None, None, None, None))
                for t in (s, o)
                if isinstance(t, URIRef) and str(t).startswith(prefix)
            )
            if iris:
                return iris[0], model.payload_path(m), iris[0][len(prefix) :]
    raise AssertionError("no lifted IRI in the chapter")


def _copy(dest: Path) -> Path:
    shutil.copytree(CHAPTER, dest, ignore=shutil.ignore_patterns("generated"))
    return dest


def _health(path: Path) -> list[dict]:
    model = seams.load(path)
    return validation.get_lifted_iri_health(model.ds, model.base_dir)


@pytest.mark.parametrize("trig", EXAMPLE_MODELS, ids=lambda p: str(p.relative_to(ROOT)))
def test_committed_examples_have_no_dangling_lifted_iris(trig):
    assert _health(trig) == []


def test_sample_without_payload_files_reports_each_payload():
    """The check reads the payload files; a model naming absent ones gets one
    finding per BPMN/DMN model and never an exception."""
    model = seams.load(SAMPLE)
    models = sorted(
        str(m)
        for n in validation.LIFTED_NOTATIONS
        for m in model.ds.subjects(validation.SEAM.notation, n)
        if model.ds.value(m, validation.SEAM.renderPayload) is not None
    )
    assert models
    findings = validation.get_lifted_iri_health(model.ds, model.base_dir)
    assert [(f["iri"], f["model"]) for f in findings] == [(None, m) for m in models]


def test_examples_check_lifted_iris():
    """The check is not vacuous: some example has lifted IRIs to compare."""
    assert _lifted(seams.load(CHAPTER))


def test_id_removed_from_xml_is_reported_by_name(tmp_path):
    copy = _copy(tmp_path / "chapter")
    iri, payload, fragment = _lifted(seams.load(copy))
    xml = payload.read_text()
    assert f'id="{fragment}"' in xml
    payload.write_text(xml.replace(f'id="{fragment}"', f'id="{fragment}_gone"', 1))

    findings = _health(copy)
    assert [f["iri"] for f in findings] == [iri]
    assert fragment in findings[0]["message"]
    assert findings[0]["model"] == iri.split("#", 1)[0]


def test_malformed_payload_is_one_finding_not_an_error(tmp_path):
    copy = _copy(tmp_path / "chapter")
    iri, payload, _fragment = _lifted(seams.load(copy))
    payload.write_text("<definitions><unclosed></definitions>")

    findings = _health(copy)
    assert [(f["iri"], f["model"]) for f in findings] == [(None, iri.split("#", 1)[0])]
    assert "cannot be read" in findings[0]["message"]


def test_missing_payload_is_one_finding_not_an_error(tmp_path):
    copy = _copy(tmp_path / "chapter")
    model = seams.load(copy)
    iri, payload, _fragment = _lifted(model)
    payload.unlink()

    findings = validation.get_lifted_iri_health(model.ds, model.base_dir)
    assert [(f["iri"], f["model"]) for f in findings] == [(None, iri.split("#", 1)[0])]


def test_result_is_cached_per_dataset_and_cleared_with_conformance():
    model = seams.load(CHAPTER)
    first = validation.get_lifted_iri_health(model.ds, model.base_dir)
    assert validation.get_lifted_iri_health(model.ds, model.base_dir) is first
    validation._clear_cache()
    assert validation.get_lifted_iri_health(model.ds, model.base_dir) is not first


def test_full_page_shows_lifted_iri_section_fragment_does_not(tmp_path, restore_viewer):
    copy = _copy(tmp_path / "chapter")
    iri, payload, fragment = _lifted(seams.load(copy))
    payload.write_text(payload.read_text().replace(f'id="{fragment}"', f'id="{fragment}_gone"', 1))
    viewer_app.configure(copy)
    client = TestClient(viewer_app.app)
    url = f"/view/{quote(viewer_app.root_iri(), safe='')}"

    page = client.get(url, headers={"Accept": "text/html"})
    assert page.status_code == 200
    assert 'class="health-lifted"' in page.text
    assert "Lifted IRIs missing from the XML" in page.text
    assert iri in page.text

    fragment_view = client.get(url, headers={"Accept": "text/html", "hx-request": "true"})
    assert fragment_view.status_code == 200
    assert 'class="health-lifted"' not in fragment_view.text
    assert "Lifted IRIs missing from the XML" not in fragment_view.text

    view = client.get(url, headers={"Accept": "application/json"}).json()
    assert [f["iri"] for f in view["modelConformance"]["liftedIris"]] == [iri]


def test_clean_model_page_has_no_lifted_iri_section(restore_viewer):
    viewer_app.configure(CHAPTER)
    page = TestClient(viewer_app.app).get(
        f"/view/{quote(viewer_app.root_iri(), safe='')}", headers={"Accept": "text/html"}
    )
    assert page.status_code == 200
    assert 'class="health-lifted"' not in page.text

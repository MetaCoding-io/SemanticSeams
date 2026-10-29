"""Generators for human tasks (M009/S04/T03, ADR-0009, D027).

For the approval fixture, the FastAPI generator emits a completion handler for
the operation the form a user task seam:completedOn submits to: it depends on
runtime.task_policy, takes the correlation key from the path and awaits
runtime.complete_task. The htmx generator emits that form's partial for the
host's task inbox, plus the partial its completion route renders. A key that
is not a path variable, or a completion form with no task process, raises
GeneratorError naming the subject and predicate.
"""

import ast
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import jinja2
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seams_gen import GeneratorError, extract_page, extract_routes  # noqa: E402
from seams_gen.__main__ import main  # noqa: E402
from seams_gen.fastapi import render_routes  # noqa: E402
from seams_gen.htmx import render_fragments, render_task_forms  # noqa: E402
from seams_runtime import ModelGraph  # noqa: E402
from seams_runtime.host import build_app  # noqa: E402
from seams_runtime.model import COMM, PROC, SEAM  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "human_task"
TRIG = FIXTURE / "approval.trig"
EX = "https://example.org/expenses/"
TASK = EX + "approval_bpmn#approve_expense"
TASK_CURIE = ":approval_bpmn#approve_expense"


def _routes_text(trig=TRIG) -> str:
    routes = extract_routes(ModelGraph.load(trig))
    (module,) = routes.modules
    return render_routes(routes)[module.file_name]


def _mutated(tmp_path, old: str, new: str) -> Path:
    """A copy of the fixture with one exact text substitution (and its BPMN)."""
    text = TRIG.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    (tmp_path / "approval.bpmn").write_bytes((FIXTURE / "approval.bpmn").read_bytes())
    path = tmp_path / "approval.trig"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return path


def _handler(text: str, name: str) -> ast.AsyncFunctionDef:
    (fn,) = [n for n in ast.parse(text).body if isinstance(n, ast.AsyncFunctionDef) and n.name == name]
    return fn


# ── the completion route ────────────────────────────────────────────────────


def test_completion_handler_completes_the_task():
    text = _routes_text()
    fn = _handler(text, "approve_expense")
    source = ast.get_source_segment(text, fn)
    assert '@router.post("/expenses/{expense}/approval", response_class=HTMLResponse)\nasync def approve_expense(' in text
    assert f'identity: Identity = Depends(runtime.task_policy("{TASK_CURIE}"))' in source
    assert [a.arg for a in fn.args.args] == ["expense", "request", "identity"]
    assert re.search(r'await runtime\.complete_task\(\s*"' + re.escape(TASK_CURIE) + r'",\s*form,\s*'
                     r'correlation_key=expense,\s*identity=identity,\s*\)', source), source
    assert "runtime.validate(" not in source  # complete_task validates the payload
    assert "start_process" not in source and "runtime.write(" not in source
    assert 'runtime.query(":ExpenseShape", expense=expense)' in source
    assert '"expense_details.html"' in source


def test_task_curie_expands_back_to_the_task_iri():
    # Facts.curie would print :approve_expense, which names another, ungoverned IRI
    model = ModelGraph.load(TRIG)
    assert str(model.curie(TASK_CURIE)) == TASK
    assert (model.curie(TASK_CURIE), SEAM.governedBy, None) in model.ds


def test_identity_is_imported_only_when_needed():
    assert "from seams_runtime import Identity, Runtime" in _routes_text()
    chat = _routes_text(ROOT / "examples" / "chat-app" / "chat-app.trig")
    assert "from seams_runtime import Runtime\n" in chat and "Identity" not in chat


def test_start_payload_does_not_shadow_the_correlation_key():
    source = ast.get_source_segment(_routes_text(), _handler(_routes_text(), "submit_expense"))
    assert 'expense_payload = runtime.validate(":ExpenseShape", form)' in source
    assert "correlation_key=expense," in source


def test_route_module_compiles_and_serves(tmp_path, monkeypatch):
    assert main(["fastapi", str(TRIG), "--out", str(tmp_path / "gen")]) == 0
    assert main(["htmx", str(TRIG), "--out", str(tmp_path / "templates")]) == 0
    module = tmp_path / "gen" / "expense_api.py"
    compile(module.read_text(encoding="utf-8"), str(module), "exec")
    monkeypatch.setenv("SEAMS_MODEL", str(TRIG))
    monkeypatch.setenv("SEAMS_TEMPLATES", str(tmp_path / "templates"))
    monkeypatch.setenv("SEAMS_DB", str(tmp_path / "seams.sqlite"))
    monkeypatch.delenv("SEAMS_DEV_USER", raising=False)
    app = build_app(module)
    with TestClient(app) as client:
        # the route is mounted (not 404) and its task_policy dependency
        # answers before the handler runs
        assert client.post("/expenses/e1/approval", data={"decision": "approved"}).status_code == 401
        denied = client.post("/expenses/e1/approval", data={"decision": "approved"},
                             headers={"X-Forwarded-User": "employee"})
        assert denied.status_code == 403


def test_key_that_is_not_a_path_variable_raises(tmp_path):
    trig = _mutated(tmp_path, 'hydra:template "/expenses/{expense}/approval" ;\n'
                    '                    hydra:mapping [ a hydra:IriTemplateMapping ;\n'
                    '                                    hydra:variable "expense" ;',
                    'hydra:template "/expenses/{claim}/approval" ;\n'
                    '                    hydra:mapping [ a hydra:IriTemplateMapping ;\n'
                    '                                    hydra:variable "claim" ;')
    with pytest.raises(GeneratorError) as err:
        extract_routes(ModelGraph.load(trig))
    assert err.value.subject == str(ModelGraph.load(trig).curie(":approval_process"))
    assert err.value.predicate == str(PROC.correlationKey)
    assert "'expense' is not a path variable" in str(err.value)
    with pytest.raises(GeneratorError) as err:
        extract_page(ModelGraph.load(trig))
    assert err.value.predicate == str(PROC.correlationKey)


def test_task_outside_any_process_model_raises(tmp_path):
    trig = _mutated(tmp_path, ":approval_process seam:detailedBy :approval_bpmn ;",
                    ":approval_process seam:detailedBy :expense_data ;")
    with pytest.raises(GeneratorError) as err:
        extract_routes(ModelGraph.load(trig))
    assert err.value.subject == str(ModelGraph.load(trig).curie(TASK_CURIE))
    assert err.value.predicate == str(SEAM.detailedBy)


def test_completion_without_a_request_body_raises(tmp_path):
    text = TRIG.read_text(encoding="utf-8")
    start = text.index(":approve_expense_op a hydra:Operation")
    old = 'comm:requestMediaType "application/x-www-form-urlencoded" ;'
    at = text.index(old, start)
    trig = tmp_path / "approval.trig"
    (tmp_path / "approval.bpmn").write_bytes((FIXTURE / "approval.bpmn").read_bytes())
    trig.write_text(text[:at] + text[at + len(old):], encoding="utf-8")
    with pytest.raises(GeneratorError) as err:
        extract_routes(ModelGraph.load(trig))
    assert err.value.subject == EX + "approve_expense_op"
    assert err.value.predicate == str(COMM.requestMediaType) and "request body" in str(err.value)


# ── the task form partial ───────────────────────────────────────────────────


class _Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = []

    def handle_starttag(self, tag, attrs):
        self.found.append((tag, dict(attrs)))


def _task_form() -> str:
    return render_task_forms(extract_page(ModelGraph.load(TRIG)))["approve_form.html"]


def _rendered(row) -> list:
    env = jinja2.Environment(autoescape=True)  # as seams_runtime.fragments does
    parser = _Elements()
    parser.feed(env.from_string(_task_form()).render(task=row))
    return parser.found


ROW = {"correlation_key": "e1", "label": "Approve Expense",
       "entity": {"id": "x1", "description": "Train", "amount": "42.50", "status": "submitted"}}


def test_htmx_cli_writes_the_task_form_and_completion_partials(tmp_path):
    assert main(["htmx", str(TRIG), "--out", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "approve_form.html", "expense_details.html", "expense_list.html", "expense_list_item.html",
        "submit_page.html"]


def test_task_form_posts_to_the_completion_path_with_the_key():
    elements = _rendered(ROW)
    (form,) = [a for t, a in elements if t == "form"]
    assert form["hx-post"] == "/expenses/e1/approval"
    assert form["hx-target"] == "closest article" and form["hx-swap"] == "outerHTML"
    (article,) = [a for t, a in elements if t == "article"]
    assert article["data-expense"] == "e1" and article["data-task"] == TASK_CURIE


def test_task_form_has_a_field_per_shape_property_and_a_select_for_sh_in():
    elements = _rendered(ROW)
    named = {a["name"]: (t, a) for t, a in elements if "name" in a}
    assert sorted(named) == ["comment", "decision"]  # :ApprovalShape's datatype properties
    tag, decision = named["decision"]
    assert tag == "select" and "required" in decision
    assert [a["value"] for t, a in elements if t == "option"] == ["approved", "rejected"]  # sh:in order
    tag, comment = named["comment"]
    assert tag == "input" and comment["maxlength"] == "500" and "required" not in comment


def test_task_form_shows_the_task_label_and_read_entity():
    text = jinja2.Environment(autoescape=True).from_string(_task_form()).render(task=ROW)
    assert "<h2>Approve Expense</h2>" in text
    assert '<dd class="description">Train</dd>' in text and '<dd class="amount">42.50</dd>' in text
    without = jinja2.Environment(autoescape=True).from_string(_task_form()).render(
        task={**ROW, "entity": None})
    assert "<dl" not in without


def test_task_form_escapes_the_key():
    text = jinja2.Environment(autoescape=True).from_string(_task_form()).render(
        task={**ROW, "correlation_key": '"><script>'})
    assert "<script>" not in text


def test_completion_partial_is_generated():
    fragments = render_fragments(extract_page(ModelGraph.load(TRIG)))
    assert "expense_details.html" in fragments
    assert "rendered by :approve_expense_op and :expense_details_op" in fragments["expense_details.html"]


def test_generation_is_deterministic():
    page = extract_page(ModelGraph.load(TRIG))
    assert page == extract_page(ModelGraph.load(TRIG))
    assert render_task_forms(page) == render_task_forms(extract_page(ModelGraph.load(TRIG)))
    assert _routes_text() == _routes_text()


def test_a_form_completing_two_tasks_raises(tmp_path):
    trig = _mutated(tmp_path, "        seam:invokes :submit_expense_op ;",
                    "        seam:completedOn :approve_form ;\n        seam:invokes :submit_expense_op ;")
    text = trig.read_text(encoding="utf-8").replace(
        "<https://example.org/expenses/approval_bpmn#persist_expense> a proc:ServiceTask",
        "<https://example.org/expenses/approval_bpmn#persist_expense> a proc:UserTask")
    trig.write_text(text, encoding="utf-8")
    with pytest.raises(GeneratorError) as err:
        extract_page(ModelGraph.load(trig))
    assert err.value.predicate == str(SEAM.completedOn)

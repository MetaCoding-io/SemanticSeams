"""The acceptance generator (backlog C2, M022/S03): tests a hand-written handler against the model.

The generated file for expense chapter 9 is compared with its golden and run
against the chapter's own handlers/notify.py. Wrong bodies, written into a copy
of the chapter, make each check fail with a message naming the model fact. The
chat app with a comm:PythonHandler on :send_message_op gives a task that fires a
transition (:persist_user_msg fires :t_send).
"""

import json
import shutil
from pathlib import Path

import pytest
from seams import ModelGraph, model_hash

from seams_gen import GeneratorError
from seams_gen.acceptance import extract_acceptance, generate_acceptance, render_acceptance, trace_acceptance
from seams_gen.builtin import acceptance
from seams_gen.sources import output_sources
from seams_gen.testing import assert_deterministic, assert_matches_golden, check_output
from seams_runtime.verify import (
    Handler,
    decision_route,
    handler_result,
    handler_types,
    transition_guard,
)

ROOT = Path(__file__).resolve().parents[1]
CHAPTER = ROOT / "examples" / "expenses" / "chapter-09"
TRIG = CHAPTER / "expenses.trig"
CHAT_DIR = ROOT / "examples" / "chat-app"
GOLDEN = ROOT / "tests" / "golden" / "acceptance" / "test_notify.py"
EXP = "https://example.org/expenses/"
APPROVAL = "https://example.org/expenses/approval_bpmn#"
CHAT = "https://example.org/chat/"
COMM_HANDLER = "https://w3id.org/seams/comm#handler"
NOTIFY_TASK = APPROVAL + "notify_manager"
OP = EXP + "notify_manager_op"
NOTIFY = Handler(
    handler="notify.notify_manager",
    implementation=EXP + "notify_manager_impl",
    accepts=((("amount", True), ("date", True), ("description", True), ("id", False), ("status", False)),),
    returns=((("message", True), ("recipient", True)),),
)

LLM_IMPL = ':completion_impl a comm:LLMCompletion ; rdfs:label "LLM completion" .'
CHAT_NOTIFY = (
    "    :send_message_op seam:implementedBy :py_impl .\n"
    '    :py_impl a comm:PythonHandler ; rdfs:label "python handler" ; comm:handler "notify.notify_manager" .'
)


def chapter(tmp_path: Path, body: str | None = None) -> ModelGraph:
    """A copy of chapter 9's model files, its handlers/notify.py replaced by ``body`` when given."""
    app = tmp_path / "app"
    app.mkdir()
    for path in CHAPTER.iterdir():
        if path.suffix in (".trig", ".bpmn", ".dmn"):
            shutil.copy(path, app / path.name)
    shutil.copytree(CHAPTER / "handlers", app / "handlers", ignore=shutil.ignore_patterns("__pycache__"))
    if body is not None:
        (app / "handlers" / "notify.py").write_text(body, encoding="utf-8")
    return ModelGraph(app / "expenses.trig")


def chat_model(tmp_path: Path, *declarations: str) -> Path:
    """The chat app's model files in ``tmp_path/chat`` with ``declarations`` added to the seams graph."""
    app = tmp_path / "chat"
    app.mkdir()
    for name in ("chat-app.trig", "chat_process.bpmn", "routing.dmn"):
        shutil.copy(CHAT_DIR / name, app / name)
    trig = app / "chat-app.trig"
    text = trig.read_text(encoding="utf-8")
    assert text.count(LLM_IMPL) == 1
    trig.write_text(text.replace(LLM_IMPL, "\n".join([LLM_IMPL, *declarations])), encoding="utf-8")
    return trig


# ── the generated file ───────────────────────────────────────────────────────


def test_chapter_9_matches_the_golden():
    files = generate_acceptance(TRIG)
    assert list(files) == ["test_notify.py"]
    check_output("test_notify.py", files["test_notify.py"])
    assert_matches_golden(files["test_notify.py"], GOLDEN, model_hash(TRIG))


def test_generation_is_deterministic():
    assert_deterministic(acceptance, TRIG)


def test_a_model_without_python_handlers_generates_nothing():
    assert generate_acceptance(CHAT_DIR / "chat-app.trig") == {}


def test_the_registered_generator_renders_with_sources_and_traces():
    files = acceptance.generate(TRIG, CHAPTER / "generated" / "acceptance")
    sources = output_sources("acceptance", TRIG, CHAPTER / "generated" / "acceptance")
    assert list(sources) == list(files)
    for iri in (OP, EXP + "ExpenseShape", EXP + "NotificationShape", EXP + "approval_routing", NOTIFY_TASK):
        assert iri in sources["test_notify.py"], iri


def test_the_trace_cites_the_shape_and_decision_each_test_derives_from():
    view = extract_acceptance(ModelGraph(TRIG))
    files = render_acceptance(view)
    trace = trace_acceptance(view)["test_notify.py"]
    lines = files["test_notify.py"].splitlines()

    def terms(fragment: str) -> tuple[str, ...]:
        number = next(i for i, line in enumerate(lines, 1) if fragment in line)
        return next(t.terms for t in trace.lines if t.line == number)

    shape = terms("def test_shape_notify_manager_expense_train")
    assert {EXP + "expense_train", EXP + "ExpenseShape", EXP + "NotificationShape", OP} <= set(shape)
    decision = terms("def test_decision_notify_manager_routes_up_to_1000_to_manager")
    assert {EXP + "routes_up_to_1000_to_manager", EXP + "approval_routing", APPROVAL + "flow_manager"} <= set(decision)
    assert NOTIFY_TASK in decision


def test_a_task_that_fires_a_transition_gets_a_transition_test(tmp_path):
    trig = chat_model(tmp_path, CHAT_NOTIFY)
    view = extract_acceptance(ModelGraph(trig))
    text = render_acceptance(view)["test_notify.py"]
    assert "def test_transition_notify_manager(model):" in text
    assert f'transition_guard(model, "{CHAT}chat_bpmn#persist_user_msg", "{CHAT}t_send")' in text
    trace = trace_acceptance(view)["test_notify.py"]
    number = next(i for i, line in enumerate(text.splitlines(), 1) if "def test_transition_" in line)
    terms = next(t.terms for t in trace.lines if t.line == number)
    assert {f"{CHAT}t_send", f"{CHAT}s_composing", f"{CHAT}s_sending"} <= set(terms)


# ── errors name the fact ─────────────────────────────────────────────────────


def test_a_bad_handler_path_names_the_implementation(tmp_path):
    trig = chat_model(tmp_path, CHAT_NOTIFY.replace('"notify.notify_manager"', '"notify..escape"'))
    with pytest.raises(GeneratorError) as err:
        extract_acceptance(ModelGraph(trig))
    assert str(err.value.subject) == f"{CHAT}py_impl"
    assert str(err.value.predicate) == COMM_HANDLER


def test_two_modules_with_one_test_file_name_the_handler(tmp_path):
    extra = (
        '    :a_op a hydra:Operation ; rdfs:label "a" ; seam:implementedBy :a_impl .\n'
        '    :a_impl a comm:PythonHandler ; rdfs:label "a" ; comm:handler "a.b.run" .\n'
        '    :b_op a hydra:Operation ; rdfs:label "b" ; seam:implementedBy :b_impl .\n'
        '    :b_impl a comm:PythonHandler ; rdfs:label "b" ; comm:handler "a_b.run" .'
    )
    trig = chat_model(tmp_path, extra)
    with pytest.raises(GeneratorError, match="test_a_b.py") as err:
        extract_acceptance(ModelGraph(trig))
    assert str(err.value.predicate) == COMM_HANDLER


# ── the checks against the hand-written body ─────────────────────────────────


def test_chapter_9_handler_passes_every_check(tmp_path):
    model = chapter(tmp_path)
    assert handler_types(model, NOTIFY).ok
    assert handler_result(model, NOTIFY, OP, EXP + "expense_train").ok
    for example in ("routes_up_to_1000_to_manager", "routes_above_1000_to_finance", "routes_up_to_100_automatically"):
        check = decision_route(model, NOTIFY_TASK, EXP + example, tmp_path / f"{example}.sqlite")
        assert check.ok, check.detail


HEADER = "from typing import NotRequired, TypedDict\n\nfrom seams_runtime import OperationError\n\n"


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ("def notify_manager(entity: dict, extra: int) -> dict:\n    return {}\n", "one entity argument"),
        ("def notify_manager(entity) -> dict:\n    return {}\n", "annotate the entity parameter"),
        ("def notify_manager(entity: dict) -> str:\n    return ''\n", "neither dict nor a TypedDict"),
        ("def notify_manager(entity: dict) -> None:\n    return None\n", "admits None"),
        (
            "class Note(TypedDict):\n    message: str\n    recipient: NotRequired[str]\n\n\n"
            "def notify_manager(entity: dict) -> Note:\n    return {'message': ''}\n",
            "('recipient', False)",
        ),
    ],
    ids=["two-parameters", "unannotated", "wrong-return-type", "returns-none", "typed-dict-required-ness"],
)
def test_wrong_types_fail_naming_the_shape_predicate(tmp_path, body, fragment):
    check = handler_types(chapter(tmp_path, HEADER + body), NOTIFY)
    assert not check.ok
    assert fragment in check.detail and NOTIFY.implementation in check.detail


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ("    return {'recipient': 'manager'}\n", f"does not conform to {EXP}NotificationShape"),
        ("    return 'sent'\n", "returned a str"),
        ("    raise OperationError('lost', 'gone')\n", "hydra:possibleStatus declares ['notify-failed']"),
        ("    raise ValueError('boom')\n", "raised ValueError: boom"),
    ],
    ids=["missing-required-field", "not-a-dict", "undeclared-error", "unexpected-exception"],
)
def test_a_wrong_result_fails_naming_the_example_and_shape(tmp_path, body, fragment):
    model = chapter(tmp_path, HEADER + "def notify_manager(entity: dict) -> dict:\n" + body)
    check = handler_result(model, NOTIFY, OP, EXP + "expense_train")
    assert not check.ok
    assert fragment in check.detail and EXP + "expense_train" in check.detail


def test_a_declared_error_passes_the_shape_check_and_routes_to_the_boundary(tmp_path):
    body = "def notify_manager(entity: dict) -> dict:\n    raise OperationError('notify-failed', 'no phone')\n"
    model = chapter(tmp_path, HEADER + body)
    assert handler_result(model, NOTIFY, OP, EXP + "expense_train").ok
    check = decision_route(model, NOTIFY_TASK, EXP + "routes_up_to_1000_to_manager", tmp_path / "seams.sqlite")
    assert check.ok and "boundary caught 'notify-failed'" in check.detail


def test_a_failing_body_fails_the_decision_route(tmp_path):
    model = chapter(tmp_path, HEADER + "def notify_manager(entity: dict) -> dict:\n    raise ValueError('boom')\n")
    check = decision_route(model, NOTIFY_TASK, EXP + "routes_up_to_1000_to_manager", tmp_path / "seams.sqlite")
    assert not check.ok
    assert "the instance failed" in check.detail and EXP + "approval_routing" in check.detail
    # The finance route never reaches the task, so the body is not called.
    assert decision_route(model, NOTIFY_TASK, EXP + "routes_above_1000_to_finance", tmp_path / "f.sqlite").ok


def test_the_transition_guard_names_the_transition_and_states(tmp_path):
    model = chapter(tmp_path)
    check = transition_guard(model, APPROVAL + "record_approval", EXP + "t_approve")
    assert check.ok and "'submitted' to 'approved'" in check.detail
    stale = transition_guard(model, NOTIFY_TASK, EXP + "t_approve")
    assert not stale.ok and "seam:fires None" in stale.detail and EXP + "t_approve" in stale.detail


def test_a_handler_that_does_not_import_fails_every_check(tmp_path):
    model = chapter(tmp_path, "def other(entity):\n    return {}\n")
    for check in (handler_types(model, NOTIFY), handler_result(model, NOTIFY, OP, EXP + "expense_train")):
        assert not check.ok and "has no attribute 'notify_manager'" in check.detail, check.detail


def test_trace_is_json_serialisable():
    trace = trace_acceptance(extract_acceptance(ModelGraph(TRIG)))["test_notify.py"]
    assert json.dumps([line.terms for line in trace.lines])

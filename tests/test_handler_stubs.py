"""The write-once handler stub generator (ADR-0012 regeneration rule, D050).

``python -m seams_gen.stubs`` writes a stub for each comm:PythonHandler whose
module is absent, and never writes a file that exists. Models are the chat app
copied to tmp_path with handler declarations added; handlers directories are
in tmp_path too.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
from seams import model_hash

from seams_gen import golden_target
from seams_gen.stubs import main

ROOT = Path(__file__).resolve().parents[1]
CHAT_DIR = ROOT / "examples" / "chat-app"
CHAT = "https://example.org/chat/"
COMM_HANDLER = "https://w3id.org/seams/comm#handler"
GOLDEN = ROOT / "tests" / "golden" / "handler_stubs" / "notify.py"

LLM_IMPL = ':completion_impl a comm:LLMCompletion ; rdfs:label "LLM completion" .'
NOTIFY = (
    "    :send_message_op seam:implementedBy :py_impl .\n"
    '    :py_impl a comm:PythonHandler ; rdfs:label "python handler" ; comm:handler "notify.notify_manager" .'
)


def extra(name: str, handler: str) -> str:
    """An operation with no shapes, seam:implementedBy a comm:PythonHandler ``handler``."""
    return (
        f'    :{name}_op a hydra:Operation ; rdfs:label "{name}" ; seam:implementedBy :{name}_impl .\n'
        f'    :{name}_impl a comm:PythonHandler ; rdfs:label "{name} handler" ; comm:handler "{handler}" .'
    )


def chat_model(tmp_path: Path, *declarations: str) -> Path:
    """The chat app's model files in ``tmp_path/app`` with ``declarations`` added to the seams graph."""
    app = tmp_path / "app"
    app.mkdir(parents=True)
    for name in ("chat-app.trig", "chat_process.bpmn", "routing.dmn"):
        shutil.copy(CHAT_DIR / name, app / name)
    trig = app / "chat-app.trig"
    text = trig.read_text(encoding="utf-8")
    assert text.count(LLM_IMPL) == 1
    trig.write_text(text.replace(LLM_IMPL, "\n".join([LLM_IMPL, *declarations])), encoding="utf-8")
    return trig


def snapshot(directory: Path) -> dict[str, bytes]:
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in sorted(directory.rglob("*")) if p.is_file()}


def stubs(capsys, *argv) -> tuple[int, str, str]:
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


# ── the stub ─────────────────────────────────────────────────────────────────


def test_stub_matches_the_golden(tmp_path, capsys):
    trig = chat_model(tmp_path, NOTIFY)
    code, out, err = stubs(capsys, trig)
    handlers = trig.parent / "handlers"
    assert (code, err) == (0, "")
    assert out.splitlines() == [str(handlers / "__init__.py"), str(handlers / "notify.py")]
    expected = golden_target(GOLDEN, model_hash(trig))
    assert (handlers / "notify.py").read_text(encoding="utf-8") == expected
    # The package __init__.py is the same generated-once header, with no functions.
    assert (handlers / "__init__.py").read_text(encoding="utf-8") == "".join(expected.splitlines(True)[:3])


def test_the_stub_satisfies_the_runtime_until_it_is_called(tmp_path, capsys):
    from seams_runtime import Runtime
    from seams_runtime.store import SQLiteStore

    trig = chat_model(tmp_path, NOTIFY)
    assert stubs(capsys, trig)[0] == 0
    rt = Runtime.load(
        trig,
        store=SQLiteStore(tmp_path / "seams.sqlite"),
        llm_transport=httpx.MockTransport(lambda r: httpx.Response(500)),
        llm_base_url="http://llm.test",
    )
    impl, target = rt.implementations[rt.model.curie(":send_message_op")]
    assert impl.handler == "notify.notify_manager" and target.__name__ == "notify_manager"


def test_a_second_run_leaves_owned_code_alone(tmp_path, capsys):
    trig = chat_model(tmp_path, NOTIFY)
    assert stubs(capsys, trig)[0] == 0
    module = trig.parent / "handlers" / "notify.py"
    owned = "def notify_manager(entity: dict) -> dict:\n    return {**entity, 'content': 'edited'}\n"
    module.write_text(owned, encoding="utf-8")
    (trig.parent / "handlers" / "__init__.py").write_bytes(b"")
    before = snapshot(trig.parent / "handlers")
    code, out, err = stubs(capsys, trig)
    assert (code, out, err) == (0, "", "")
    assert snapshot(trig.parent / "handlers") == before
    assert module.read_text(encoding="utf-8") == owned


def test_a_module_without_the_function_is_reported_not_patched(tmp_path, capsys):
    trig = chat_model(tmp_path, NOTIFY)
    handlers = trig.parent / "handlers"
    handlers.mkdir()
    (handlers / "__init__.py").write_text("", encoding="utf-8")
    (handlers / "notify.py").write_text("def notify_someone(entity):\n    return entity\n", encoding="utf-8")
    before = snapshot(handlers)
    code, out, err = stubs(capsys, trig)
    assert (code, out) == (0, "")
    assert snapshot(handlers) == before
    (line,) = err.splitlines()
    assert line.startswith(f"python -m seams_gen.stubs: {CHAT}py_impl: {COMM_HANDLER}: ")
    assert '"notify.notify_manager"' in line and "defines no notify_manager" in line


def test_a_module_that_does_not_parse_is_reported(tmp_path, capsys):
    trig = chat_model(tmp_path, NOTIFY)
    handlers = trig.parent / "handlers"
    handlers.mkdir()
    (handlers / "__init__.py").write_text("", encoding="utf-8")
    (handlers / "notify.py").write_text("def notify_manager(:\n", encoding="utf-8")
    code, out, err = stubs(capsys, trig)
    assert (code, out) == (0, "")
    assert f"{CHAT}py_impl: {COMM_HANDLER}: " in err and "does not parse" in err


def test_an_absent_function_in_a_new_module_is_written_beside_owned_modules(tmp_path, capsys):
    trig = chat_model(tmp_path, NOTIFY, extra("audit", "audit.record"))
    handlers = trig.parent / "handlers"
    handlers.mkdir()
    (handlers / "__init__.py").write_text("", encoding="utf-8")
    (handlers / "notify.py").write_text("def notify_manager(entity):\n    return entity\n", encoding="utf-8")
    code, out, err = stubs(capsys, trig)
    assert (code, err) == (0, "")
    assert out.splitlines() == [str(handlers / "audit.py")]
    text = (handlers / "audit.py").read_text(encoding="utf-8")
    # No seam:returnsShape: the handler must return None (ADR-0012).
    assert "def record(entity: dict) -> None:" in text
    assert "Returns: None; the operation states no seam:returnsShape." in text
    assert "entity: the operation states no seam:acceptsShape." in text


def test_nested_handler_paths_get_their_packages(tmp_path, capsys):
    trig = chat_model(tmp_path, extra("pay", "billing.pay.pay_expense"), extra("refund", "billing.refund"))
    code, _, err = stubs(capsys, trig)
    handlers = trig.parent / "handlers"
    assert (code, err) == (0, "")
    assert sorted(snapshot(handlers)) == ["__init__.py", "billing/__init__.py", "billing/pay.py"]
    # billing is a package, so billing.refund is a function of billing/__init__.py.
    assert "def refund(entity: dict) -> None:" in (handlers / "billing" / "__init__.py").read_text()
    assert "def pay_expense(entity: dict) -> None:" in (handlers / "billing" / "pay.py").read_text()


def test_output_is_deterministic(tmp_path, capsys):
    declarations = (NOTIFY, extra("zeta", "notify.zeta"), extra("alpha", "notify.alpha"))
    runs = []
    for seed in ("0", "1"):
        trig = chat_model(tmp_path / seed, *declarations)
        env = {**os.environ, "PYTHONHASHSEED": seed}
        subprocess.run(
            [sys.executable, "-m", "seams_gen.stubs", str(trig)], check=True, cwd=ROOT, env=env, capture_output=True
        )
        runs.append(snapshot(trig.parent / "handlers"))
    assert runs[0] == runs[1]
    text = runs[0]["notify.py"].decode()
    assert text.index("def alpha") < text.index("def notify_manager") < text.index("def zeta")


def test_the_chat_app_writes_nothing(tmp_path, capsys):
    handlers = tmp_path / "handlers"
    code, out, err = stubs(capsys, CHAT_DIR / "chat-app.trig", "--handlers", handlers)
    assert (code, out, err) == (0, "", "")
    assert not handlers.exists()


# ── errors ───────────────────────────────────────────────────────────────────


def test_a_bad_handler_path_exits_2_and_writes_nothing(tmp_path, capsys):
    trig = chat_model(tmp_path, NOTIFY, extra("bad", "notify..escape"))
    code, out, err = stubs(capsys, trig)
    assert (code, out) == (2, "")
    assert err.startswith(f"python -m seams_gen.stubs: {CHAT}bad_impl: {COMM_HANDLER}: ")
    assert not (trig.parent / "handlers").exists()


def test_a_bad_kind_exits_2(tmp_path, capsys):
    trig = chat_model(
        tmp_path,
        '    :send_message_op seam:implementedBy :odd_impl .\n    :odd_impl a comm:Channel ; rdfs:label "odd" .',
    )
    code, _, err = stubs(capsys, trig)
    assert code == 2
    assert f"{CHAT}odd_impl: http://www.w3.org/1999/02/22-rdf-syntax-ns#type: " in err


def test_a_missing_model_exits_1(tmp_path, capsys):
    code, out, err = stubs(capsys, tmp_path / "absent.trig")
    assert (code, out) == (1, "")
    assert "no such model file" in err


def test_an_unwritable_handlers_directory_exits_1(tmp_path, capsys):
    trig = chat_model(tmp_path, NOTIFY)
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")
    code, out, err = stubs(capsys, trig, "--handlers", blocker / "handlers")
    assert (code, out) == (1, "")
    assert err.startswith("python -m seams_gen.stubs: ")

"""``seams propose`` (M022/S04, backlog C4, D059) with fake provider commands on a
copy of the expense tutorial's chapter 9 without its handlers/notify.py. No network."""

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import sys
from pathlib import Path

import pytest
from seams_cli import LockError, read_lock
from seams_cli.__main__ import main
from seams_cli.project import ProjectError, load_project
from seams_cli.propose import CACHE_DIR, extract_draft, propose

from tests.workspace_copy import copy_example

ROOT = Path(__file__).resolve().parent.parent
CH09 = ROOT / "examples" / "expenses" / "chapter-09"
FIXTURES = ROOT / "tests" / "fixtures" / "propose"
TASK = "notify_manager"


def _provider(name: str, *args: str) -> str:
    return shlex.join([sys.executable, str(FIXTURES / name), *args])


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch):
    monkeypatch.delenv("SEAMS_MODEL", raising=False)


@pytest.fixture
def app(tmp_path) -> Path:
    root = copy_example(CH09, tmp_path, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "handlers" / "notify.py").unlink()
    return root


def test_accepts_a_passing_draft_and_writes_the_handlers_module(app, capsys):
    code = main(["propose", TASK, "--project", str(app), "--provider", _provider("good_provider.py")])
    out = capsys.readouterr().out
    assert code == 0, out
    assert (app / "handlers" / "notify.py").read_text() == (CH09 / "handlers" / "notify.py").read_text()
    lines = out.splitlines()
    assert lines[0] == "task https://example.org/expenses/approval_bpmn#notify_manager"
    assert lines[1].startswith("context sha256:")
    assert lines[2] == "template draft-v1"
    assert lines[3].startswith("provider ")
    assert lines[4] == "cache miss"
    assert lines[5].startswith("draft sha256:")
    assert lines[-2:] == ["tests passed", "wrote handlers/notify.py"]


def test_rejects_a_failing_draft_writes_nothing_and_names_the_tests(app, capsys):
    before = sorted(p.relative_to(app) for p in (app / "handlers").rglob("*"))
    code = main(["propose", TASK, "--project", str(app), "--provider", _provider("bad_provider.py")])
    captured = capsys.readouterr()
    assert code == 1
    assert not (app / "handlers" / "notify.py").exists()
    assert sorted(p.relative_to(app) for p in (app / "handlers").rglob("*")) == before
    assert "failed test_shape_notify_manager_expense_train" in captured.out.splitlines()
    assert "nothing written" in captured.err


def test_a_cache_hit_does_not_call_the_provider(app, tmp_path):
    provider = _provider("good_provider.py", str(tmp_path / "calls"))
    first = propose(load_project(app), None, TASK, provider)
    (app / "handlers" / "notify.py").unlink()
    second = propose(load_project(app), None, TASK, provider)
    assert (first.cache_hit, second.cache_hit) == (False, True)
    assert second.passed and second.written == "handlers/notify.py"
    assert first.sha256 == second.sha256
    assert (tmp_path / "calls").read_text() == "1"
    assert len(list((app / CACHE_DIR).iterdir())) == 1


def test_provider_failure_is_reported_and_nothing_cached(app, capsys):
    code = main(["propose", TASK, "--project", str(app), "--provider", _provider("bad_provider.py", "--exit", "3")])
    err = capsys.readouterr().err
    assert code == 1
    assert "exited 3: quota exceeded" in err
    assert not (app / CACHE_DIR).exists()
    assert not (app / "handlers" / "notify.py").exists()


def test_missing_provider_command_is_reported(app, capsys):
    assert main(["propose", TASK, "--project", str(app), "--provider", "no-such-provider-xyz"]) == 1
    assert "command not found" in capsys.readouterr().err


def test_refuses_to_overwrite_an_existing_module_without_force(tmp_path, capsys):
    root = copy_example(CH09, tmp_path, ignore=shutil.ignore_patterns("__pycache__"))
    before = (root / "handlers" / "notify.py").read_text()
    args = ["propose", TASK, "--project", str(root), "--provider", _provider("bad_provider.py")]
    assert main(args) == 2
    assert "--force" in capsys.readouterr().err
    assert main([*args, "--force"]) == 1
    assert (root / "handlers" / "notify.py").read_text() == before


def test_provider_from_the_project_file(app):
    toml = app / "seams.toml"
    toml.write_text(toml.read_text() + f"\n[propose]\nprovider = {_provider('good_provider.py')!r}\n")
    result = propose(load_project(app), None, TASK)
    assert result.passed and result.provider == _provider("good_provider.py")


def test_no_provider_is_a_project_error(app):
    with pytest.raises(ProjectError, match=r"\[propose\] provider"):
        propose(load_project(app), None, TASK)


def test_bad_propose_table_is_a_project_error(app):
    toml = app / "seams.toml"
    toml.write_text(toml.read_text() + "\n[propose]\nprovider = 3\n")
    with pytest.raises(ProjectError, match="propose.provider"):
        load_project(app)


def test_unknown_task_exits_2(app, capsys):
    assert main(["propose", "no_such_task", "--project", str(app), "--provider", _provider("good_provider.py")]) == 2
    assert not (app / CACHE_DIR).exists()


@pytest.mark.parametrize(
    ("response", "draft"),
    [
        ("```python\nx = 1\n```\n", "x = 1\n"),
        ("\n````\nx = '```'\n````", "x = '```'\n"),
        ("x = 1\n", "x = 1\n"),
        ("intro\n```python\nx = 1\n```\n", "intro\n```python\nx = 1\n```\n"),
    ],
)
def test_extract_draft_strips_one_fence(response, draft):
    assert extract_draft(response) == draft


def _drafts(app: Path) -> list[dict]:
    return json.loads((app / "seams.lock").read_text(encoding="utf-8")).get("drafts", [])


def test_an_accepted_draft_is_recorded_in_the_lock(app):
    (app / "seams.lock").unlink(missing_ok=True)
    result = propose(load_project(app), None, TASK, _provider("good_provider.py"))
    written = (app / "handlers" / "notify.py").read_bytes()
    assert _drafts(app) == [
        {
            "context_hash": result.context_hash,
            "path": "handlers/notify.py",
            "provider": _provider("good_provider.py"),
            "sha256": hashlib.sha256(written).hexdigest(),
            "task": result.task,
            "template": "draft-v1",
        }
    ]
    assert read_lock(load_project(app)).drafts[0].sha256 == result.sha256.removeprefix("sha256:")


def test_a_rejected_draft_leaves_the_lock_unchanged(app):
    lock = app / "seams.lock"
    before = lock.read_bytes() if lock.exists() else None
    assert not propose(load_project(app), None, TASK, _provider("bad_provider.py")).passed
    assert (lock.read_bytes() if lock.exists() else None) == before


def test_a_second_acceptance_replaces_the_record(app):
    propose(load_project(app), None, TASK, _provider("good_provider.py"))
    once = (app / "seams.lock").read_bytes()
    propose(load_project(app), None, TASK, _provider("good_provider.py"), force=True)
    assert (app / "seams.lock").read_bytes() == once
    assert len(_drafts(app)) == 1


def test_generate_keeps_the_draft_record(app, capsys):
    propose(load_project(app), None, TASK, _provider("good_provider.py"))
    drafts = _drafts(app)
    assert main(["generate", "--project", str(app)]) == 0, capsys.readouterr()
    assert _drafts(app) == drafts


def test_a_malformed_lock_writes_nothing(app):
    (app / "seams.lock").write_text("{not json", encoding="utf-8")
    with pytest.raises(LockError, match="invalid JSON"):
        propose(load_project(app), None, TASK, _provider("good_provider.py"))
    assert not (app / "handlers" / "notify.py").exists()
    assert not (app / CACHE_DIR).exists()

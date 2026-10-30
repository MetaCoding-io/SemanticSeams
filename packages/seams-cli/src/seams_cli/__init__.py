"""seams_cli: the ``seams`` command line (D042).

``seams generate`` reads an app's seams.toml project file (``load_project``),
picks the model (``resolve_model``) and rewrites every output its generators
name (``generate_project``, ``apply``), recording them in seams.lock
(``read_lock``, ``build_lock``, ``render_lock``, ``audit``). ``seams check``
(``run_check``) reports every ``Finding`` without writing; ``seams status``
(``run_status``) gives a ``Status`` per running runtime container. The editable
install puts the repository root on sys.path, so the virtual members seams_gen
and seams_runtime import from any working directory.
"""

from .check import Finding, run_check
from .generate import apply, generate_project, write_outputs
from .lockfile import LOCK_FILE, Audit, Lock, LockedOutput, LockError, Output, audit, build_lock, read_lock, render_lock
from .project import GeneratorTarget, Project, ProjectError, load_project, resolve_model
from .status import Status, run_status

__all__ = [
    "LOCK_FILE",
    "Audit",
    "Finding",
    "Lock",
    "LockError",
    "LockedOutput",
    "Output",
    "Status",
    "apply",
    "audit",
    "build_lock",
    "read_lock",
    "render_lock",
    "GeneratorTarget",
    "Project",
    "ProjectError",
    "generate_project",
    "load_project",
    "resolve_model",
    "run_check",
    "run_status",
    "write_outputs",
]

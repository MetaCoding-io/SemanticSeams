"""seams_cli: the ``seams`` command line (D042).

``seams generate`` reads an app's seams.toml project file (``load_project``),
picks the model (``resolve_model``) and rewrites every output its generators
name (``generate_project``, ``write_outputs``). The editable install puts the
repository root on sys.path, so the virtual members seams_gen and
seams_runtime import from any working directory.
"""

from .generate import generate_project, write_outputs
from .project import GeneratorTarget, Project, ProjectError, load_project, resolve_model

__all__ = [
    "GeneratorTarget",
    "Project",
    "ProjectError",
    "generate_project",
    "load_project",
    "resolve_model",
    "write_outputs",
]

"""Command line: ``seams generate|check [--project PATH] [--model PATH]``.

``--project`` is a seams.toml file or a directory holding one (default: the
working directory); ``--model`` overrides the project's model. Each written
path is printed, relative to the working directory when it lies below it.

The project's seams.lock (D043) records every output; generate rewrites it
last and prints its path. An output the old lock lists but no generator writes
any more is deleted and printed as ``removed <path>`` when it is a regular file
still matching its locked hash; otherwise it is kept and reported on stderr as
``kept hand-edited orphan``. A locked output edited by hand is reported as
``overwrote hand-edited``, a deleted one as ``restored deleted``; both are
rewritten and the exit code stays 0. A malformed seams.lock exits 2 before
anything is written.
A ProjectError or GeneratorError prints ``seams generate: <message>`` to
stderr and exits 2; a file that cannot be read or written exits 1.

``seams check`` (D044) writes nothing. It validates the model against the
SHACL shapes, runs the project's gate queries and compares the outputs
generate would write with the disk and seams.lock. Each finding prints to
stdout as ``<kind> <detail>``; with any finding, ``seams check: N problem(s)``
goes to stderr and the exit code is 1. A model that cannot be loaded, a bad
gate or a malformed seams.lock exits 2. The ``status`` subcommand is to come
(M012/S04).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from seams_gen import GeneratorError

from .check import FILE_KINDS, run_check
from .generate import apply, generate_project
from .lockfile import locate
from .project import ProjectError, load_project, resolve_model

EXIT_PROJECT_ERROR = 2
EXIT_IO_ERROR = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seams", description="Work with a Semantic Seams project (seams.toml).")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")
    gen = sub.add_parser(
        "generate",
        help="rewrite every generated output the project file names",
        description="Run every generator of the project file and write its outputs.",
    )
    _project_arguments(gen)
    gen.set_defaults(run=_generate)
    check = sub.add_parser(
        "check",
        help="fail on SHACL violations, gate rows and stale outputs; writes nothing",
        description="Validate the model, run the project's gate queries and compare the outputs with the disk.",
    )
    _project_arguments(check)
    check.set_defaults(run=_check)
    return parser


def _project_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project", type=Path, default=Path("."), help="seams.toml or a directory holding one (default: .)"
    )
    parser.add_argument("--model", type=Path, help="the model (.trig); overrides the project file and SEAMS_MODEL")


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _generate(args: argparse.Namespace) -> int:
    project = load_project(args.project)
    model = resolve_model(project, args.model)
    files = generate_project(project, model)
    applied = apply(project, model, files)
    report = applied.audit
    for kind, paths in (("overwrote hand-edited", report.edited), ("restored deleted", report.missing)):
        for rel in paths:
            print(f"seams generate: {kind} {_display(locate(project, rel))}", file=sys.stderr)
    for path in applied.kept:
        print(f"seams generate: kept hand-edited orphan {_display(path)}", file=sys.stderr)
    for path in sorted(files):
        print(_display(path))
    for path in applied.removed:
        print(f"removed {_display(path)}")
    print(_display(applied.lock))
    return 0


def _check(args: argparse.Namespace) -> int:
    project = load_project(args.project)
    findings = run_check(project, resolve_model(project, args.model))
    for finding in findings:
        detail = _display(Path(finding.detail)) if finding.kind in FILE_KINDS else finding.detail
        print(f"{finding.kind} {detail}")
    if findings:
        print(f"seams check: {len(findings)} problem(s)", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except (ProjectError, GeneratorError) as err:
        print(f"seams {args.command}: {err}", file=sys.stderr)
        return EXIT_PROJECT_ERROR
    except OSError as err:
        print(f"seams {args.command}: {err}", file=sys.stderr)
        return EXIT_IO_ERROR


if __name__ == "__main__":
    sys.exit(main())

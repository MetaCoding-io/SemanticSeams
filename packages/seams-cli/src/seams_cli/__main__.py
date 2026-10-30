"""Command line: ``seams generate [--project PATH] [--model PATH]``.

``--project`` is a seams.toml file or a directory holding one (default: the
working directory); ``--model`` overrides the project's model. Each written
path is printed, relative to the working directory when it lies below it.
A ProjectError or GeneratorError prints ``seams generate: <message>`` to
stderr and exits 2; a file that cannot be read or written exits 1.
The ``check`` and ``status`` subcommands are to come (M012/S03, S04).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from seams_gen import GeneratorError

from .generate import generate_project, write_outputs
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
    gen.add_argument(
        "--project", type=Path, default=Path("."), help="seams.toml or a directory holding one (default: .)"
    )
    gen.add_argument("--model", type=Path, help="the model (.trig); overrides the project file and SEAMS_MODEL")
    gen.set_defaults(run=_generate)
    return parser


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _generate(args: argparse.Namespace) -> int:
    project = load_project(args.project)
    files = generate_project(project, resolve_model(project, args.model))
    write_outputs(files)
    for path in sorted(files):
        print(_display(path))
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

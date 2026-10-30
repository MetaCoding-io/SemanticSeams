"""Command line: ``python -m seams_gen <generator> <trig> --out <dir>``.

Each generator is a subcommand registered in ``GENERATORS``: ``htmx`` (S04),
``fastapi`` (S05) and ``compose`` (S06). A generator is called as
``generate(trig, out)`` and returns ``{relative file name: text}``; only
``compose`` uses ``out``, as the base directory its bind-mount sources are
relative to (D018). A GeneratorError (a missing or
ambiguous graph fact) prints its message, which names the subject IRI and the
predicate, to stderr and exits 2. A file that cannot be read or written exits 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from seams import load

from . import GeneratorError
from .compose import generate_compose
from .fastapi import route_module
from .htmx import generate_pages

EXIT_GENERATOR_ERROR = 2
EXIT_IO_ERROR = 1


def _htmx(trig: Path, out: Path) -> dict[str, str]:
    """{file name: content}: the landmark page as <page local name>.html, plus
    the fragment partials its UIFragment operations render (GAP-19), the
    partial of each form a user task is completed on (ADR-0009), and each
    other page of ``model.interfaces.served_pages()`` with its partials."""
    return generate_pages(load(trig))


def _fastapi(trig: Path, out: Path) -> dict[str, str]:
    """{<container local name>.py: content}: the route module of the one
    container that seam:executes a process."""
    name, text = route_module(trig)
    return {name: text}


def _compose(trig: Path, out: Path) -> dict[str, str]:
    """{compose.yaml: content}: the docker compose file of the arch:System's
    containers, with bind-mount sources relative to the output directory."""
    return {"compose.yaml": generate_compose(trig, base_dir=out)}


# subcommand -> (help, generate(trig, out) -> {relative file name: text})
GENERATORS = {
    "htmx": ("the htmx/Jinja2 page of the landmark IFML ViewContainer and its fragment partials", _htmx),
    "fastapi": ("the thin FastAPI route module of the container that executes the process", _fastapi),
    "compose": ("the docker compose file of the arch:System's containers", _compose),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m seams_gen", description="Generate code from a seams model.")
    sub = parser.add_subparsers(dest="generator", required=True, metavar="generator")
    for name, (help_text, generate) in GENERATORS.items():
        p = sub.add_parser(name, help=help_text, description=f"Generate {help_text}.")
        p.add_argument("trig", type=Path, help="the seams model (.trig)")
        p.add_argument("--out", type=Path, required=True, help="output directory (created if missing)")
        p.set_defaults(generate=generate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        files = args.generate(args.trig, args.out)
        args.out.mkdir(parents=True, exist_ok=True)
        for name, text in sorted(files.items()):
            path = args.out / name
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            print(path)
    except GeneratorError as err:
        print(f"seams_gen {args.generator}: {err}", file=sys.stderr)
        return EXIT_GENERATOR_ERROR
    except OSError as err:
        print(f"seams_gen {args.generator}: {err}", file=sys.stderr)
        return EXIT_IO_ERROR
    return 0


if __name__ == "__main__":
    sys.exit(main())

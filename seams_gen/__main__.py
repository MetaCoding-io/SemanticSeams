"""Command line: ``python -m seams_gen <generator> <trig> --out <dir>``.

Each generator is a subcommand registered in ``GENERATORS``; S05 and S06 add
``fastapi`` and ``compose`` the same way. A GeneratorError (a missing or
ambiguous graph fact) prints its message, which names the subject IRI and the
predicate, to stderr and exits 2. A file that cannot be read or written exits 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import GeneratorError
from .htmx import extract_page, render_page
from seams_runtime import ModelGraph

EXIT_GENERATOR_ERROR = 2
EXIT_IO_ERROR = 1


def _htmx(trig: Path) -> dict[str, str]:
    """{file name: content}: the landmark page as <page local name>.html."""
    page = extract_page(ModelGraph.load(trig))
    return {f"{page.id}.html": render_page(page)}


# subcommand -> (help, generate(trig) -> {relative file name: text})
GENERATORS = {
    "htmx": ("the htmx/Jinja2 page of the landmark IFML ViewContainer", _htmx),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m seams_gen",
                                     description="Generate code from a seams model.")
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
        files = args.generate(args.trig)
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

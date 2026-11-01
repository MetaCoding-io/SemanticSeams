"""Command line: ``python -m seams_gen <generator> <trig> --out <dir>``.

Each generator of the ``seams.generators`` entry-point group (D056,
``seams_gen.registry``) is a subcommand of ``GENERATORS``. The built-ins are
``htmx`` (S04), ``fastapi`` (S05), ``compose`` (S06), ``tests`` (M015,
ADR-0014), ``smoke`` (M015/S05, backlog A9), ``dockerfile`` (M016/S03) and
``ifmledit`` (M008/S01, backlog 12), the objects of ``seams_gen.builtin``. A
generator is called as ``generate(trig, out)`` and returns ``{relative file
name: text}``; only ``compose`` uses ``out``, as the base directory its
bind-mount sources, build contexts and secret files are relative to (D018).
``compose`` writes one ``compose.<environment>.yaml`` per arch:Environment
(ADR-0015). A GeneratorError (a missing or ambiguous graph fact) prints its
message, which names the subject IRI and the predicate, to stderr and exits 2.
A file that cannot be read or written exits 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import GeneratorError
from .registry import discover

EXIT_GENERATOR_ERROR = 2
EXIT_IO_ERROR = 1

# subcommand -> (help, generate(trig, out) -> {relative file name: text}): a
# view of the seams.generators registry (D056), sorted by name
GENERATORS = {name: (g.help, g.generate) for name, g in discover().items()}


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

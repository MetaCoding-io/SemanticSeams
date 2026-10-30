"""Command line: ``python -m seams_gen.complexity <trig>``.

Measures how much of a model the viewer's cross-layer views have to work with
(backlog E3, D025). It runs the three queries in ``docs/queries/complexity/``
and gates two of the numbers:

- models per notation: at least ``MIN_MULTI_MODEL_NOTATIONS`` notations must
  have two or more models;
- the elements reached from the most distinct models: the top one must be
  reached from at least ``MIN_MAX_REACH`` models;
- cross-layer seam edges: reported, not gated (one large model can have many
  edges and still be fully visible by descent).

Only the TriG is loaded, never ``ontology/*.ttl``: the ontology's
``seam:reveal`` annotations are seam: triples too and would inflate the edge
count (60 to 86 for the chat app). Exits 0 on pass, 1 on fail, and 2 with the
message on stderr when the model cannot be read or parsed.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import rdflib
import seams

MIN_MULTI_MODEL_NOTATIONS = 3
MIN_MAX_REACH = 5
TOP_REACHED = 5

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2

QUERY_DIR = Path(__file__).resolve().parents[1] / "docs" / "queries" / "complexity"


def _query(name: str) -> str:
    return (QUERY_DIR / name).read_text(encoding="utf-8")


def load_model(trig: Path) -> rdflib.Graph:
    """The model in ``trig``, loaded through ``seams.load``: the union of every
    named graph and the default graph, TriG only. The ontology is deliberately
    not loaded."""
    return seams.load(trig).ds


def _ranked(rows) -> list[tuple[str, int]]:
    """(IRI, count) pairs sorted by count descending, then IRI."""
    return sorted(((str(r[0]), int(r[1])) for r in rows), key=lambda x: (-x[1], x[0]))


@dataclass(frozen=True)
class Complexity:
    models_per_notation: list[tuple[str, int]]
    most_reached: list[tuple[str, int]]
    edges: int

    @property
    def multi_model_notations(self) -> int:
        return sum(1 for _, n in self.models_per_notation if n >= 2)

    @property
    def max_reach(self) -> int:
        return self.most_reached[0][1] if self.most_reached else 0

    @property
    def failures(self) -> list[str]:
        out = []
        if self.multi_model_notations < MIN_MULTI_MODEL_NOTATIONS:
            out.append(
                f"notations with 2+ models: {self.multi_model_notations}, need at least {MIN_MULTI_MODEL_NOTATIONS}"
            )
        if self.max_reach < MIN_MAX_REACH:
            out.append(f"most models one element is reached from: {self.max_reach}, need at least {MIN_MAX_REACH}")
        return out


def measure(graph: rdflib.Graph) -> Complexity:
    """Run the three complexity queries against ``graph``.

    most-reached.rq ends in ``LIMIT 5``, but SPARQL orders ties arbitrarily, so
    the limit is dropped here and the top five are taken after the
    deterministic (count, IRI) sort; otherwise which tied element makes the
    cut would vary between runs."""
    per_notation = _ranked(graph.query(_query("models-per-notation.rq")))
    unlimited = re.sub(r"\s*LIMIT\s+\d+\s*$", "\n", _query("most-reached.rq").rstrip())
    reached = _ranked(graph.query(unlimited))[:TOP_REACHED]
    edges = int(next(iter(graph.query(_query("seam-edges.rq"))))[0])
    return Complexity(per_notation, reached, edges)


def _local(iri: str) -> str:
    return re.split(r"[#/]", iri)[-1]


def report(result: Complexity) -> str:
    lines = ["models per notation:"]
    lines += [f"  {_local(n)}: {c}" for n, c in result.models_per_notation]
    lines.append("most reached (distinct models):")
    lines += [f"  {_local(t)}: {c}" for t, c in result.most_reached]
    lines.append(f"seam edges: {result.edges} (reported, not gated)")
    failures = result.failures
    lines.append("FAIL" if failures else "PASS")
    lines += [f"  {f}" for f in failures]
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m seams_gen.complexity", description="Measure a seams model's cross-layer complexity."
    )
    parser.add_argument("trig", type=Path, help="the model's TriG file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.trig.is_file():
            raise FileNotFoundError(f"no such model file: {args.trig}")
        result = measure(load_model(args.trig))
    except Exception as exc:  # missing file, OSError, or any rdflib parse error
        print(f"python -m seams_gen.complexity: {args.trig}: {exc}", file=sys.stderr)
        return EXIT_ERROR
    sys.stdout.write(report(result))
    return EXIT_FAIL if result.failures else EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())

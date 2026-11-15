"""``seams observed``: ask the as-observed questions of recorded runs (M032/S01, ADR-0042).

``run_observed`` loads the project's model (``resolve_model``, so ``--model``
and SEAMS_MODEL apply as for generate), reads each RUN with
``seams_gen.sequence.read_trace`` (a trace JSON file, or an instance id in the
runtime's SQLite store at ``db``, default SEAMS_DB, else
``<project root>/seams.sqlite``, as ``seams sequence --trace`` does) and each
``--spans`` file with ``seams.spans_to_runs``, builds one
``seams.observed_graph`` and asks ``dead-model`` and ``conformance`` with
``seams.observed_question``, then checks the model's latency budgets with
``seams.budget_results`` (M032/S02, ADR-0043): each ``nfr:LatencyBudget`` is
met, missed or unobserved. Nothing is written, and the model and its hash
are not touched.

A run read from a trace file whose instance result names no ``instance`` is
named by the RUN argument as given. ``Observed.lines`` gives the text report,
``Observed.to_json`` the JSON one; both are sorted. An unknown instance or a
malformed trace file raises GeneratorError, a malformed span file or row or
a malformed budget ResolutionError (both exit 2), and a model that cannot be loaded
ProjectError (exit 2).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import seams
from rdflib import Graph
from rdflib.term import Node

from seams_gen.sequence import read_trace

from .project import Project, ProjectError, resolve_model

#: The report's sections, in print order, with the query variables each line shows.
SECTIONS = (("dead-model", ("node", "process")), ("conformance", ("run", "index", "reason", "reached")))

#: The budgets section's columns, in print order (one ``budget`` line per budget).
BUDGET_KEYS = ("budget", "element", "max_ms", "percentile", "observed_ms", "samples", "verdict")


@dataclass(frozen=True)
class Observed:
    """The answers for one set of recorded runs."""

    graph: str
    runs: int
    steps: int
    answers: dict[str, list[dict[str, str]]]
    budgets: list[dict[str, str]]

    def lines(self) -> list[str]:
        """One ``<section> <value>...`` line per answer row, then one ``budget
        <budget> <element> <max_ms> <percentile> <observed_ms> <samples>
        <verdict>`` line per latency budget; ``-`` for an unbound value."""
        out: list[str] = []
        for section, keys in SECTIONS:
            out.extend(f"{section} " + " ".join(row.get(k, "-") for k in keys) for row in self.answers[section])
        out.extend("budget " + " ".join(row[k] or "-" for k in BUDGET_KEYS) for row in self.budgets)
        return out

    def to_json(self) -> dict[str, object]:
        """The graph IRI, counts, answers and ``budgets`` (``observed_ms`` null when unobserved)."""
        budgets = [{k: (row[k] or None) for k in BUDGET_KEYS} for row in self.budgets]
        return {"graph": self.graph, "runs": self.runs, "steps": self.steps, **self.answers, "budgets": budgets}

    def summary(self) -> str:
        dead, odd = len(self.answers["dead-model"]), len(self.answers["conformance"])
        missed = sum(1 for row in self.budgets if row["verdict"] == "missed")
        return (
            f"{self.runs} run(s), {self.steps} step(s): {dead} unreached node(s), {odd} unexplained step(s), "
            f"{missed} of {len(self.budgets)} budget(s) missed"
        )


def budget_rows(results: Sequence[seams.BudgetResult]) -> list[dict[str, str]]:
    """``seams.budget_results`` as text cells, in its order; ``observed_ms`` is "" when unobserved."""
    return [
        {
            "budget": str(r.budget),
            "element": str(r.element),
            "max_ms": str(r.max_ms),
            "percentile": str(r.percentile),
            "observed_ms": "" if r.observed_ms is None else str(r.observed_ms),
            "samples": str(r.samples),
            "verdict": r.verdict,
        }
        for r in results
    ]


def _cell(graph: Graph, name: str, value: Node) -> str:
    """A run is shown by its instance id, every other value as its text."""
    if name == "run":
        instance = graph.value(value, seams.OBS.instance)  # pyright: ignore[reportArgumentType]
        if instance is not None:
            return str(instance)
    return str(value)


def _sorted(graph: Graph, rows: list[dict[str, Node]], keys: Sequence[str]) -> list[dict[str, str]]:
    found = [{k: _cell(graph, k, v) for k, v in row.items()} for row in rows]

    def key(row: dict[str, str]) -> tuple[object, ...]:
        return tuple(int(row[k]) if k == "index" else row.get(k, "") for k in keys)

    return sorted(found, key=key)


def run_observed(
    project: Project,
    model: Path | None,
    runs: Sequence[str],
    spans: Sequence[Path] = (),
    db: Path | None = None,
) -> Observed:
    """The dead-model and conformance answers and the budget verdicts for ``runs`` and ``spans`` over the project's model."""
    trig = resolve_model(project, model)
    try:
        loaded = seams.load(trig)
    except Exception as err:
        raise ProjectError(f"{trig}: cannot load the model: {err}") from err
    store = db if db is not None else Path(os.environ.get("SEAMS_DB") or project.root / "seams.sqlite")
    recorded: list[seams.ObservedRun] = []
    for source in runs:
        run, rows = read_trace(source, store)
        recorded.append(seams.ObservedRun(run if run is not None else source, rows))
    for path in spans:
        recorded.extend(seams.spans_to_runs(path.read_text(encoding="utf-8")))
    graph = seams.observed_graph(recorded)
    answers = {
        section: _sorted(graph, seams.observed_question(loaded, graph, section), keys) for section, keys in SECTIONS
    }
    steps = sum(len(r.rows) for r in recorded)
    budgets = budget_rows(seams.budget_results(loaded, graph))
    return Observed(str(graph.identifier), len(recorded), steps, answers, budgets)

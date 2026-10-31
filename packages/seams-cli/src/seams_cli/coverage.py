"""``seams coverage``: what the model declares that no scenario or test exercises (M015/S04, D054).

Three reports, from ``seams.coverage``:

- ``path``: a start-to-end BPMN path no verify:Scenario runs, as its process
  IRI and then its flow node IRIs in walk order.
- ``transition``: a state:Transition nothing seam:fires, as its lifecycle IRI
  and its IRI.
- ``policy``: an odrl:permission the ``tests`` generator writes no party deny
  test for, as its policy, target and assignee IRIs (``-`` when absent).

``coverage_report(model)`` returns them as ``Gap`` rows, in that order and in
``seams.coverage``'s fixed order within each. ``to_json`` gives the
``--json`` form.
"""

from __future__ import annotations

from typing import NamedTuple

import seams

PATH = "path"
TRANSITION = "transition"
POLICY = "policy"
KINDS = (PATH, TRANSITION, POLICY)
ABSENT = "-"


class Gap(NamedTuple):
    """One uncovered element. ``iris`` are full IRIs: the owner (process,
    lifecycle or policy) first, then the path nodes, the transition, or the
    permission's target and assignee (``-`` when absent)."""

    kind: str
    iris: tuple[str, ...]


def path_gaps(model: seams.Model) -> list[Gap]:
    return [Gap(PATH, (str(p.process.iri), *(str(i) for i in p.iris))) for p in seams.unexercised_paths(model)]


def coverage_report(model: seams.Model) -> list[Gap]:
    """Every gap: unexercised paths, then unfired transitions, then permissions without a deny test."""
    gaps = path_gaps(model)
    gaps += [Gap(TRANSITION, (str(t.model), str(t.iri))) for t in seams.unfired_transitions(model)]
    gaps += [
        Gap(POLICY, (str(u.policy.iri), str(u.target or ABSENT), str(u.assignee or ABSENT)))
        for u in seams.policies_without_deny(model)
    ]
    return gaps


def to_json(gaps: list[Gap]) -> dict:
    """``{"paths": [...], "transitions": [...], "policies": [...], "counts": {...}}`` with full IRIs."""
    paths = [{"process": g.iris[0], "nodes": list(g.iris[1:]), "end": g.iris[-1]} for g in gaps if g.kind == PATH]
    transitions = [{"lifecycle": g.iris[0], "transition": g.iris[1]} for g in gaps if g.kind == TRANSITION]
    policies = [
        {"policy": g.iris[0], "target": _or_none(g.iris[1]), "assignee": _or_none(g.iris[2])}
        for g in gaps
        if g.kind == POLICY
    ]
    return {
        "paths": paths,
        "transitions": transitions,
        "policies": policies,
        "counts": {"paths": len(paths), "transitions": len(transitions), "policies": len(policies)},
    }


def _or_none(value: str) -> str | None:
    return None if value == ABSENT else value


def summary(gaps: list[Gap]) -> str:
    """``N unexercised path(s), M unfired transition(s), K permission(s) without a deny test``."""
    count = {kind: sum(g.kind == kind for g in gaps) for kind in KINDS}
    return (
        f"{count[PATH]} unexercised path(s), {count[TRANSITION]} unfired transition(s), "
        f"{count[POLICY]} permission(s) without a deny test"
    )


__all__ = ["Gap", "coverage_report", "path_gaps", "summary", "to_json"]

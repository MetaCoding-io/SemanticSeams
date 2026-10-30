"""DMN decision tables read from the payload XML (lxml only).

Elements are matched on their local names, so any DMN namespace version
reads the same. ``parse_dmn`` returns every decision of a file keyed by
decision id; ``decision_table`` returns one. A decision without a
``decisionTable``, or a rule whose entries do not line up with the table's
inputs and outputs, raises ``ResolutionError`` naming the decision or rule
and the DMN element that failed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._xml import elements, localname
from .errors import ResolutionError

DEFAULT_HIT_POLICY = "UNIQUE"  # DMN 1.3, 8.2.11: hitPolicy defaults to UNIQUE


@dataclass(frozen=True)
class TableInput:
    """A decision-table input: its label and the inputExpression text."""

    id: str
    label: str | None
    expression: str
    type_ref: str | None


@dataclass(frozen=True)
class TableOutput:
    """A decision-table output column."""

    id: str
    label: str | None
    name: str | None
    type_ref: str | None


@dataclass(frozen=True)
class Rule:
    """A rule: one inputEntry text per input, one outputEntry text per output."""

    id: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    description: str | None


@dataclass(frozen=True)
class DecisionTable:
    """The decisionTable of a DMN decision."""

    decision_id: str
    decision_name: str | None
    table_id: str | None
    hit_policy: str
    aggregation: str | None
    inputs: tuple[TableInput, ...]
    outputs: tuple[TableOutput, ...]
    rules: tuple[Rule, ...]


def _children(el: Any, name: str) -> list[Any]:
    return [c for c in el if localname(c.tag) == name]


def _child(el: Any, name: str) -> Any | None:
    found = _children(el, name)
    return found[0] if found else None


def _text(el: Any | None) -> str | None:
    """The stripped text of el's ``text`` child (None when it has none)."""
    if el is None:
        return None
    text = _child(el, "text")
    return (text.text or "").strip() if text is not None else None


def _rule(el: Any, path: Path, n_inputs: int, n_outputs: int) -> Rule:
    rule_id = str(el.get("id") or "")
    subject = f"{path.name}#{rule_id}"
    inputs = tuple(_text(e) or "" for e in _children(el, "inputEntry"))
    outputs = tuple(_text(e) or "" for e in _children(el, "outputEntry"))
    if len(inputs) != n_inputs:
        raise ResolutionError(
            subject, "dmn:inputEntry", f"rule has {len(inputs)} inputEntry, the table has {n_inputs} inputs"
        )
    if len(outputs) != n_outputs:
        raise ResolutionError(
            subject, "dmn:outputEntry", f"rule has {len(outputs)} outputEntry, the table has {n_outputs} outputs"
        )
    description = _child(el, "description")
    return Rule(
        id=rule_id,
        inputs=inputs,
        outputs=outputs,
        description=(description.text or "").strip() if description is not None else None,
    )


def _table(decision: Any, path: Path) -> DecisionTable:
    decision_id = str(decision.get("id") or "")
    table = _child(decision, "decisionTable")
    if table is None:
        raise ResolutionError(f"{path.name}#{decision_id}", "dmn:decisionTable", "decision has no decision table")
    inputs: list[TableInput] = []
    for el in _children(table, "input"):
        expr = _child(el, "inputExpression")
        inputs.append(
            TableInput(
                id=str(el.get("id") or ""),
                label=el.get("label"),
                expression=_text(expr) or "",
                type_ref=expr.get("typeRef") if expr is not None else None,
            )
        )
    outputs = [
        TableOutput(id=str(el.get("id") or ""), label=el.get("label"), name=el.get("name"), type_ref=el.get("typeRef"))
        for el in _children(table, "output")
    ]
    rules = [_rule(el, path, len(inputs), len(outputs)) for el in _children(table, "rule")]
    return DecisionTable(
        decision_id=decision_id,
        decision_name=decision.get("name"),
        table_id=table.get("id"),
        hit_policy=table.get("hitPolicy") or DEFAULT_HIT_POLICY,
        aggregation=table.get("aggregation"),
        inputs=tuple(inputs),
        outputs=tuple(outputs),
        rules=tuple(rules),
    )


def parse_dmn(path: str | os.PathLike[str]) -> dict[str, DecisionTable]:
    """Every decision's table in the DMN file, keyed by decision id in document order."""
    p = Path(path)
    return {str(el.get("id")): _table(el, p) for el in elements(p) if localname(el.tag) == "decision"}


def decision_table(path: str | os.PathLike[str], decision_id: str) -> DecisionTable:
    """The table of decision ``decision_id`` in the DMN file."""
    tables = parse_dmn(path)
    if decision_id not in tables:
        raise ResolutionError(
            f"{Path(path).name}#{decision_id}", "dmn:decision", f"not among decision ids {list(tables)}"
        )
    return tables[decision_id]

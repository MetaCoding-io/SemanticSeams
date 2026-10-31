"""``model.scenarios`` and ``model.decision_examples``: what a model says it should do (ADR-0014).

A ``Scenario`` is one run of a process: who starts it with which values,
which user tasks named parties complete in order and with which form
values, and the lifecycle state or BPMN end event the run must reach. A
``DecisionExample`` is a decision's inputs and the outputs its DMN table
must return. Shape examples are read from the shape
(``Shape.valid_examples`` / ``Shape.invalid_examples``).

Givens are sorted by field IRI, steps keep their RDF list order and
expected outputs are sorted by variable, so a reader of these views gets
the same order every time (principle 6). A missing or ambiguous fact the
``seamsh:ScenarioShape``, ``GivenShape``, ``DecisionExampleShape`` and
``ExpectOutputShape`` shapes flag raises ``ResolutionError`` naming the
subject and predicate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rdflib import Literal, URIRef
from rdflib.collection import Collection
from rdflib.term import Node

from ..errors import ResolutionError
from ..namespaces import DEC, VERIFY
from ._base import Element, element_type, one_value

if TYPE_CHECKING:
    from .decisions import Decision
    from .lifecycles import State
    from .processes import Process, ProcessElement


@dataclass(frozen=True)
class Given:
    """One verify:given: the ``sh:path`` it fills and its literal value."""

    field: URIRef
    value: Literal


@dataclass(frozen=True)
class ExpectedOutput:
    """One verify:expectOutput: a DMN output ``dec:variable`` and the literal it must equal."""

    variable: str
    value: Literal


@dataclass(frozen=True)
class Step:
    """One member of a scenario's verify:step list: the user task, who completes it and the form values."""

    task: ProcessElement
    actor: URIRef
    givens: tuple[Given, ...]


def _iri(subject: Node, predicate: URIRef, value: Node) -> URIRef:
    if not isinstance(value, URIRef):
        raise ResolutionError(subject, predicate, f"expected an IRI, found {value!r}")
    return value


def _givens(element: Element, node: Node) -> tuple[Given, ...]:
    """The verify:given values of ``node``, by field IRI; a field given twice raises."""
    ds = element.views.ds
    out: dict[URIRef, Given] = {}
    for given in ds.objects(node, VERIFY.given):
        field = _iri(given, VERIFY.field, one_value(ds, given, VERIFY.field))
        value = one_value(ds, given, VERIFY.value)
        if not isinstance(value, Literal):
            raise ResolutionError(given, VERIFY.value, f"expected a literal, found {value!r}")
        if field in out:
            raise ResolutionError(node, VERIFY.given, f"{field} is given twice")
        out[field] = Given(field, value)
    return tuple(out[f] for f in sorted(out, key=str))


@element_type(VERIFY.Scenario)
@dataclass(frozen=True, eq=False)
class Scenario(Element):
    """A verify:Scenario."""

    @property
    def process(self) -> Process:
        """The proc:Process it runs (verify:process)."""
        from .processes import Process

        iri = _iri(self.iri, VERIFY.process, self._one_value(VERIFY.process))
        return self.views.intern(Process, iri)

    @property
    def actor(self) -> URIRef:
        """The odrl:Party who starts the process (verify:actor)."""
        return _iri(self.iri, VERIFY.actor, self._one_value(VERIFY.actor))

    @property
    def givens(self) -> tuple[Given, ...]:
        """The start values, by field IRI."""
        return _givens(self, self.iri)

    @property
    def steps(self) -> tuple[Step, ...]:
        """The verify:step list, in list order (no list: no steps)."""
        from .processes import ProcessElement

        head = self._optional_value(VERIFY.step)
        if head is None:
            return ()
        ds = self.views.ds
        steps: list[Step] = []
        for node in Collection(ds, head):
            task = _iri(node, VERIFY.task, one_value(ds, node, VERIFY.task))
            actor = _iri(node, VERIFY.actor, one_value(ds, node, VERIFY.actor))
            steps.append(Step(self.views.intern(ProcessElement, task), actor, _givens(self, node)))
        return tuple(steps)

    @property
    def expect_state(self) -> State | None:
        """The state:State the entity must end in (verify:expectState), or None."""
        from .lifecycles import State

        value = self._optional_value(VERIFY.expectState)
        return None if value is None else self.views.intern(State, _iri(self.iri, VERIFY.expectState, value))

    @property
    def expect_end_event(self) -> URIRef | None:
        """The BPMN end event the run must finish on (verify:expectEndEvent), or None."""
        value = self._optional_value(VERIFY.expectEndEvent)
        return None if value is None else _iri(self.iri, VERIFY.expectEndEvent, value)


@element_type(VERIFY.DecisionExample)
@dataclass(frozen=True, eq=False)
class DecisionExample(Element):
    """A verify:DecisionExample."""

    @property
    def decision(self) -> Decision:
        """The dec:Decision it evaluates (verify:decision)."""
        from .decisions import Decision

        iri = _iri(self.iri, VERIFY.decision, self._one_value(VERIFY.decision))
        return self.views.intern(Decision, iri)

    @property
    def givens(self) -> tuple[Given, ...]:
        """The decision's input values, by field IRI."""
        return _givens(self, self.iri)

    @property
    def expected(self) -> tuple[ExpectedOutput, ...]:
        """Each verify:expectOutput, by variable."""
        ds = self.views.ds
        out: list[ExpectedOutput] = []
        for node in ds.objects(self.iri, VERIFY.expectOutput):
            variable = one_value(ds, node, DEC.variable)
            value = one_value(ds, node, VERIFY.value)
            if not isinstance(value, Literal):
                raise ResolutionError(node, VERIFY.value, f"expected a literal, found {value!r}")
            out.append(ExpectedOutput(str(variable), value))
        return tuple(sorted(out, key=lambda o: o.variable))


__all__ = ["DecisionExample", "ExpectedOutput", "Given", "Scenario", "Step"]

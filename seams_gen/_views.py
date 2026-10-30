"""The bridge from seams views to ``GeneratorError`` (M010/S05, D036).

Generators read the model only through seams views. A view says "missing or
ambiguous" with ``ResolutionError(subject, predicate)``; a generator says it
with ``GeneratorError(subject, predicate, detail)``. ``only`` and
``optional`` pick from a ``Many`` with the generators' wording ("expected
exactly one, found none", "expected at most one, found a, b"), ``required``
does the same for a single-valued view property that answered None, and
``view_errors`` turns a ``ResolutionError`` a view property raises into the
``GeneratorError`` naming the same subject and predicate.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from seams import Many, Model, ResolutionError

from . import GeneratorError


def _found(items: Many) -> str:
    return "none" if not items else ", ".join(str(i) for i in items.iris())


def only[T](many: Many[T], detail: str = "") -> T:
    """The single item; ``GeneratorError(many.subject, many.predicate)`` otherwise."""
    if len(many) != 1:
        text = f"expected exactly one, found {_found(many)}"
        raise GeneratorError(many.subject, many.predicate, f"{detail}: {text}" if detail else text)
    return many[0]


def optional[T](many: Many[T]) -> T | None:
    """None or the single item; several raise ``GeneratorError(many.subject, many.predicate)``."""
    if len(many) > 1:
        raise GeneratorError(many.subject, many.predicate, f"expected at most one, found {_found(many)}")
    return many[0] if many else None


def required[T](value: T | None, subject: object, predicate: object, detail: str = "") -> T:
    """``value``, or ``GeneratorError(subject, predicate)`` when the view answered None."""
    if value is None:
        text = "expected exactly one, found none"
        raise GeneratorError(subject, predicate, f"{detail}: {text}" if detail else text)
    return value


def label(model: Model, iri: object) -> str:
    """The single rdfs:label of ``iri`` (``Model.label(strict=True)``)."""
    with view_errors():
        return model.label(iri, strict=True)


@contextmanager
def view_errors() -> Iterator[None]:
    """Re-raise a view's ``ResolutionError`` as ``GeneratorError`` on the same subject and predicate."""
    try:
        yield
    except ResolutionError as err:
        raise GeneratorError(err.subject, err.predicate, err.detail) from err

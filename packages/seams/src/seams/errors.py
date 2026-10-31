"""Typed errors.

Every error names the graph terms it is about (as IRI strings), carries the
HTTP status a route should answer with, and serialises to a JSON-safe dict via
``to_dict()`` so a handler can put it straight into a response body.
"""

from __future__ import annotations

from typing import Any, cast


def _jsonable(value: Any) -> Any:
    """IRIs, literals, paths and other terms become strings; containers recurse."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        items = cast(dict[Any, Any], value).items()
        return {str(k): _jsonable(v) for k, v in items}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in cast("list[Any]", value)]
    return str(value)


class SeamsError(Exception):
    """Base class for every seams error."""

    http_status = 500

    def _fields(self) -> dict[str, Any]:
        return {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": type(self).__name__,
            "message": str(self),
            "http_status": self.http_status,
            **_jsonable(self._fields()),
        }


class ResolutionError(SeamsError, LookupError):
    """A graph hop is missing (or points nowhere)."""

    http_status = 500

    def __init__(self, subject: object, predicate: object, detail: str = "") -> None:
        self.subject = str(subject)
        self.predicate = str(predicate)
        self.detail = detail
        msg = f"cannot resolve {self.subject}: missing {self.predicate}"
        super().__init__(f"{msg} ({detail})" if detail else msg)

    def _fields(self) -> dict[str, Any]:
        return {"subject": self.subject, "predicate": self.predicate, "detail": self.detail}

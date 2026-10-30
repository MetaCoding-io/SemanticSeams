"""Load a seams model from a TriG file or a directory of TriG files.

``load`` returns a ``Model``: the merged rdflib Dataset plus the model hash and
the ``seam:renderPayload`` files (BPMN, DMN) the model names. Loading needs
only rdflib; nothing here executes the model.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

from rdflib import RDFS, Dataset, URIRef
from rdflib.term import Node

from .errors import ResolutionError
from .namespaces import SEAM, local_name

if TYPE_CHECKING:
    from .sparql import Row

    # Imported lazily at run time: the views import this module.
    from .views import (
        Architecture,
        Channel,
        Decision,
        Interfaces,
        Lifecycles,
        Many,
        Operation,
        Policy,
        Processes,
        Shape,
        Views,
    )

#: Environment variable naming the model ``load()`` reads when given no path.
MODEL_ENV = "SEAMS_MODEL"


def payload_path(payload_iri: object, base_dir: str | os.PathLike[str]) -> Path:
    """file: IRIs map to their path; anything else resolves its last path
    segment against the model's base directory."""
    parts = urlsplit(str(payload_iri))
    if parts.scheme == "file":
        return Path(unquote(parts.path))
    return Path(base_dir) / unquote(parts.path).rsplit("/", 1)[-1]


def _relpath(path: Path, base_dir: Path) -> str:
    return Path(os.path.relpath(path.resolve(), base_dir.resolve())).as_posix()


def _frame(rel: str, data: bytes) -> bytes:
    """Relative path, NUL, decimal length, bytes."""
    return rel.encode("utf-8") + b"\0" + str(len(data)).encode("ascii") + data


class Model:
    """A loaded seams model.

    ``path`` is the resolved TriG file or directory, ``base_dir`` the directory
    payloads resolve against (the file's parent, or the directory itself),
    ``files`` the TriG files parsed and ``ds`` the merged Dataset.
    """

    def __init__(self, path: str | os.PathLike[str], dataset: Dataset | None = None) -> None:
        resolved = Path(path).resolve()
        self.path: Path = resolved
        if resolved.is_dir():
            self.base_dir: Path = resolved
            self.is_directory = True
            self.files: tuple[Path, ...] = tuple(sorted(resolved.glob("*.trig"), key=lambda p: p.name))
            if not self.files:
                raise FileNotFoundError(f"no *.trig files in model directory {resolved}")
        else:
            self.base_dir = resolved.parent
            self.is_directory = False
            self.files = (resolved,)
        if dataset is None:
            dataset = Dataset(default_union=True)
            for trig in self.files:
                dataset.parse(str(trig), format="trig")
        self.ds: Dataset = dataset
        # Per-instance cache (never a module-level id()-keyed dict; see MEM010).
        self._hash: str | None = None
        self._views: Views | None = None

    @property
    def hash(self) -> str:
        """``"sha256:<hex>"`` over the model and its payloads.

        A single file hashes its TriG bytes, then each payload framed as
        relative path, NUL, length, bytes (sorted by relative path). A
        directory frames each TriG file the same way (relative path is the
        file name, sorted by name), then the payloads. Editing or renaming any
        file changes the hash.
        """
        if self._hash is None:
            h = hashlib.sha256()
            if self.is_directory:
                for trig in self.files:
                    h.update(_frame(_relpath(trig, self.base_dir), trig.read_bytes()))
            else:
                h.update(self.path.read_bytes())
            for rel, path in self.payloads():
                h.update(_frame(rel, path.read_bytes()))
            self._hash = "sha256:" + h.hexdigest()
        return self._hash

    @property
    def subject(self) -> URIRef:
        """IRI used as the subject of model-level resolution errors."""
        return URIRef(self.path.as_uri())

    def curie(self, term: object) -> URIRef:
        """Expand ":x" (or any prefix bound in the TriG) to an IRI; full IRIs
        pass through unchanged."""
        if isinstance(term, URIRef):
            return term
        text = str(term)
        if "://" in text or text.startswith("urn:"):
            return URIRef(text)
        prefix, sep, local = text.partition(":")
        if not sep:
            raise ValueError(f"not a CURIE or IRI: {text!r}")
        ns = dict(self.ds.namespaces()).get(prefix)
        if ns is None:
            raise ResolutionError(self.subject, f"@prefix {prefix}:", f"cannot expand {text!r}")
        return URIRef(str(ns) + local)

    def label(self, iri: object) -> str:
        """The rdfs:label of ``iri``, or its local name when it has none."""
        value = self.ds.value(URIRef(str(iri)), RDFS.label)
        return str(value) if value is not None else local_name(iri)

    def payloads(self) -> list[tuple[str, Path]]:
        """(posix path relative to base_dir, absolute path) for every
        seam:renderPayload, sorted by relative path. A payload that does not
        exist raises ResolutionError naming the model that renders it."""
        seen: dict[str, Path] = {}
        for model, payload in self.ds.subject_objects(SEAM.renderPayload):
            path = payload_path(payload, self.base_dir)
            if not path.is_file():
                raise ResolutionError(model, SEAM.renderPayload, f"payload {path} not found")
            seen[_relpath(path, self.base_dir)] = path
        return sorted(seen.items())

    # ── typed views (seams.views) ──

    @property
    def views(self) -> Views:
        """The per-model view registry every view below shares."""
        if self._views is None:
            from .views import Views

            self._views = Views(self)
        return self._views

    @property
    def architecture(self) -> Architecture:
        """Systems, containers, deployment nodes and environments."""
        from . import views

        return views.architecture(self)

    @property
    def operations(self) -> Many[Operation]:
        """Every hydra:Operation, by IRI."""
        from . import views

        return views.operations(self)

    @property
    def channels(self) -> Many[Channel]:
        """Every comm:Channel, by IRI."""
        from . import views

        return views.channels(self)

    @property
    def shapes(self) -> Many[Shape]:
        """Every sh:NodeShape, by IRI."""
        from . import views

        return views.shapes(self)

    @property
    def lifecycles(self) -> Lifecycles:
        """Every state:StateMachine, by IRI."""
        from . import views

        return views.lifecycles(self)

    @property
    def policies(self) -> Many[Policy]:
        """Every odrl:Policy, by IRI."""
        from . import views

        return views.policies(self)

    @property
    def interfaces(self) -> Interfaces:
        """Interaction models, pages (landmark and served), components and events."""
        from . import views

        return views.interfaces(self)

    @property
    def processes(self) -> Processes:
        """Every proc:Process, by IRI, and its BPMN elements."""
        from . import views

        return views.processes(self)

    @property
    def decisions(self) -> Many[Decision]:
        """Every bound dec:Decision, by IRI."""
        from . import views

        return views.decisions(self)

    # ── SPARQL (seams.sparql) ──

    def sparql(self, query: str, /, **bindings: Any) -> list[Row]:
        """Rows of a read-only SELECT with the project prefixes bound. Each
        keyword binds that variable; a str with ':' is expanded via curie().
        Rows follow the query's ORDER BY, else sort by their str values."""
        from .sparql import rows

        return rows(self, query, **bindings)

    def question(self, name: str, /, **bindings: Any) -> list[Row]:
        """Run the bundled canned question ``name`` (see
        ``seams.sparql.question_names()``) like ``sparql``."""
        from .sparql import load_question, rows

        return rows(self, load_question(name), **bindings)

    def payload_path(self, model_iri: object) -> Path:
        """The existing payload file ``model_iri`` renders via seam:renderPayload."""
        model = self.curie(model_iri)
        payload: Node | None = self.ds.value(model, SEAM.renderPayload)
        if payload is None:
            raise ResolutionError(model, SEAM.renderPayload)
        path = payload_path(payload, self.base_dir)
        if not path.is_file():
            raise ResolutionError(model, SEAM.renderPayload, f"payload {path} not found")
        return path


def load(path: str | os.PathLike[str] | None = None) -> Model:
    """Load a model from a TriG file or a directory of ``*.trig`` files.

    A directory loads every ``*.trig`` directly inside it (non-recursive,
    sorted by name) into one Dataset. Without ``path``, the ``SEAMS_MODEL``
    environment variable names the model; an explicit path always wins.
    """
    if path is None:
        env = os.environ.get(MODEL_ENV, "")
        if not env:
            raise ValueError(f"no model path given and {MODEL_ENV} is not set")
        path = env
    return Model(path)


def model_hash(path: str | os.PathLike[str]) -> str:
    """The hash of the model at ``path`` (see ``Model.hash``)."""
    return Model(path).hash

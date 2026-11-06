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
from .ontologies import DatasetOntology, ImportStatus, VendoredOntology
from .ontologies import check_imports as _check_imports
from .ontologies import dataset_imports as _dataset_imports
from .ontologies import import_statuses as _import_statuses
from .vocabularies import MigrationStep
from .vocabularies import check_versions as _check_versions

if TYPE_CHECKING:
    from .sparql import Row

    # Imported lazily at run time: the views import this module.
    from .views import (
        Aggregate,
        Architecture,
        Channel,
        Decision,
        DecisionExample,
        Interfaces,
        Lifecycles,
        Many,
        Ontology,
        Operation,
        Policy,
        Processes,
        Scenario,
        Shape,
        Views,
    )

#: Environment variable naming the model ``load()`` reads when given no path.
MODEL_ENV = "SEAMS_MODEL"

#: The repository's ontology/ (vocabularies, shapes, migrations) when ``seams``
#: runs from the workspace (D060). An installed copy has none next to it.
DEFAULT_ONTOLOGY_DIR = Path(__file__).resolve().parents[4] / "ontology"


def model_dir(path: str | os.PathLike[str]) -> Path:
    """The resolved directory a model at ``path`` resolves its payloads and
    handlers against: ``path`` itself when it is a directory of TriG files,
    else the TriG file's parent (``Model.base_dir`` without loading)."""
    resolved = Path(path).resolve()
    return resolved if resolved.is_dir() else resolved.parent


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

    ``ds`` has passed the ADR-0021 vocabulary version check against
    ``ontology_dir`` and holds the migrated data when the model targets an
    older vocabulary; ``migrations`` lists the steps applied, sorted. Without
    ``ontology_dir`` the repository's ``ontology/`` is used, and the check is
    skipped when there is none (an installed ``seams`` outside the
    workspace). ``check_versions=False`` keeps the model as written.

    The ``owl:imports`` of every ``seam:Ontology`` model are resolved against
    the other ontology models of the Dataset by ``owl:versionIRI`` (ADR-0030
    section 4), then ``ontology_dir/vendor`` (ADR-0022, ``seams.ontologies``):
    ``dataset_imports`` lists the Dataset's ontologies they name and
    ``imports`` the vendored ones, each sorted by version IRI, and the first
    import that does not resolve raises ``ResolutionError(<ontology>,
    owl:imports)``. ``check_imports=False`` loads without the check, and
    ``import_statuses`` reports each import's status instead. ``ontology_dir``
    is the directory both checks used, or None when there is none.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        dataset: Dataset | None = None,
        *,
        ontology_dir: str | os.PathLike[str] | None = None,
        check_versions: bool = True,
        check_imports: bool = True,
    ) -> None:
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
        vocabularies = Path(ontology_dir) if ontology_dir is not None else DEFAULT_ONTOLOGY_DIR
        self.ontology_dir: Path | None = vocabularies.resolve() if vocabularies.is_dir() else None
        if ontology_dir is not None and self.ontology_dir is None and (check_versions or check_imports):
            raise FileNotFoundError(f"no ontology directory {vocabularies}")
        self.migrations: tuple[MigrationStep, ...] = ()
        self.imports: tuple[VendoredOntology, ...] = ()
        self.dataset_imports: tuple[DatasetOntology, ...] = ()
        if self.ontology_dir is not None:
            if check_versions:
                self.migrations = _check_versions(dataset, self.ontology_dir)
            if check_imports:
                self.imports = _check_imports(dataset, self.ontology_dir)
                self.dataset_imports = _dataset_imports(_import_statuses(dataset, self.ontology_dir))
        self.ds: Dataset = dataset
        # Per-instance cache (never a module-level id()-keyed dict; see MEM010).
        self._hash: str | None = None
        self._views: Views | None = None
        self._ns: list[tuple[str, str]] | None = None
        self._import_statuses: tuple[ImportStatus, ...] | None = None

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

    def compact(self, term: object, *, whole: bool = False) -> str:
        """``prefix:local`` for the longest bound namespace ``term`` starts
        with (ties by prefix), the inverse partner of ``curie``. The local part
        is the IRI's last fragment or segment (a BPMN element ``<model#id>``
        shows as ``:id``); ``whole=True`` keeps everything after the namespace
        (``:approval_bpmn#approve_expense``), which ``curie`` expands back.
        ``<iri>`` when no namespace matches (the bare IRI with ``whole``)."""
        text = str(term)
        for ns, prefix in self._namespaces():
            if text.startswith(ns):
                return f"{prefix}:{text[len(ns) :]}" if whole else f"{prefix}:{local_name(text)}"
        return text if whole else f"<{text}>"

    def _namespaces(self) -> list[tuple[str, str]]:
        if self._ns is None:
            self._ns = sorted(
                ((str(ns), prefix) for prefix, ns in self.ds.namespaces()), key=lambda p: (-len(p[0]), p[1])
            )
        return self._ns

    def label(self, iri: object, *, strict: bool = False) -> str:
        """The rdfs:label of ``iri``, or its local name when it has none.
        ``strict=True`` requires exactly one rdfs:label and raises
        ``ResolutionError(iri, rdfs:label)`` otherwise (the generators' rule)."""
        node = URIRef(str(iri))
        if strict:
            values = sorted(set(self.ds.objects(node, RDFS.label)), key=str)
            if len(values) != 1:
                found = "none" if not values else ", ".join(str(v) for v in values)
                raise ResolutionError(node, RDFS.label, f"expected exactly one, found {found}")
            return str(values[0])
        value = self.ds.value(node, RDFS.label)
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

    @property
    def import_statuses(self) -> tuple[ImportStatus, ...]:
        """Every ontology import and whether it resolves, sorted by (ontology,
        import); read even when the model was loaded with ``check_imports=False``."""
        if self._import_statuses is None:
            self._import_statuses = _import_statuses(self.ds, self.ontology_dir)
        return self._import_statuses

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
    def ontologies(self) -> Many[Ontology]:
        """Every seam:Ontology model (ADR-0022), by IRI."""
        from . import views

        return views.ontologies(self)

    @property
    def aggregates(self) -> Many[Aggregate]:
        """Every aggregate that names seam:aggregateMember shapes (ADR-0035), by IRI."""
        from . import views

        return views.aggregates(self)

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

    @property
    def scenarios(self) -> Many[Scenario]:
        """Every verify:Scenario (ADR-0014), by IRI."""
        from . import views

        return views.scenarios(self)

    @property
    def decision_examples(self) -> Many[DecisionExample]:
        """Every verify:DecisionExample (ADR-0014), by IRI."""
        from . import views

        return views.decision_examples(self)

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


def load(
    path: str | os.PathLike[str] | None = None,
    *,
    ontology_dir: str | os.PathLike[str] | None = None,
    check_versions: bool = True,
    check_imports: bool = True,
) -> Model:
    """Load a model from a TriG file or a directory of ``*.trig`` files.

    A directory loads every ``*.trig`` directly inside it (non-recursive,
    sorted by name) into one Dataset. Without ``path``, the ``SEAMS_MODEL``
    environment variable names the model; an explicit path always wins.

    The vocabulary versions the model declares are checked against
    ``ontology_dir`` (default: the repository's ``ontology/``) and an older
    model is migrated in memory (ADR-0021), and its ontology imports are
    resolved against the vendored ontologies (ADR-0022); see ``Model``.
    """
    if path is None:
        env = os.environ.get(MODEL_ENV, "")
        if not env:
            raise ValueError(f"no model path given and {MODEL_ENV} is not set")
        path = env
    return Model(path, ontology_dir=ontology_dir, check_versions=check_versions, check_imports=check_imports)


def model_hash(path: str | os.PathLike[str]) -> str:
    """The hash of the model at ``path`` (see ``Model.hash``)."""
    return Model(path, check_versions=False, check_imports=False).hash

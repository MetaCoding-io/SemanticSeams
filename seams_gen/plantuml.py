"""The PlantUML export of the derived views (M033/S01, backlog X9, ADR-0044).

``extract_plantuml(model)`` gathers, sorted by IRI, the as-designed sequence
diagrams ``seams_gen.sequence.derive`` draws for every ifml:Event that
seam:triggers a process, and the event storm ``seams_gen.storm.derive`` reads
for every proc:Process. It derives nothing itself: ``render_plantuml`` only
prints those dataclasses, from their Mermaid-free fields, as PlantUML:

- ``sequence/<diagram file stem>.puml``: a sequence diagram with the
  diagram's event and path, one ``' gap:`` comment line per gap, its actors
  and participants (``actor``/``participant "<label>" as <id>``), then each
  message in order: a call ``->``, a reply ``-->`` or a ``note over``;
- ``storm/<process local name>.puml``: an activity diagram of the storm's
  timeline, from ``start`` to ``stop``: one activity per step, with a note
  holding the step's entries (``<kind>: <text>``), then a legend of the read
  models. Its gaps are ``' gap:`` comment lines too.

Each file runs from ``@startuml`` to ``@enduml``, with a header comment and
the IRI it was derived from, and carries no model hash, timestamp or path.
Labels are printed as they are, with ``"`` turned into ``'`` inside quoted
names and the storm's Markdown backticks dropped. Two diagrams with one file
name (an event or process local name shared across namespaces) raise
``GeneratorError``; a fault of either deriver is passed on as it is.
"""

from __future__ import annotations

from dataclasses import dataclass

from rdflib import RDF, URIRef
from seams import Model, local_name

from . import GeneratorError
from ._views import view_errors
from .protocol import Files, Sources
from .sequence import SequenceDiagram, file_name
from .sequence import derive as derive_sequence
from .storm import Storm
from .storm import derive as derive_storm

HEADER = (
    "' {what}, written by the seams_gen plantuml generator (ADR-0044). "
    "Regenerate it with `seams generate`; do not edit it."
)


@dataclass(frozen=True)
class PlantUmlModel:
    """The derived diagrams the export prints: the sequence diagrams of each
    triggering event and the storm of each process, both by IRI."""

    sequences: tuple[SequenceDiagram, ...]
    storms: tuple[Storm, ...]


def sequence_file(diagram: SequenceDiagram) -> str:
    """``sequence/<file_name stem>.puml``."""
    return f"sequence/{file_name(diagram).removesuffix('.mmd')}.puml"


def storm_file(storm: Storm) -> str:
    """``storm/<process local name>.puml``."""
    return _storm_file(storm.process)


def _storm_file(process: URIRef) -> str:
    return f"storm/{local_name(process)}.puml"


def _unique_files(model: Model, files: list[tuple[str, URIRef]]) -> None:
    """Two diagrams with one file name would overwrite each other."""
    seen: dict[str, URIRef] = {}
    for name, iri in files:
        if name in seen and seen[name] != iri:
            detail = (
                f"{model.compact(seen[name])} and {model.compact(iri)} both write {name}; a PlantUML "
                "file is named after the local name"
            )
            raise GeneratorError(iri, RDF.type, detail)
        seen[name] = iri


def extract_plantuml(model: Model) -> PlantUmlModel:
    """Every derived sequence diagram and storm of ``model``."""
    with view_errors():
        events = sorted((e for e in model.interfaces.events() if list(e.triggers_all)), key=lambda e: str(e.iri))
        processes = sorted(model.processes, key=lambda p: str(p.iri))
    _unique_files(model, [(_storm_file(p.iri), p.iri) for p in processes])
    sequences = tuple(d for e in events for d in derive_sequence(model, str(e.iri)))
    _unique_files(model, [(sequence_file(d), d.event) for d in sequences])
    return PlantUmlModel(sequences, tuple(derive_storm(model, p) for p in processes))


def _quoted(label: str) -> str:
    return '"' + label.replace('"', "'") + '"'


def _plain(text: str) -> str:
    """A storm text without its Markdown code marks, on one line."""
    return text.replace("`", "").replace("\n", " ")


def sequence_text(diagram: SequenceDiagram) -> str:
    """The diagram as PlantUML, with a trailing newline."""
    source = "executed from" if diagram.executed else "derived from"
    lines = ["@startuml", HEADER.format(what="Sequence diagram"), f"' {source} {diagram.event}"]
    lines.append(f"' path: {', '.join(diagram.path) if diagram.path else 'single'}")
    if diagram.run is not None:
        lines.append(f"' run: {diagram.run}")
    lines += [f"' gap: {g}" for g in diagram.gaps]
    for p in diagram.participants:
        lines.append(f"{'actor' if p.actor else 'participant'} {_quoted(p.label)} as {p.id}")
    for m in diagram.messages:
        if m.kind == "note":
            lines.append(f"note over {m.sender} : {m.text}")
        else:
            lines.append(f"{m.sender} {'-->' if m.kind == 'reply' else '->'} {m.receiver} : {m.text}")
    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def storm_text(storm: Storm) -> str:
    """The storm as a PlantUML activity diagram, with a trailing newline."""
    lines = ["@startuml", HEADER.format(what="Event storm"), f"' derived from {storm.process}"]
    lines += [f"' gap: {g}" for g in storm.gaps]
    lines += [f"title Event storm: {storm.label}", "start"]
    if not storm.steps:
        lines.append("' No step of the process has a fact to show.")
    entries = storm.entries()
    for step in storm.steps:
        lines.append(f":{step.index}. {_plain(step.name)} ({local_name(step.iri)});")
        notes = [f"  {e.kind}: {_plain(e.text)}" for e in entries if e.step == step.index]
        if notes:
            lines += ["note right", *notes, "end note"]
    lines.append("stop")
    if storm.read_models:
        lines += ["legend right", "  Read models"]
        lines += [f"  - {_plain(e.text)}" for e in storm.read_models]
        lines.append("endlegend")
    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def render_plantuml(view: PlantUmlModel) -> Files:
    """{``sequence/<stem>.puml`` and ``storm/<process>.puml``: text}."""
    files = {sequence_file(d): sequence_text(d) for d in view.sequences}
    files.update({storm_file(s): storm_text(s) for s in view.storms})
    return dict(sorted(files.items()))


def plantuml_sources(model: Model) -> Sources:
    """{file: full IRIs}: a sequence diagram's event, lifelines and message
    terms; a storm's process, steps, entries and read models."""
    view = extract_plantuml(model)
    found: dict[str, set[str]] = {}
    for d in view.sequences:
        terms = {d.event, *(p.iri for p in d.participants), *(t for m in d.messages for t in m.terms)}
        found[sequence_file(d)] = {str(t) for t in terms}
    for s in view.storms:
        terms = {s.process, *(st.iri for st in s.steps), *(e.iri for e in (*s.entries(), *s.read_models))}
        found[storm_file(s)] = {str(t) for t in terms}
    return {name: tuple(sorted(iris)) for name, iris in sorted(found.items())}


__all__ = [
    "PlantUmlModel",
    "extract_plantuml",
    "plantuml_sources",
    "render_plantuml",
    "sequence_file",
    "sequence_text",
    "storm_file",
    "storm_text",
]

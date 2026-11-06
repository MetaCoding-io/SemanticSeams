"""Domain profiles (ADR-0018, ADR-0033 section 5).

A model attaches to a profile with ``seam:conformsTo <P>`` in its seams graph. The
profile is a package ``profiles/<name>/profile.ttl`` in the model directory: the file
that states ``<P> a seam:Profile`` is the profile, found by scanning every
``profiles/*/profile.ttl`` in sorted path order. The IRI is the identity; the model
names no file.

``resolve_profile`` returns what the editor restricts itself to: the offered classes
(seam:offersClass), the previewed generators (seam:usesGenerator), the labels
(skos:prefLabel, else rdfs:label) and one shapes graph parsed from the
seam:profileShapes files. ``Profile.pills`` maps each pill shape (ADR-0033 section 4:
a sh:NodeShape of severity sh:Info with a label) to its label. Every value comes from
the profile graph. The profile is kept in its own graph and never merged into the
model dataset, so attaching one leaves the model hash and seams.lock unchanged. The
resolver reads and parses; it does not validate. ``seams check`` and the viewer each
run pyshacl with the shapes graph it returns.

A profile that cannot be resolved raises ``ResolutionError(subject, predicate,
detail)``; paths in the detail are relative to the model directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import rdflib
from rdflib import RDF, RDFS, SKOS, Namespace, URIRef
from rdflib.term import Node
from rdflib.util import guess_format

from .errors import ResolutionError
from .namespaces import SEAM

SH = Namespace("http://www.w3.org/ns/shacl#")


@dataclass(frozen=True)
class Profile:
    """A resolved domain profile: everything the editor and ``seams check`` read from it."""

    iri: URIRef
    classes: tuple[URIRef, ...]
    generators: tuple[str, ...]
    labels: dict[URIRef, str] = field(default_factory=lambda: dict[URIRef, str]())
    shapes: rdflib.Graph = field(default_factory=rdflib.Graph)
    graph: rdflib.Graph = field(default_factory=rdflib.Graph)
    pills: dict[URIRef, str] = field(default_factory=lambda: dict[URIRef, str]())


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _attachment(ds: rdflib.Dataset) -> tuple[URIRef, URIRef] | None:
    """The (model subject, profile IRI) the dataset's seam:conformsTo states."""
    pairs: list[tuple[Node, Node]] = sorted({(s, o) for s, _p, o, _g in ds.quads((None, SEAM.conformsTo, None, None))})
    if not pairs:
        return None
    subject = pairs[0][0]
    profiles = sorted({o for _s, o in pairs}, key=str)
    if len(profiles) > 1:
        raise ResolutionError(
            subject, SEAM.conformsTo, f"the model states more than one profile: {', '.join(map(str, profiles))}"
        )
    profile = profiles[0]
    if not isinstance(subject, URIRef) or not isinstance(profile, URIRef):
        raise ResolutionError(subject, SEAM.conformsTo, f"a profile is named by IRI, not {profile!r}")
    return subject, profile


def _find(subject: URIRef, iri: URIRef, model_dir: Path) -> tuple[Path, rdflib.Graph]:
    """The profile.ttl declaring ``iri`` under ``model_dir/profiles``, parsed."""
    found: list[tuple[Path, rdflib.Graph]] = []
    for path in sorted(model_dir.glob("profiles/*/profile.ttl")):
        graph = rdflib.Graph()
        try:
            graph.parse(path, format="turtle")
        except Exception as err:  # rdflib raises parser-specific exceptions
            raise ResolutionError(subject, SEAM.conformsTo, f"{_relative(path, model_dir)}: {err}") from err
        if (iri, RDF.type, SEAM.Profile) in graph:
            found.append((path, graph))
    if not found:
        raise ResolutionError(
            subject, SEAM.conformsTo, f"no profiles/*/profile.ttl in {model_dir.name}/ declares {iri} a seam:Profile"
        )
    if len(found) > 1:
        files = ", ".join(_relative(path, model_dir) for path, _g in found)
        raise ResolutionError(subject, SEAM.conformsTo, f"more than one profile.ttl declares {iri}: {files}")
    return found[0]


def _label(graph: rdflib.Graph, node: URIRef) -> str | None:
    for predicate in (SKOS.prefLabel, RDFS.label):
        values = sorted(str(o) for o in graph.objects(node, predicate))
        if values:
            return values[0]
    return None


def _shapes(iri: URIRef, graph: rdflib.Graph, profile_dir: Path, model_dir: Path) -> rdflib.Graph:
    shapes = rdflib.Graph()
    for name in sorted(str(o) for o in graph.objects(iri, SEAM.profileShapes)):
        path = profile_dir / name
        where = _relative(path, model_dir) if path.is_relative_to(model_dir) else name
        if not path.is_file():
            raise ResolutionError(iri, SEAM.profileShapes, f"{where}: no such file")
        try:
            shapes.parse(path, format=guess_format(str(path)) or "turtle")
        except Exception as err:  # rdflib raises parser-specific exceptions
            raise ResolutionError(iri, SEAM.profileShapes, f"{where}: {err}") from err
    return shapes


def _pills(shapes: rdflib.Graph) -> dict[URIRef, str]:
    """Each labelled sh:NodeShape of severity sh:Info (ADR-0033 section 4) and its label."""
    pills: dict[URIRef, str] = {}
    for shape in sorted(shapes.subjects(RDF.type, SH.NodeShape), key=str):
        if isinstance(shape, URIRef) and (shape, SH.severity, SH.Info) in shapes:
            label = _label(shapes, shape)
            if label is not None:
                pills[shape] = label
    return pills


def resolve_profile(ds: rdflib.Dataset, model_dir: Path) -> Profile | None:
    """The profile the model in ``ds`` conforms to, or None when it states none.

    ``model_dir`` is the directory of the loaded TriG file. No profile file is read
    when the model has no seam:conformsTo.
    """
    attachment = _attachment(ds)
    if attachment is None:
        return None
    subject, iri = attachment
    path, graph = _find(subject, iri, model_dir)
    classes = tuple(sorted(o for o in graph.objects(iri, SEAM.offersClass) if isinstance(o, URIRef)))
    labels = {cls: label for cls in classes if (label := _label(graph, cls)) is not None}
    shapes = _shapes(iri, graph, path.parent, model_dir)
    return Profile(
        iri=iri,
        classes=classes,
        generators=tuple(sorted({str(o) for o in graph.objects(iri, SEAM.usesGenerator)})),
        labels=labels,
        shapes=shapes,
        graph=graph,
        pills=_pills(shapes),
    )


__all__ = ["Profile", "resolve_profile"]

"""``model.ontologies``: seam:Ontology models, their classes and superclasses (ADR-0022)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from rdflib import OWL, RDF, RDFS, URIRef
from rdflib.namespace import SKOS
from rdflib.term import Node

from ..namespaces import SEAM, local_name
from ..ontologies import vendored_graph
from ._base import Element, Many, element_type


class Superclass(NamedTuple):
    """An ``rdfs:subClassOf`` target of a class. ``source`` is where it is
    declared: the ``seam:Model`` that declares it as an ``owl:Class``, the
    version IRI of the resolved import that declares it, or None when neither
    does (a likely typo; ADR-0022 section 5). ``label`` and ``definition`` come
    from that source (``rdfs:label``, else ``skos:prefLabel``, else the local
    name; ``skos:definition``)."""

    iri: URIRef
    label: str
    definition: str | None
    source: URIRef | None


def _first_text(values: list[Node]) -> str | None:
    texts = sorted(str(v) for v in values)
    return texts[0] if texts else None


@element_type(OWL.Class)
@dataclass(frozen=True, eq=False)
class OntologyClass(Element):
    """An owl:Class a model declares."""

    @property
    def definition(self) -> str | None:
        """Its skos:definition (the first by lexical form when there are several)."""
        return _first_text(self._values(SKOS.definition))

    @property
    def superclasses(self) -> tuple[Superclass, ...]:
        """Its rdfs:subClassOf IRIs, sorted, each with where it is declared."""
        views = self.views
        ds = views.ds
        out: list[Superclass] = []
        for parent in self._objects(RDFS.subClassOf):
            model = ds.value(parent, SEAM.inModel)
            if (parent, RDF.type, OWL.Class) in ds and isinstance(model, URIRef):
                definition = _first_text(sorted(set(ds.objects(parent, SKOS.definition)), key=str))
                out.append(Superclass(parent, views.model.label(parent), definition, model))
                continue
            out.append(_imported(self, parent))
        return tuple(out)

    @property
    def properties(self) -> Many[Element]:
        """The properties whose rdfs:domain it is, by IRI."""
        return self._related(self._subjects(RDFS.domain), RDFS.domain)


def _imported(cls: OntologyClass, parent: URIRef) -> Superclass:
    for status in cls.views.model.import_statuses:
        if status.vendored is None or status.ontology != cls.model:
            continue
        graph = vendored_graph(status.vendored)
        if (parent, RDF.type, OWL.Class) not in graph:
            continue
        label = graph.value(parent, RDFS.label) or graph.value(parent, SKOS.prefLabel)
        definition = _first_text(sorted(set(graph.objects(parent, SKOS.definition)), key=str))
        text = local_name(parent) if label is None else str(label)
        return Superclass(parent, text, definition, status.vendored.version)
    return Superclass(parent, local_name(parent), None, None)


@dataclass(frozen=True, eq=False)
class Ontology(Element):
    """A ``seam:Model`` with ``seam:notation seam:Ontology``: also the owl:Ontology."""

    @property
    def version_iri(self) -> URIRef | None:
        """Its owl:versionIRI (the shapes require exactly one)."""
        found = self._objects(OWL.versionIRI)
        return found[0] if len(found) == 1 else None

    @property
    def imports(self) -> tuple[URIRef, ...]:
        """The version IRIs it owl:imports, sorted."""
        return tuple(self._objects(OWL.imports))

    def classes(self) -> Many[OntologyClass]:
        """The owl:Classes seam:inModel it, by IRI."""
        ds = self.views.ds
        iris = [c for c in self._subjects(SEAM.inModel) if (c, RDF.type, OWL.Class) in ds]
        return self._many(OntologyClass, iris, SEAM.inModel)

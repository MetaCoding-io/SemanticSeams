"""Graph-fact helpers shared by the seams generators (M004).

``Facts`` wraps a loaded ``ModelGraph`` with the lookups every generator
needs: sorted objects/subjects (always by IRI, never graph iteration order),
exactly-one and at-most-one accessors that raise ``GeneratorError`` naming the
subject and predicate, curies and ``comm:path`` templates.
"""

from __future__ import annotations

import re

from rdflib import RDFS, Literal, Namespace
from seams import COMM, HYDRA, ModelGraph, local_name

from . import GeneratorError

DASH = Namespace("http://datashapes.org/dash#")


class Facts:
    def __init__(self, model: ModelGraph):
        self.m = model
        self.ds = model.ds
        self._ns = sorted(((str(ns), prefix) for prefix, ns in self.ds.namespaces()), key=lambda p: (-len(p[0]), p[1]))

    def curie(self, iri) -> str:
        """prefix:local for the longest bound namespace; the local part is the
        IRI's last fragment/segment (a BPMN element <model#id> shows as :id)."""
        s = str(iri)
        for ns, prefix in self._ns:
            if s.startswith(ns):
                return f"{prefix}:{local_name(s)}"
        return f"<{s}>"

    def objects(self, s, p) -> list:
        return sorted(set(self.ds.objects(s, p)), key=str)

    def subjects(self, p, o) -> list:
        return sorted(set(self.ds.subjects(p, o)), key=str)

    def one(self, s, p, detail: str = ""):
        values = self.objects(s, p)
        if len(values) != 1:
            found = "none" if not values else ", ".join(str(v) for v in values)
            raise GeneratorError(
                s,
                p,
                f"{detail}: expected exactly one, found {found}" if detail else f"expected exactly one, found {found}",
            )
        return values[0]

    def optional(self, s, p):
        values = self.objects(s, p)
        if len(values) > 1:
            raise GeneratorError(s, p, f"expected at most one, found {', '.join(map(str, values))}")
        return values[0] if values else None

    def int_value(self, s, p) -> int | None:
        v = self.optional(s, p)
        if v is None:
            return None
        if not isinstance(v, Literal) or not isinstance(v.toPython(), int):
            raise GeneratorError(s, p, f"expected an integer, found {v!r}")
        return int(v.toPython())

    def label(self, s) -> str:
        return str(self.one(s, RDFS.label))

    def path_template(self, s) -> tuple[str, dict[str, str]]:
        """comm:path hydra:template and {variable: local name of hydra:property}."""
        node = self.one(s, COMM.path)
        template = str(self.one(node, HYDRA.template, f"comm:path of {s}"))
        mappings = {}
        for m in self.objects(node, HYDRA.mapping):
            mappings[str(self.one(m, HYDRA.variable))] = local_name(self.one(m, HYDRA.property))
        variables = re.findall(r"\{(\w+)\}", template)
        missing = [v for v in variables if v not in mappings]
        if missing:
            raise GeneratorError(node, HYDRA.mapping, f"no mapping for template variable(s) {missing}")
        return template, mappings

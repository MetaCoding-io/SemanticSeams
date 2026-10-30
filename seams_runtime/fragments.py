"""``FragmentRenderer``: the htmx partials generated handlers return (D017).

    runtime.render_fragment("message_thread.html", messages)
    runtime.render_fragment("message_thread_item.html", message)

A fragment name is a seam:rendersComponent target's local name, optionally
with an ``_item`` suffix for the one-item partial (seams_gen.fragments
.fragment_for). The name is resolved against the graph before it is used
as a template path, so an unknown or path-like name never touches the
filesystem. The bound variables follow the seam.ttl visibleWhen rule: the
component's seam:reads shape ``:MessageShape`` gives ``messages`` (whole
component), ``message`` (item partial) and, when the component has
seam:visibleWhen, ``message_state``. ``component_context`` applies the
same rule to a page block (Runtime.render_page).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import jinja2
from rdflib import URIRef

from .errors import ResolutionError
from .model import SEAM, ModelGraph, local_name

log = logging.getLogger(__name__)

ITEM_SUFFIX = "_item"


def shape_name(shape) -> str:
    """:MessageShape -> message (same rule as seams_gen.htmx._shape_name)."""
    name = local_name(shape).lower()
    return name[: -len("shape")] if name.endswith("shape") and len(name) > 5 else name


def flatten(item) -> dict:
    """A Store entity row becomes its payload plus ``id`` and ``status``;
    a plain mapping passes through as a dict."""
    item = dict(item)
    if isinstance(item.get("data"), Mapping):
        data = dict(item["data"])
        return {**data, "id": item.get("id"), "status": data.get("status") or item.get("status")}
    return item


@dataclass(frozen=True)
class Fragment:
    template: str
    component: URIRef
    item: bool
    shape: URIRef | None
    visible_when: URIRef | None


class FragmentRenderer:
    def __init__(self, model: ModelGraph, templates_dir):
        self.model = model
        self.templates_dir = Path(templates_dir)
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self.templates_dir)),
            autoescape=True,  # lenient Undefined: a fresh payload has no status/timestamp
        )

    def _components(self) -> dict[str, URIRef]:
        return {local_name(c): c for c in self.model.ds.objects(None, SEAM.rendersComponent) if isinstance(c, URIRef)}

    def resolve(self, name: str) -> Fragment:
        components = self._components()
        stem = name[: -len(".html")] if name.endswith(".html") else name
        item = stem.endswith(ITEM_SUFFIX) and stem[: -len(ITEM_SUFFIX)] in components
        local = stem[: -len(ITEM_SUFFIX)] if item else stem
        component = components.get(local)
        if component is None:
            raise ResolutionError(
                self.model.subject, SEAM.rendersComponent, f"no rendered component for template {name!r}"
            )
        return self._fragment(component, item)

    def _fragment(self, component: URIRef, item: bool = False) -> Fragment:
        return Fragment(
            f"{local_name(component)}{ITEM_SUFFIX if item else ''}.html",
            component,
            item,
            self.model.ds.value(component, SEAM.reads),
            self.model.ds.value(component, SEAM.visibleWhen),
        )

    def component_context(self, component, data, params: Mapping | None = None) -> dict:
        """The variables a page block for ``component`` needs: the same
        binding as the component's whole partial (``messages``,
        ``message_state``), whether or not an operation renders it."""
        return self._context(self._fragment(self.model.curie(component)), data, params or {})

    def context(self, name: str, data, params: Mapping | None = None) -> dict:
        frag = self.resolve(name)
        return self._context(frag, data, params or {})

    def _context(self, frag: Fragment, data, params: Mapping) -> dict:
        if frag.shape is None:
            raise ResolutionError(frag.component, SEAM.reads, f"component of template {frag.template!r} reads no shape")
        var = shape_name(frag.shape)
        if frag.item:
            items = [flatten(data)]
            ctx = {var: items[0]}
        else:
            rows = [data] if isinstance(data, Mapping) else list(data or [])
            items = [flatten(d) for d in rows]
            ctx = {f"{var}s": items}
        if frag.visible_when is not None:
            statuses = [i["status"] for i in items if i.get("status")]
            ctx[f"{var}_state"] = statuses[-1] if statuses else self.model.lifecycle_for(frag.shape).initial
        ctx.update(params)
        return ctx

    def render(self, name: str, data, params: Mapping | None = None) -> str:
        frag = self.resolve(name)
        ctx = self._context(frag, data, params or {})
        log.debug("render_fragment %s: component %s, variables %s", frag.template, frag.component, sorted(ctx))
        return self.env.get_template(frag.template).render(ctx)

    def render_template(self, template: str, ctx: Mapping) -> str:
        """Render a template by name; callers resolve ``template`` from the graph."""
        log.debug("render %s: variables %s", template, sorted(ctx))
        return self.env.get_template(template).render(dict(ctx))

"""The htmx page generator (M004/S04, D016).

``extract_page`` reads the landmark IFML ViewContainer and the seam, shape,
communication and lifecycle facts it touches into frozen dataclasses;
``generate_page`` renders them through templates/htmx_page.html.j2. The
template holds the fixed text only: every model-specific string comes from the
``PageModel``, and every collection is sorted explicitly (components by
ifml:order, fields by sh:order, everything else by IRI), never by graph
iteration order. A missing or ambiguous required fact raises
``GeneratorError`` naming the subject IRI and the predicate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import jinja2
from rdflib import RDF, RDFS, XSD, Literal, Namespace, URIRef
from rdflib.namespace import SH

from seams_runtime import ModelGraph
from seams_runtime.model import COMM, HYDRA, SEAM, STATE, local_name

from . import GeneratorError

IFML = Namespace("https://w3id.org/seams/ifml#")
DASH = Namespace("http://datashapes.org/dash#")

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_NAME = "htmx_page.html.j2"

# ifml:swap value -> (hx-swap, targets the component's item list); the rule
# documented on ifml:swap in ontology/ifml.ttl.
SWAPS = {
    IFML.Replace: ("outerHTML", False),
    IFML.Append: ("beforeend", True),
    IFML.Prepend: ("afterbegin", True),
}

# The IFML ViewComponent types the generator renders, in the order they are
# checked (a component must have exactly one).
COMPONENT_TYPES = (IFML.List, IFML.Details, IFML.Form)


# ── the page model ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Field:
    name: str        # local name of sh:path
    kind: str        # "textarea" (dash:TextAreaEditor), "datetime", "enum" (sh:in) or "text"
    order: int | None
    max_length: int | None
    required: bool   # sh:minCount >= 1


@dataclass(frozen=True)
class Flow:
    curie: str
    target: str      # local name of ifml:target
    swap: str        # hx-swap
    target_id: str   # hx-target element id (#<target> or #<target>_items)


@dataclass(frozen=True)
class Link:
    """The navigation an item of a List fires (ifml:hasEvent -> NavigationFlow)."""
    event_trigger: str
    flow: Flow
    get_path: str    # hx-get, with path variables filled from the item
    vals: tuple[tuple[str, str], ...]  # hx-vals from the DataFlow ParameterBinding


@dataclass(frozen=True)
class Stream:
    id: str          # local name of the comm:Channel
    curie: str
    publisher: str   # curie of the element that seam:publishesTo the channel
    connect: str     # sse-connect path
    event_name: str  # sse-swap


@dataclass(frozen=True)
class Input:
    """A form field: an ifml:Parameter ifml:boundTo a written shape's sh:path."""
    id: str
    name: str
    element: str     # "textarea" or "input"
    attributes: tuple[str, ...]


@dataclass(frozen=True)
class Submit:
    event: str       # curie
    label: str       # button text
    method: str      # lowercased hydra:method (hx-<method>)
    method_upper: str
    path: str
    operation: str   # curie
    media_kind: str  # local name of seam:mediaKind
    consumer: str    # curie of the container that seam:consumes the operation
    triggers: tuple[str, ...]
    event_policies: tuple[str, ...]
    route_policies: tuple[str, ...]
    flow: Flow


@dataclass(frozen=True)
class Component:
    id: str
    curie: str
    kind: str        # "List", "Details" or "Form"
    type_curie: str
    label: str
    order: int
    reads: str | None
    writes: str | None
    guard_variable: str | None
    guard_state: str | None
    guard_state_curie: str | None
    parameters: tuple[str, ...]
    # List / Details
    collection: str | None = None
    loop_var: str | None = None
    item_class: str | None = None
    fields: tuple[Field, ...] = ()
    link: Link | None = None
    display_field: str | None = None
    stream: Stream | None = None
    # Form
    submit: Submit | None = None
    inputs: tuple[Input, ...] = ()
    unbound: tuple[str, ...] = ()


@dataclass(frozen=True)
class PageModel:
    model_stem: str
    model_hash: str
    id: str
    curie: str
    interaction_model: str
    path: str
    title: str
    uses_sse: bool
    components: tuple[Component, ...]


# ── graph helpers ───────────────────────────────────────────────────────────


class _Facts:
    def __init__(self, model: ModelGraph):
        self.m = model
        self.ds = model.ds
        self._ns = sorted(((str(ns), prefix) for prefix, ns in self.ds.namespaces()),
                          key=lambda p: (-len(p[0]), p[1]))

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
            raise GeneratorError(s, p, f"{detail}: expected exactly one, found {found}"
                                 if detail else f"expected exactly one, found {found}")
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


def _shape_name(shape) -> str:
    """:MessageShape -> message (the seam:visibleWhen variable rule in seam.ttl)."""
    name = local_name(shape).lower()
    return name[: -len("shape")] if name.endswith("shape") and len(name) > 5 else name


def _fill(template: str, fill) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: "{{ " + fill(m.group(1)) + " }}", template)


# ── extraction ──────────────────────────────────────────────────────────────


def extract_page(model: ModelGraph) -> PageModel:
    f = _Facts(model)
    page = _landmark(f, model)
    imodel = _interaction_model(f, page)
    presenter = _presenter(f, imodel)

    components = []
    for c in f.objects(page, IFML.contains):
        components.append((f.int_value(c, IFML.order), c))
    unordered = [c for order, c in components if order is None]
    if unordered:
        raise GeneratorError(unordered[0], IFML.order, f"component of {page} has no ifml:order")
    components.sort(key=lambda oc: oc[0])

    page_params = {f.label(p) for _, c in components for p in f.objects(c, IFML.hasParameter)}
    sse_channels = [ch for ch in f.objects(presenter, SEAM.consumes)
                    if (ch, RDF.type, COMM.Channel) in f.ds
                    and (ch, COMM.transport, COMM.SSE) in f.ds]

    built = tuple(_component(f, c, order, presenter, page_params, sse_channels)
                  for order, c in components)
    return PageModel(
        model_stem=model.path.stem,
        model_hash=model.hash,
        id=local_name(page),
        curie=f.curie(page),
        interaction_model=f.curie(imodel),
        path=str(f.one(page, IFML.path)),
        title=str(f.one(page, IFML.title)),
        uses_sse=bool(sse_channels),
        components=built,
    )


def _landmark(f: _Facts, model: ModelGraph):
    containers = f.subjects(RDF.type, IFML.ViewContainer)
    landmarks = [c for c in containers if (c, IFML.isLandmark, Literal(True)) in f.ds]
    if len(landmarks) != 1:
        models = f.subjects(RDF.type, IFML.InteractionModel)
        subject = models[0] if len(models) == 1 else model.subject
        found = ", ".join(map(str, landmarks)) or "none"
        raise GeneratorError(subject, IFML.isLandmark,
                             f"expected exactly one ifml:ViewContainer with ifml:isLandmark true, found {found}")
    return landmarks[0]


def _interaction_model(f: _Facts, page):
    models = [m for m in f.subjects(IFML.contains, page)
              if (m, RDF.type, IFML.InteractionModel) in f.ds]
    if len(models) != 1:
        raise GeneratorError(page, IFML.contains,
                             f"expected one ifml:InteractionModel containing the page, found {len(models)}")
    return models[0]


def _presenter(f: _Facts, imodel):
    presenters = f.subjects(SEAM.presents, imodel)
    if len(presenters) != 1:
        raise GeneratorError(imodel, SEAM.presents,
                             f"expected one container presenting the model, found {len(presenters)}")
    return presenters[0]


def _component(f: _Facts, c, order, presenter, page_params, sse_channels) -> Component:
    types = [t for t in COMPONENT_TYPES if (c, RDF.type, t) in f.ds]
    if len(types) != 1:
        raise GeneratorError(c, RDF.type, f"expected one of {[f.curie(t) for t in COMPONENT_TYPES]}")
    ctype = types[0]
    reads = f.optional(c, SEAM.reads)
    writes = f.optional(c, SEAM.writes)
    guard_var = guard_state = guard_curie = None
    state = f.optional(c, SEAM.visibleWhen)
    if state is not None:
        if reads is None:
            raise GeneratorError(c, SEAM.reads, "seam:visibleWhen needs the shape the component reads")
        machine = f.one(reads, SEAM.lifecycle, f"guard {state} of {c}")
        if (machine, STATE.hasState, state) not in f.ds:
            raise GeneratorError(machine, STATE.hasState, f"guard state {state} of {c} is not a state of it")
        guard_var = _shape_name(reads) + "_state"
        guard_state = f.label(state)
        guard_curie = f.curie(state)

    base = dict(
        id=local_name(c), curie=f.curie(c), kind=local_name(ctype), type_curie=f.curie(ctype),
        label=f.label(c), order=order,
        reads=f.curie(reads) if reads is not None else None,
        writes=f.curie(writes) if writes is not None else None,
        guard_variable=guard_var, guard_state=guard_state, guard_state_curie=guard_curie,
        parameters=tuple(sorted(f.label(p) for p in f.objects(c, IFML.hasParameter))),
    )

    def fill_param(var: str) -> str:
        if var not in page_params:
            raise GeneratorError(c, IFML.hasParameter,
                                 f"path variable {var!r} names no ifml:Parameter of the page")
        return var

    if ctype == IFML.List:
        if reads is None:
            raise GeneratorError(c, SEAM.reads, "an ifml:List must read a shape")
        link = _list_link(f, c)
        fields = _fields(f, reads)
        identifiers = {expr.split(".", 1)[1] for _, expr in link.vals}
        identifiers |= set(re.findall(r"\{\{ item\.(\w+) \}\}", link.get_path))
        display = [fl.name for fl in fields if fl.name not in identifiers]
        if not display:
            raise GeneratorError(reads, SH.property, "no non-identifier datatype property to display")
        return Component(**base, collection=_shape_name(reads) + "s", loop_var="item",
                         link=link, display_field=display[0])

    if ctype == IFML.Details:
        if reads is None:
            raise GeneratorError(c, SEAM.reads, "an ifml:Details must read a shape")
        streams = [ch for ch in sse_channels if (ch, SEAM.acceptsShape, reads) in f.ds]
        if len(streams) > 1:
            raise GeneratorError(c, SEAM.reads, f"ambiguous SSE channels {list(map(str, streams))}")
        stream = None
        if streams:
            ch = streams[0]
            publishers = f.subjects(SEAM.publishesTo, ch)
            if len(publishers) != 1:
                raise GeneratorError(ch, SEAM.publishesTo,
                                     f"expected one publisher, found {len(publishers)}")
            template, _ = f.path_template(ch)
            stream = Stream(id=local_name(ch), curie=f.curie(ch), publisher=f.curie(publishers[0]),
                            connect=_fill(template, fill_param),
                            event_name=str(f.one(ch, COMM.eventName)))
        name = _shape_name(reads)
        return Component(**base, collection=name + "s", loop_var=name,
                         item_class=f.label(reads).lower(), fields=_fields(f, reads), stream=stream)

    # ifml:Form
    if writes is None:
        raise GeneratorError(c, SEAM.writes, "an ifml:Form must write a shape")
    submit = _submit(f, c, presenter, fill_param)
    fields = _fields(f, writes)
    bound = {}
    for p in f.objects(c, IFML.hasParameter):
        target = f.optional(p, IFML.boundTo)
        if target is not None:
            bound[local_name(target)] = p
    by_name = {fl.name: fl for fl in fields}
    unknown = sorted(set(bound) - set(by_name))
    if unknown:
        raise GeneratorError(bound[unknown[0]], IFML.boundTo,
                             f"{unknown[0]!r} is not a datatype sh:path of {writes}")
    prefix = base["id"]
    suffix = "_" + local_name(ctype).lower()
    if prefix.endswith(suffix) and len(prefix) > len(suffix):
        prefix = prefix[: -len(suffix)]
    inputs = tuple(_input(prefix, fl) for fl in fields if fl.name in bound)
    unbound = tuple(fl.name for fl in fields if fl.name not in bound)
    return Component(**base, fields=fields, submit=submit, inputs=inputs, unbound=unbound)


def _fields(f: _Facts, shape) -> tuple[Field, ...]:
    fields = []
    for prop in f.objects(shape, SH.property):
        if f.optional(prop, SH.datatype) is None:
            continue  # object-valued (sh:class) properties are not rendered fields
        datatype = f.optional(prop, SH.datatype)
        if f.optional(prop, DASH.editor) == DASH.TextAreaEditor:
            kind = "textarea"
        elif datatype == XSD.dateTime:
            kind = "datetime"
        elif f.optional(prop, SH["in"]) is not None:
            kind = "enum"
        else:
            kind = "text"
        min_count = f.int_value(prop, SH.minCount)
        fields.append(Field(
            name=local_name(f.one(prop, SH.path)), kind=kind,
            order=f.int_value(prop, SH.order), max_length=f.int_value(prop, SH.maxLength),
            required=min_count is not None and min_count >= 1,
        ))
    fields.sort(key=lambda fl: (fl.order is None, fl.order or 0, fl.name))
    return tuple(fields)


def _flow(f: _Facts, flow) -> Flow:
    target = f.one(flow, IFML.target)
    swap = f.one(flow, IFML.swap)
    if swap not in SWAPS:
        raise GeneratorError(flow, IFML.swap, f"unknown swap strategy {swap}")
    hx_swap, to_items = SWAPS[swap]
    tid = local_name(target) + ("_items" if to_items else "")
    return Flow(curie=f.curie(flow), target=local_name(target), swap=hx_swap, target_id=tid)


def _navigation(f: _Facts, event):
    flows = [fl for fl in f.subjects(IFML.source, event)
             if (fl, RDF.type, IFML.NavigationFlow) in f.ds]
    if len(flows) != 1:
        raise GeneratorError(event, IFML.source,
                             f"expected one ifml:NavigationFlow from the event, found {len(flows)}")
    return flows[0]


def _list_link(f: _Facts, c) -> Link:
    event = f.one(c, IFML.hasEvent)
    flow_iri = _navigation(f, event)
    flow = _flow(f, flow_iri)
    target = f.one(flow_iri, IFML.target)
    reads_ops = [op for op in f.subjects(SEAM.rendersComponent, target)
                 if str(f.optional(op, HYDRA.method)) == "GET"]
    if len(reads_ops) != 1:
        raise GeneratorError(target, SEAM.rendersComponent,
                             f"expected one GET operation rendering {target}, found {len(reads_ops)}")
    template, mappings = f.path_template(reads_ops[0])
    get_path = _fill(template, lambda var: "item." + mappings[var])

    vals = []
    for df in f.subjects(IFML.source, c):
        if (df, RDF.type, IFML.DataFlow) not in f.ds or (df, IFML.target, target) not in f.ds:
            continue
        for binding in f.objects(df, IFML.binds):
            f.one(binding, IFML.sourceParameter)
            name = f.label(f.one(binding, IFML.targetParameter))
            if name not in mappings:
                raise GeneratorError(binding, IFML.targetParameter,
                                     f"{name!r} is not a path variable of {reads_ops[0]}")
            vals.append((name, "item." + mappings[name]))
    return Link(event_trigger=str(f.one(event, IFML.trigger)), flow=flow,
                get_path=get_path, vals=tuple(sorted(vals)))


def _submit(f: _Facts, c, presenter, fill_param) -> Submit:
    events = [e for e in f.objects(c, IFML.hasEvent) if f.objects(e, SEAM.submitsTo)]
    if len(events) != 1:
        subject = f.objects(c, IFML.hasEvent)
        subject = subject[0] if len(subject) == 1 else c
        raise GeneratorError(subject, SEAM.submitsTo,
                             f"expected one event of form {c} that seam:submitsTo an operation, "
                             f"found {len(events)}")
    event = events[0]
    op = f.one(event, SEAM.submitsTo)
    if (presenter, SEAM.consumes, op) not in f.ds:
        raise GeneratorError(presenter, SEAM.consumes, f"the presenting container does not consume {op}")
    method = str(f.one(op, HYDRA.method))
    template, _ = f.path_template(op)
    return Submit(
        event=f.curie(event), label=f.label(event), method=method.lower(), method_upper=method.upper(),
        path=_fill(template, fill_param), operation=f.curie(op),
        media_kind=local_name(f.one(op, SEAM.mediaKind)), consumer=f.curie(presenter),
        triggers=tuple(f.curie(p) for p in f.objects(event, SEAM.triggers)),
        event_policies=tuple(f.curie(p) for p in f.objects(event, SEAM.governedBy)),
        route_policies=tuple(f.curie(p) for p in f.objects(op, SEAM.governedBy)),
        flow=_flow(f, _navigation(f, event)),
    )


def _input(prefix: str, fl: Field) -> Input:
    element = "textarea" if fl.kind == "textarea" else "input"
    attributes = [f'name="{fl.name}"']
    if element == "input":
        attributes.append('type="datetime-local"' if fl.kind == "datetime" else 'type="text"')
    if fl.max_length is not None:
        attributes.append(f'maxlength="{fl.max_length}"')
    if fl.required:
        attributes.append("required")
    return Input(id=f"{prefix}_{fl.name}", name=fl.name, element=element, attributes=tuple(attributes))


# ── rendering ───────────────────────────────────────────────────────────────


def _environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        variable_start_string="[[", variable_end_string="]]",
        block_start_string="[%", block_end_string="%]",
        comment_start_string="[#", comment_end_string="#]",
        keep_trailing_newline=True, trim_blocks=True, lstrip_blocks=True,
        undefined=jinja2.StrictUndefined, autoescape=False,
    )
    env.filters["english_list"] = _english_list
    return env


def _english_list(items) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def render_page(page: PageModel) -> str:
    return _environment().get_template(TEMPLATE_NAME).render(page=page)


def generate_page(trig_path) -> str:
    """Load the model and render its landmark page."""
    return render_page(extract_page(ModelGraph.load(trig_path)))

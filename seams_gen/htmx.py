"""The htmx page generator (M004/S04, D016).

``extract_page`` reads the landmark IFML ViewContainer and the seam, shape,
communication and lifecycle facts it touches into frozen dataclasses, through
``model.interfaces`` and the seams views it links to (D036), never raw triples;
``generate_page`` renders them through templates/htmx_page.html.j2 and
``generate_fragments`` renders the partials the presenting container's
UIFragment operations name (GAP-19, D017) through htmx_fragment.html.j2, plus,
for each ``ifml:Form`` a ``proc:UserTask`` ``seam:completedOn`` (ADR-0009), a
task form partial through htmx_task_form.html.j2 and the partials of the
components its completion renders on the form's screen. ``generate_pages``
renders every page of ``model.interfaces.served_pages()``: the landmark, then
each other page with an ``ifml:path`` and no task form, extracted the same way
and rendered with its own partials. The
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
from rdflib import RDF, XSD, URIRef
from rdflib.namespace import SH
from seams import (
    COMM,
    DASH,
    HYDRA,
    IFML,
    PROC,
    SEAM,
    STATE,
    Channel,
    Model,
    ModelGraph,
    Operation,
    Page,
    ProcessElement,
    ResolutionError,
    local_name,
)
from seams import Component as ComponentView

from . import GeneratorError
from ._views import label, only, optional, required, view_errors
from .fragments import fragment_for

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_NAME = "htmx_page.html.j2"
FRAGMENT_TEMPLATE_NAME = "htmx_fragment.html.j2"
TASK_FORM_TEMPLATE_NAME = "htmx_task_form.html.j2"

# The runtime variable a task form partial fills the correlation-key path
# variable from: Runtime.user_tasks rows are bound as ``task``.
TASK_KEY = "task.correlation_key"

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
    name: str  # local name of sh:path
    kind: str  # "textarea" (dash:TextAreaEditor), "datetime", "enum" (sh:in) or "text"
    order: int | None
    max_length: int | None
    required: bool  # sh:minCount >= 1
    options: tuple[str, ...] = ()  # sh:in values, in list order


@dataclass(frozen=True)
class Flow:
    curie: str
    target: str  # local name of ifml:target
    swap: str  # hx-swap
    target_id: str  # hx-target element id (#<target> or #<target>_items)


@dataclass(frozen=True)
class Link:
    """The navigation an item of a List fires (ifml:hasEvent -> NavigationFlow)."""

    event_trigger: str
    flow: Flow
    get_path: str  # hx-get, with path variables filled from the item
    vals: tuple[tuple[str, str], ...]  # hx-vals from the DataFlow ParameterBinding


@dataclass(frozen=True)
class Stream:
    id: str  # local name of the comm:Channel
    curie: str
    publisher: str  # curie of the element that seam:publishesTo the channel
    connect: str  # sse-connect path
    event_name: str  # sse-swap


@dataclass(frozen=True)
class Input:
    """A form field: an ifml:Parameter ifml:boundTo a written shape's sh:path."""

    id: str
    name: str
    element: str  # "textarea", "input" or (task forms only) "select"
    attributes: tuple[str, ...]
    options: tuple[str, ...] = ()  # a select's sh:in values


@dataclass(frozen=True)
class Submit:
    event: str  # curie
    label: str  # button text
    method: str  # lowercased hydra:method (hx-<method>)
    method_upper: str
    path: str
    operation: str  # curie
    media_kind: str  # local name of seam:mediaKind
    consumer: str  # curie of the container that seam:consumes the operation
    triggers: tuple[str, ...]
    event_policies: tuple[str, ...]
    route_policies: tuple[str, ...]
    flow: Flow
    # correlation-key variables no page component binds: a form that starts a
    # new process instance; the path keeps {key} and the browser fills it
    # with a fresh random key on every submit
    mint: tuple[str, ...] = ()


@dataclass(frozen=True)
class Component:
    id: str
    curie: str
    kind: str  # "List", "Details" or "Form"
    type_curie: str
    label: str
    order: int
    reads: str | None
    writes: str | None
    guard_variable: str | None
    guard_states: tuple[str, ...]
    guard_state_curies: tuple[str, ...]
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
class Fragment:
    """A partial named by the GAP-19 rule (seams_gen.fragments.fragment_for)."""

    name: str  # file name, <component>.html or <component>_item.html
    component: str  # local name of the seam:rendersComponent target
    kind: str  # "component" or "item"
    operations: tuple[str, ...]  # curies of the operations that render it, by IRI


@dataclass(frozen=True)
class TaskForm:
    """The partial of an ifml:Form a proc:UserTask seam:completedOn (ADR-0009),
    rendered by the host's task inbox with ``task`` bound to a
    Runtime.user_tasks row."""

    name: str  # file name, <form local name>.html
    id: str  # the form's local name
    curie: str
    label: str  # the form's rdfs:label
    task: str  # curie of the user task
    task_label: str  # the task's rdfs:label
    key: str  # the process's proc:correlationKey rdfs:label
    entity_class: str | None  # the task's seam:reads shape label, lowercased
    entity_fields: tuple[Field, ...]
    submit: Submit
    inputs: tuple[Input, ...]
    unbound: tuple[str, ...]


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
    fragments: tuple[Fragment, ...] = ()
    task_forms: tuple[TaskForm, ...] = ()
    screen_components: tuple[Component, ...] = ()  # rendered components of task form screens
    landmark: bool = True  # Page.is_landmark; False for the other model.interfaces.served_pages()


# ── graph helpers ───────────────────────────────────────────────────────────


def _shape_name(shape) -> str:
    """:MessageShape -> message (the seam:visibleWhen variable rule in seam.ttl)."""
    name = local_name(shape).lower()
    return name[: -len("shape")] if name.endswith("shape") and len(name) > 5 else name


def _fill(template: str, fill) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: "{{ " + fill(m.group(1)) + " }}", template)


def _path_template(endpoint) -> tuple[str, dict[str, str]]:
    """An operation's or channel's comm:path hydra:template and {variable:
    local name of hydra:property}; every template variable must be mapped."""
    path = required(endpoint.path, endpoint.iri, COMM.path)
    mappings = {m.variable: m.property for m in path.mappings}
    missing = [v for v in re.findall(r"\{(\w+)\}", path.template) if v not in mappings]
    if missing:
        raise GeneratorError(endpoint.iri, HYDRA.mapping, f"no mapping for template variable(s) {missing}")
    return path.template, mappings


def _parameters(model: Model, component) -> list[str]:
    """The labels of a component's ifml:hasParameter parameters, by parameter IRI."""
    return [label(model, p.iri) for p in component.parameter_bindings]


# ── extraction ──────────────────────────────────────────────────────────────


def extract_page(model: Model, page=None) -> PageModel:
    """``page`` (one of ``model.interfaces.served_pages()``), by default
    ``model.interfaces.landmark()``. Only the landmark's PageModel carries the
    task forms and their screens' components; any other page carries its own
    components and partials. This is the IFML interpretation: it reads the
    model only through ``model.interfaces`` and the views it links to (D036)."""
    with view_errors():
        return _extract_page(model, page)


def _extract_page(model: Model, page) -> PageModel:
    view = _landmark(model) if page is None else model.interfaces.pages().by_iri(model.curie(page))
    landmark = view.is_landmark
    imodel = _interaction_model(model, view)
    presenter = _presenter(imodel)

    components = list(view.components())  # by ifml:order, then IRI
    unordered = [c for c in components if c.order is None]
    if unordered:
        raise GeneratorError(unordered[0].iri, IFML.order, f"component of {view.iri} has no ifml:order")

    page_params = {name for c in components for name in _parameters(model, c)}
    # Runtime.page_context binds a correlation key only when a component that
    # seam:reads a shape is scoped by it; any other key in a submit path is new.
    keys = {p.correlation_key for p in model.processes if p.correlation_key is not None}
    bound_keys = {name for c in components if c.reads for name in _parameters(model, c)} & keys
    mintable = keys - bound_keys
    sse_channels = [ch for ch in presenter.consumes if isinstance(ch, Channel) and ch.transport == COMM.SSE]

    built = tuple(_component(model, c, c.order, presenter, page_params, sse_channels, mintable) for c in components)
    task_forms = _task_forms(model, presenter) if landmark else ()
    screens = _screen_components(model, presenter, task_forms, {c.id for c in built}, sse_channels)
    return PageModel(
        model_stem=model.path.stem,
        model_hash=model.hash,
        id=local_name(view.iri),
        curie=model.compact(view.iri),
        interaction_model=model.compact(imodel.iri),
        path=required(view.path, view.iri, IFML.path),
        title=required(view.title, view.iri, IFML.title),
        uses_sse=bool(sse_channels),
        components=built,
        fragments=_fragments(model, presenter, {c.id for c in built + screens}),
        task_forms=task_forms,
        screen_components=screens,
        landmark=landmark,
    )


def _fragments(model: Model, presenter, component_ids) -> tuple[Fragment, ...]:
    """Every partial an operation the presenter seam:consumes renders onto a
    page component, grouped by file name and sorted by it."""
    found: dict[str, tuple[str, str, list]] = {}
    for op in presenter.consumes:
        if not isinstance(op, Operation) or not op.renders:
            continue
        name, component, kind = fragment_for(model, op)
        if local_name(component) not in component_ids:
            continue
        found.setdefault(name, (local_name(component), kind, []))[2].append(model.compact(op.iri))
    return tuple(
        Fragment(name=name, component=comp, kind=kind, operations=tuple(ops))
        for name, (comp, kind, ops) in sorted(found.items())
    )


def _landmark(model: Model) -> Page:
    """``model.interfaces.landmark()``, its error named on the interaction model."""
    try:
        return model.interfaces.landmark()
    except ResolutionError:
        landmarks = model.interfaces.pages().where(lambda p: p.is_landmark)
        models = model.interfaces.models()
        subject = models[0].iri if len(models) == 1 else model.subject
        found = ", ".join(map(str, landmarks.iris())) or "none"
        raise GeneratorError(
            subject,
            IFML.isLandmark,
            f"expected exactly one ifml:ViewContainer with ifml:isLandmark true, found {found}",
        ) from None


def _interaction_model(model: Model, page: Page):
    models = [m for m in model.interfaces.models() if page in m.pages()]
    if len(models) != 1:
        raise GeneratorError(
            page.iri, IFML.contains, f"expected one ifml:InteractionModel containing the page, found {len(models)}"
        )
    return models[0]


def _presenter(imodel):
    try:
        presenter = imodel.presented_by
    except ResolutionError:
        presenter, found = None, "several"
    else:
        found = "0"
    if presenter is None:
        raise GeneratorError(imodel.iri, SEAM.presents, f"expected one container presenting the model, found {found}")
    return presenter


def _component(model: Model, c, order, presenter, page_params, sse_channels, mintable=frozenset()) -> Component:
    types = c.types
    if len(types) != 1:
        raise GeneratorError(c.iri, RDF.type, f"expected one of {[model.compact(t) for t in COMPONENT_TYPES]}")
    ctype = types[0]
    reads = optional(c.reads)
    writes = optional(c.writes)
    guard_var = None
    guard_states: tuple[str, ...] = ()
    guard_curies: tuple[str, ...] = ()
    states = c.visible_when
    if states:
        if reads is None:
            raise GeneratorError(c.iri, SEAM.reads, "seam:visibleWhen needs the shape the component reads")
        machine = required(reads.lifecycle, reads.iri, SEAM.lifecycle, f"guard of {c.iri}")
        machine_states = machine.states()
        for state in states:
            if state not in machine_states:
                raise GeneratorError(
                    machine.iri, STATE.hasState, f"guard state {state.iri} of {c.iri} is not a state of it"
                )
        guard_var = _shape_name(reads.iri) + "_state"
        guard_states = tuple(sorted(label(model, state.iri) for state in states))
        guard_curies = tuple(sorted(model.compact(state.iri) for state in states))

    base = dict(
        id=local_name(c.iri),
        curie=model.compact(c.iri),
        kind=local_name(ctype),
        type_curie=model.compact(ctype),
        label=label(model, c.iri),
        order=order,
        reads=model.compact(reads.iri) if reads is not None else None,
        writes=model.compact(writes.iri) if writes is not None else None,
        guard_variable=guard_var,
        guard_states=guard_states,
        guard_state_curies=guard_curies,
        parameters=tuple(sorted(_parameters(model, c))),
    )

    def fill_param(var: str) -> str:
        if var not in page_params:
            raise GeneratorError(c.iri, IFML.hasParameter, f"path variable {var!r} names no ifml:Parameter of the page")
        return var

    if ctype == IFML.List:
        if reads is None:
            raise GeneratorError(c.iri, SEAM.reads, "an ifml:List must read a shape")
        link = _list_link(model, c)
        fields = _fields(reads)
        identifiers = {expr.split(".", 1)[1] for _, expr in link.vals}
        identifiers |= set(re.findall(r"\{\{ item\.(\w+) \}\}", link.get_path))
        display = [fl.name for fl in fields if fl.name not in identifiers]
        if not display:
            raise GeneratorError(reads.iri, SH.property, "no non-identifier datatype property to display")
        return Component(
            **base, collection=_shape_name(reads.iri) + "s", loop_var="item", link=link, display_field=display[0]
        )

    if ctype == IFML.Details:
        if reads is None:
            raise GeneratorError(c.iri, SEAM.reads, "an ifml:Details must read a shape")
        streams = [ch for ch in sse_channels if ch.accepts == reads]
        if len(streams) > 1:
            raise GeneratorError(c.iri, SEAM.reads, f"ambiguous SSE channels {[str(ch.iri) for ch in streams]}")
        stream = None
        if streams:
            ch = streams[0]
            publishers = ch.published_by
            if len(publishers) != 1:
                raise GeneratorError(ch.iri, SEAM.publishesTo, f"expected one publisher, found {len(publishers)}")
            template, _ = _path_template(ch)
            stream = Stream(
                id=local_name(ch.iri),
                curie=model.compact(ch.iri),
                publisher=model.compact(publishers[0].iri),
                connect=_fill(template, fill_param),
                event_name=required(ch.event_name, ch.iri, COMM.eventName),
            )
        name = _shape_name(reads.iri)
        return Component(
            **base,
            collection=name + "s",
            loop_var=name,
            item_class=label(model, reads.iri).lower(),
            fields=_fields(reads),
            stream=stream,
        )

    # ifml:Form
    if writes is None:
        raise GeneratorError(c.iri, SEAM.writes, "an ifml:Form must write a shape")
    submit = _submit(model, c, presenter, fill_param, mintable)
    fields = _fields(writes)
    bound = {local_name(p.bound_to): p.iri for p in c.parameter_bindings if p.bound_to is not None}
    by_name = {fl.name: fl for fl in fields}
    unknown = sorted(set(bound) - set(by_name))
    if unknown:
        raise GeneratorError(
            bound[unknown[0]], IFML.boundTo, f"{unknown[0]!r} is not a datatype sh:path of {writes.iri}"
        )
    prefix = base["id"]
    suffix = "_" + local_name(ctype).lower()
    if prefix.endswith(suffix) and len(prefix) > len(suffix):
        prefix = prefix[: -len(suffix)]
    inputs = tuple(_input(prefix, fl) for fl in fields if fl.name in bound)
    unbound = tuple(fl.name for fl in fields if fl.name not in bound)
    return Component(**base, fields=fields, submit=submit, inputs=inputs, unbound=unbound)


def _fields(shape) -> tuple[Field, ...]:
    """A shape's datatype fields (``model.shapes``); object-valued (sh:class)
    properties are not rendered fields."""
    fields = []
    for prop in shape.fields():
        if prop.datatype is None:
            continue
        if prop.editor == DASH.TextAreaEditor:
            kind = "textarea"
        elif prop.datatype == XSD.dateTime:
            kind = "datetime"
        elif prop.options:
            kind = "enum"
        else:
            kind = "text"
        fields.append(
            Field(
                name=prop.name,
                kind=kind,
                order=prop.order,
                max_length=prop.max_length,
                required=prop.required,
                options=prop.options,
            )
        )
    fields.sort(key=lambda fl: (fl.order is None, fl.order or 0, fl.name))
    return tuple(fields)


def _flow(model: Model, flow) -> Flow:
    target = flow.target
    swap = flow.swap
    if swap not in SWAPS:
        raise GeneratorError(flow.iri, IFML.swap, f"unknown swap strategy {swap}")
    hx_swap, to_items = SWAPS[swap]
    tid = local_name(target.iri) + ("_items" if to_items else "")
    return Flow(curie=model.compact(flow.iri), target=local_name(target.iri), swap=hx_swap, target_id=tid)


def _navigation(event):
    flows = event.flows.where(lambda fl: fl.kind == IFML.NavigationFlow)
    if len(flows) != 1:
        raise GeneratorError(
            event.iri, IFML.source, f"expected one ifml:NavigationFlow from the event, found {len(flows)}"
        )
    return flows[0]


def _list_link(model: Model, c) -> Link:
    event = only(c.events())
    navigation = _navigation(event)
    flow = _flow(model, navigation)
    target = navigation.target
    rendering = target.rendered_by if isinstance(target, ComponentView) else ()
    reads_ops = [op for op in rendering if op.method == "GET"]
    if len(reads_ops) != 1:
        raise GeneratorError(
            target.iri,
            SEAM.rendersComponent,
            f"expected one GET operation rendering {target.iri}, found {len(reads_ops)}",
        )
    template, mappings = _path_template(reads_ops[0])
    get_path = _fill(template, lambda var: "item." + mappings[var])

    vals = []
    for df in c.data_flows:
        if target.iri not in df.targets.iris():
            continue
        for binding in df.binds:
            name = label(model, binding.target)
            if name not in mappings:
                raise GeneratorError(
                    df.iri, IFML.targetParameter, f"{name!r} is not a path variable of {reads_ops[0].iri}"
                )
            vals.append((name, "item." + mappings[name]))
    return Link(
        event_trigger=required(event.trigger, event.iri, IFML.trigger),
        flow=flow,
        get_path=get_path,
        vals=tuple(sorted(vals)),
    )


def _submit(model: Model, c, presenter, fill_param, mintable=frozenset()) -> Submit:
    all_events = c.events()
    events = [e for e in all_events if e.submits_to is not None]
    if len(events) != 1:
        subject = all_events[0].iri if len(all_events) == 1 else c.iri
        raise GeneratorError(
            subject,
            SEAM.submitsTo,
            f"expected one event of form {c.iri} that seam:submitsTo an operation, found {len(events)}",
        )
    event = events[0]
    op = event.submits_to
    if op.iri not in presenter.consumes.iris():
        raise GeneratorError(presenter.iri, SEAM.consumes, f"the presenting container does not consume {op.iri}")
    method = required(op.method, op.iri, HYDRA.method)
    template, _ = _path_template(op)
    variables = re.findall(r"\{(\w+)\}", template)
    mint = tuple(v for v in variables if v in mintable)
    for var in mint:
        fill_param(var)  # still a parameter of the page
    path = re.sub(
        r"\{(\w+)\}", lambda m: m.group(0) if m.group(1) in mint else "{{ " + fill_param(m.group(1)) + " }}", template
    )
    return Submit(
        event=model.compact(event.iri),
        label=label(model, event.iri),
        method=method.lower(),
        method_upper=method.upper(),
        path=path,
        operation=model.compact(op.iri),
        mint=mint,
        media_kind=local_name(required(op.media_kind, op.iri, SEAM.mediaKind)),
        consumer=model.compact(presenter.iri),
        triggers=tuple(model.compact(p.iri) for p in event.triggers_all),
        event_policies=tuple(model.compact(p.iri) for p in event.governed_by),
        route_policies=tuple(model.compact(p.iri) for p in op.governed_by),
        flow=_flow(model, _navigation(event)),
    )


def _task_forms(model: Model, presenter) -> tuple[TaskForm, ...]:
    """One TaskForm per ifml:Form some proc:UserTask seam:completedOn, by IRI."""
    found = {}
    for task in model.views.all(ProcessElement, PROC.UserTask):
        form = task.completed_on
        if form is None:
            continue
        if form.iri in found:
            raise GeneratorError(
                form.iri,
                SEAM.completedOn,
                f"completes both {found[form.iri][1].iri} and {task.iri}; expected one user task",
            )
        found[form.iri] = (form, task)
    return tuple(_task_form(model, *found[iri], presenter) for iri in sorted(found, key=str))


def _task_form(model: Model, form, task, presenter) -> TaskForm:
    if IFML.Form not in form.types:
        raise GeneratorError(task.iri, SEAM.completedOn, f"{form.iri} is not an ifml:Form")
    writes = only(form.writes, "the shape the task form submits")
    process = _task_process(model, task.iri)
    key = required(process.correlation_key, process.iri, PROC.correlationKey)

    def fill_key(var: str) -> str:
        if var != key:
            raise GeneratorError(
                process.iri,
                PROC.correlationKey,
                f"path variable {var!r} of the completion of {task.iri} is not the correlation key {key!r}",
            )
        return TASK_KEY

    submit = _submit(model, form, presenter, fill_key)
    if TASK_KEY not in submit.path:
        raise GeneratorError(
            process.iri,
            PROC.correlationKey,
            f"{key!r} is not a path variable of {submit.operation}, "
            f"so the completion of {task.iri} cannot name its instance",
        )
    fields = _fields(writes)
    bound = {local_name(p.bound_to): p.iri for p in form.parameter_bindings if p.bound_to is not None}
    by_name = {fl.name for fl in fields}
    unknown = sorted(set(bound) - by_name)
    if unknown:
        raise GeneratorError(
            bound[unknown[0]], IFML.boundTo, f"{unknown[0]!r} is not a datatype sh:path of {writes.iri}"
        )
    prefix = local_name(form.iri)
    if prefix.endswith("_form") and len(prefix) > len("_form"):
        prefix = prefix[: -len("_form")]
    reads = optional(task.reads)
    return TaskForm(
        name=f"{local_name(form.iri)}.html",
        id=local_name(form.iri),
        curie=model.compact(form.iri),
        label=label(model, form.iri),
        task=_task_curie(model, task.iri),
        task_label=label(model, task.iri),
        key=key,
        entity_class=label(model, reads.iri).lower() if reads is not None else None,
        entity_fields=_fields(reads) if reads is not None else (),
        submit=submit,
        inputs=tuple(_task_input(prefix, fl) for fl in fields if fl.name in bound),
        unbound=tuple(fl.name for fl in fields if fl.name not in bound),
    )


def _task_process(model: Model, task):
    """The ``model.processes`` Process whose seam:detailedBy BPMN model holds
    ``task`` (its IRI is <model>#<bpmn id>, or it is seam:inModel the model)."""
    element = model.views.resolve(URIRef(str(task)))
    models = {o for p, o in element.edges if p == SEAM.inModel}
    found = [
        p
        for p in model.processes
        if any(m in models or str(element.iri).startswith(f"{m}#") for pred, m in p.edges if pred == SEAM.detailedBy)
    ]
    if len(found) != 1:
        raise GeneratorError(
            element.iri,
            SEAM.detailedBy,
            f"expected one proc:Process seam:detailedBy the model holding the task, found {[str(p.iri) for p in found]}",
        )
    return found[0]


def _task_curie(model: Model, task) -> str:
    """``prefix:rest`` for the longest bound namespace, keeping the whole rest
    (``:approval_bpmn#approve_expense``), so that ``Model.curie`` expands it
    back to the task IRI; the plain ``Model.compact`` shortens a BPMN element
    to ``:id``, which would name a different, ungoverned IRI."""
    return model.compact(task, whole=True)


def _screen_components(model: Model, presenter, task_forms, built_ids, sse_channels) -> tuple[Component, ...]:
    """The components on a task form's screen (the ifml:ViewContainer that
    ifml:contains it) that an operation the presenter seam:consumes
    seam:rendersComponent, and the landmark page does not already hold, so
    that the completion route's partial is generated. Sorted by IRI."""
    rendered = {c.iri for op in presenter.consumes if isinstance(op, Operation) for c in op.renders}
    out = {}
    for tf in task_forms:
        form = model.views.intern(ComponentView, model.curie(tf.curie))
        for screen in form.screens:
            parts = screen.components()
            params = {name for c in parts for name in _parameters(model, c)}
            for c in parts:
                if c.iri in rendered and local_name(c.iri) not in built_ids and c.iri not in out:
                    out[c.iri] = _component(model, c, c.order or 0, presenter, params, sse_channels)
    return tuple(out[iri] for iri in sorted(out, key=str))


def _task_input(prefix: str, fl: Field) -> Input:
    """A task form field: an sh:in enumeration is a <select> of its values in
    list order; anything else is the page's ``_input``."""
    if not fl.options:
        return _input(prefix, fl)
    attributes = (f'name="{fl.name}"',) + (("required",) if fl.required else ())
    return Input(id=f"{prefix}_{fl.name}", name=fl.name, element="select", attributes=attributes, options=fl.options)


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
        variable_start_string="[[",
        variable_end_string="]]",
        block_start_string="[%",
        block_end_string="%]",
        comment_start_string="[#",
        comment_end_string="#]",
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=jinja2.StrictUndefined,
        autoescape=False,
    )
    env.filters["english_list"] = _english_list
    return env


def _english_list(items) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def render_page(page: PageModel) -> str:
    return _environment().get_template(TEMPLATE_NAME).render(page=page)


def render_fragments(page: PageModel) -> dict[str, str]:
    """{file name: text} for every partial in ``page.fragments``."""
    template = _environment().get_template(FRAGMENT_TEMPLATE_NAME)
    by_id = {c.id: c for c in page.components + page.screen_components}
    return {fr.name: template.render(page=page, fr=fr, c=by_id[fr.component]) for fr in page.fragments}


def render_task_forms(page: PageModel) -> dict[str, str]:
    """{file name: text} for every task form partial in ``page.task_forms``."""
    template = _environment().get_template(TASK_FORM_TEMPLATE_NAME)
    return {tf.name: template.render(page=page, t=tf) for tf in page.task_forms}


def generate_pages(model: Model) -> dict[str, str]:
    """{file name: text}: each page of ``model.interfaces.served_pages()`` as
    <page local name>.html with its partials (the landmark first, with its task
    form partials, then the others by IRI). Two pages naming the same partial
    must render it identically."""
    files: dict[str, str] = {}
    _landmark(model)  # no single landmark: GeneratorError on the interaction model
    for page in (extract_page(model, p.iri) for p in model.interfaces.served_pages()):
        rendered = {f"{page.id}.html": render_page(page), **render_fragments(page)}
        if page.landmark:
            rendered.update(render_task_forms(page))
        for name, text in rendered.items():
            if files.get(name, text) != text:
                raise GeneratorError(
                    model.curie(page.curie), IFML.contains, f"{name} would be generated twice with different content"
                )
            files[name] = text
    return files


def generate_page(trig_path) -> str:
    """Load the model and render its landmark page."""
    return render_page(extract_page(ModelGraph.load(trig_path)))


def generate_fragments(trig_path) -> dict[str, str]:
    """Load the model and render the partials its UIFragment operations name."""
    return render_fragments(extract_page(ModelGraph.load(trig_path)))


def generate_task_forms(trig_path) -> dict[str, str]:
    """Load the model and render the partial of each form a user task is completed on."""
    return render_task_forms(extract_page(ModelGraph.load(trig_path)))

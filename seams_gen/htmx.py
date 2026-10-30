"""The htmx page generator (M004/S04, D016).

``extract_page`` reads the landmark IFML ViewContainer and the seam, shape,
communication and lifecycle facts it touches into frozen dataclasses;
``generate_page`` renders them through templates/htmx_page.html.j2 and
``generate_fragments`` renders the partials the presenting container's
UIFragment operations name (GAP-19, D017) through htmx_fragment.html.j2, plus,
for each ``ifml:Form`` a ``proc:UserTask`` ``seam:completedOn`` (ADR-0009), a
task form partial through htmx_task_form.html.j2 and the partials of the
components its completion renders on the form's screen. ``generate_pages``
adds each ``seams.ModelGraph.secondary_pages`` page (an ``ifml:path`` and no task
form), extracted the same way and rendered with its own partials. The
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
from rdflib import RDF, XSD, Literal
from rdflib.collection import Collection
from rdflib.namespace import SH
from seams import COMM, HYDRA, IFML, PROC, SEAM, STATE, ModelGraph, local_name

from . import GeneratorError
from .facts import DASH
from .facts import Facts as _Facts
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
    landmark: bool = True  # False for a seams.ModelGraph.secondary_pages page


# ── graph helpers ───────────────────────────────────────────────────────────


def _shape_name(shape) -> str:
    """:MessageShape -> message (the seam:visibleWhen variable rule in seam.ttl)."""
    name = local_name(shape).lower()
    return name[: -len("shape")] if name.endswith("shape") and len(name) > 5 else name


def _fill(template: str, fill) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: "{{ " + fill(m.group(1)) + " }}", template)


# ── extraction ──────────────────────────────────────────────────────────────


def extract_page(model: ModelGraph, page=None) -> PageModel:
    """The landmark page, or ``page`` (one of ``seams.ModelGraph.secondary_pages``).
    Only the landmark's PageModel carries the task forms and their screens'
    components; a secondary page carries its own components and partials."""
    f = _Facts(model)
    landmark = page is None
    page = _landmark(f, model) if landmark else model.curie(page)
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
    # Runtime.page_context binds a correlation key only when a component that
    # seam:reads a shape is scoped by it; any other key in a submit path is new.
    keys = {f.label(p) for p in f.ds.objects(None, PROC.correlationKey)}
    bound_keys = {
        f.label(p) for _, c in components if f.objects(c, SEAM.reads) for p in f.objects(c, IFML.hasParameter)
    } & keys
    mintable = keys - bound_keys
    sse_channels = [
        ch
        for ch in f.objects(presenter, SEAM.consumes)
        if (ch, RDF.type, COMM.Channel) in f.ds and (ch, COMM.transport, COMM.SSE) in f.ds
    ]

    built = tuple(_component(f, c, order, presenter, page_params, sse_channels, mintable) for order, c in components)
    task_forms = _task_forms(f, presenter) if landmark else ()
    screens = _screen_components(f, presenter, task_forms, {c.id for c in built}, sse_channels)
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
        fragments=_fragments(f, presenter, {c.id for c in built + screens}),
        task_forms=task_forms,
        screen_components=screens,
        landmark=landmark,
    )


def _fragments(f: _Facts, presenter, component_ids) -> tuple[Fragment, ...]:
    """Every partial an operation the presenter seam:consumes renders onto a
    page component, grouped by file name and sorted by it."""
    found: dict[str, tuple[str, str, list]] = {}
    for op in f.objects(presenter, SEAM.consumes):
        if not f.objects(op, SEAM.rendersComponent):
            continue
        name, component, kind = fragment_for(f, op)
        if local_name(component) not in component_ids:
            continue
        found.setdefault(name, (local_name(component), kind, []))[2].append(f.curie(op))
    return tuple(
        Fragment(name=name, component=comp, kind=kind, operations=tuple(ops))
        for name, (comp, kind, ops) in sorted(found.items())
    )


def _landmark(f: _Facts, model: ModelGraph):
    containers = f.subjects(RDF.type, IFML.ViewContainer)
    landmarks = [c for c in containers if (c, IFML.isLandmark, Literal(True)) in f.ds]
    if len(landmarks) != 1:
        models = f.subjects(RDF.type, IFML.InteractionModel)
        subject = models[0] if len(models) == 1 else model.subject
        found = ", ".join(map(str, landmarks)) or "none"
        raise GeneratorError(
            subject,
            IFML.isLandmark,
            f"expected exactly one ifml:ViewContainer with ifml:isLandmark true, found {found}",
        )
    return landmarks[0]


def _interaction_model(f: _Facts, page):
    models = [m for m in f.subjects(IFML.contains, page) if (m, RDF.type, IFML.InteractionModel) in f.ds]
    if len(models) != 1:
        raise GeneratorError(
            page, IFML.contains, f"expected one ifml:InteractionModel containing the page, found {len(models)}"
        )
    return models[0]


def _presenter(f: _Facts, imodel):
    presenters = f.subjects(SEAM.presents, imodel)
    if len(presenters) != 1:
        raise GeneratorError(
            imodel, SEAM.presents, f"expected one container presenting the model, found {len(presenters)}"
        )
    return presenters[0]


def _component(f: _Facts, c, order, presenter, page_params, sse_channels, mintable=frozenset()) -> Component:
    types = [t for t in COMPONENT_TYPES if (c, RDF.type, t) in f.ds]
    if len(types) != 1:
        raise GeneratorError(c, RDF.type, f"expected one of {[f.curie(t) for t in COMPONENT_TYPES]}")
    ctype = types[0]
    reads = f.optional(c, SEAM.reads)
    writes = f.optional(c, SEAM.writes)
    guard_var = None
    guard_states: tuple[str, ...] = ()
    guard_curies: tuple[str, ...] = ()
    states = f.objects(c, SEAM.visibleWhen)
    if states:
        if reads is None:
            raise GeneratorError(c, SEAM.reads, "seam:visibleWhen needs the shape the component reads")
        machine = f.one(reads, SEAM.lifecycle, f"guard of {c}")
        for state in states:
            if (machine, STATE.hasState, state) not in f.ds:
                raise GeneratorError(machine, STATE.hasState, f"guard state {state} of {c} is not a state of it")
        guard_var = _shape_name(reads) + "_state"
        guard_states = tuple(sorted(f.label(state) for state in states))
        guard_curies = tuple(sorted(f.curie(state) for state in states))

    base = dict(
        id=local_name(c),
        curie=f.curie(c),
        kind=local_name(ctype),
        type_curie=f.curie(ctype),
        label=f.label(c),
        order=order,
        reads=f.curie(reads) if reads is not None else None,
        writes=f.curie(writes) if writes is not None else None,
        guard_variable=guard_var,
        guard_states=guard_states,
        guard_state_curies=guard_curies,
        parameters=tuple(sorted(f.label(p) for p in f.objects(c, IFML.hasParameter))),
    )

    def fill_param(var: str) -> str:
        if var not in page_params:
            raise GeneratorError(c, IFML.hasParameter, f"path variable {var!r} names no ifml:Parameter of the page")
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
        return Component(
            **base, collection=_shape_name(reads) + "s", loop_var="item", link=link, display_field=display[0]
        )

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
                raise GeneratorError(ch, SEAM.publishesTo, f"expected one publisher, found {len(publishers)}")
            template, _ = f.path_template(ch)
            stream = Stream(
                id=local_name(ch),
                curie=f.curie(ch),
                publisher=f.curie(publishers[0]),
                connect=_fill(template, fill_param),
                event_name=str(f.one(ch, COMM.eventName)),
            )
        name = _shape_name(reads)
        return Component(
            **base,
            collection=name + "s",
            loop_var=name,
            item_class=f.label(reads).lower(),
            fields=_fields(f, reads),
            stream=stream,
        )

    # ifml:Form
    if writes is None:
        raise GeneratorError(c, SEAM.writes, "an ifml:Form must write a shape")
    submit = _submit(f, c, presenter, fill_param, mintable)
    fields = _fields(f, writes)
    bound = {}
    for p in f.objects(c, IFML.hasParameter):
        target = f.optional(p, IFML.boundTo)
        if target is not None:
            bound[local_name(target)] = p
    by_name = {fl.name: fl for fl in fields}
    unknown = sorted(set(bound) - set(by_name))
    if unknown:
        raise GeneratorError(bound[unknown[0]], IFML.boundTo, f"{unknown[0]!r} is not a datatype sh:path of {writes}")
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
        members = f.optional(prop, SH["in"])
        options = tuple(str(v) for v in Collection(f.ds, members)) if members is not None else ()
        fields.append(
            Field(
                name=local_name(f.one(prop, SH.path)),
                kind=kind,
                order=f.int_value(prop, SH.order),
                max_length=f.int_value(prop, SH.maxLength),
                required=min_count is not None and min_count >= 1,
                options=options,
            )
        )
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
    flows = [fl for fl in f.subjects(IFML.source, event) if (fl, RDF.type, IFML.NavigationFlow) in f.ds]
    if len(flows) != 1:
        raise GeneratorError(event, IFML.source, f"expected one ifml:NavigationFlow from the event, found {len(flows)}")
    return flows[0]


def _list_link(f: _Facts, c) -> Link:
    event = f.one(c, IFML.hasEvent)
    flow_iri = _navigation(f, event)
    flow = _flow(f, flow_iri)
    target = f.one(flow_iri, IFML.target)
    reads_ops = [op for op in f.subjects(SEAM.rendersComponent, target) if str(f.optional(op, HYDRA.method)) == "GET"]
    if len(reads_ops) != 1:
        raise GeneratorError(
            target, SEAM.rendersComponent, f"expected one GET operation rendering {target}, found {len(reads_ops)}"
        )
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
                raise GeneratorError(
                    binding, IFML.targetParameter, f"{name!r} is not a path variable of {reads_ops[0]}"
                )
            vals.append((name, "item." + mappings[name]))
    return Link(event_trigger=str(f.one(event, IFML.trigger)), flow=flow, get_path=get_path, vals=tuple(sorted(vals)))


def _submit(f: _Facts, c, presenter, fill_param, mintable=frozenset()) -> Submit:
    events = [e for e in f.objects(c, IFML.hasEvent) if f.objects(e, SEAM.submitsTo)]
    if len(events) != 1:
        subject = f.objects(c, IFML.hasEvent)
        subject = subject[0] if len(subject) == 1 else c
        raise GeneratorError(
            subject,
            SEAM.submitsTo,
            f"expected one event of form {c} that seam:submitsTo an operation, found {len(events)}",
        )
    event = events[0]
    op = f.one(event, SEAM.submitsTo)
    if (presenter, SEAM.consumes, op) not in f.ds:
        raise GeneratorError(presenter, SEAM.consumes, f"the presenting container does not consume {op}")
    method = str(f.one(op, HYDRA.method))
    template, _ = f.path_template(op)
    variables = re.findall(r"\{(\w+)\}", template)
    mint = tuple(v for v in variables if v in mintable)
    for var in mint:
        fill_param(var)  # still a parameter of the page
    path = re.sub(
        r"\{(\w+)\}", lambda m: m.group(0) if m.group(1) in mint else "{{ " + fill_param(m.group(1)) + " }}", template
    )
    return Submit(
        event=f.curie(event),
        label=f.label(event),
        method=method.lower(),
        method_upper=method.upper(),
        path=path,
        operation=f.curie(op),
        mint=mint,
        media_kind=local_name(f.one(op, SEAM.mediaKind)),
        consumer=f.curie(presenter),
        triggers=tuple(f.curie(p) for p in f.objects(event, SEAM.triggers)),
        event_policies=tuple(f.curie(p) for p in f.objects(event, SEAM.governedBy)),
        route_policies=tuple(f.curie(p) for p in f.objects(op, SEAM.governedBy)),
        flow=_flow(f, _navigation(f, event)),
    )


def _task_forms(f: _Facts, presenter) -> tuple[TaskForm, ...]:
    """One TaskForm per ifml:Form some proc:UserTask seam:completedOn, by IRI."""
    found = {}
    for task, form in f.ds.subject_objects(SEAM.completedOn):
        if (task, RDF.type, PROC.UserTask) not in f.ds:
            continue
        if form in found:
            raise GeneratorError(
                form, SEAM.completedOn, f"completes both {found[form]} and {task}; expected one user task"
            )
        found[form] = task
    return tuple(_task_form(f, form, found[form], presenter) for form in sorted(found, key=str))


def _task_form(f: _Facts, form, task, presenter) -> TaskForm:
    if (form, RDF.type, IFML.Form) not in f.ds:
        raise GeneratorError(task, SEAM.completedOn, f"{form} is not an ifml:Form")
    writes = f.one(form, SEAM.writes, "the shape the task form submits")
    process = _task_process(f, task)
    key = f.label(f.one(process, PROC.correlationKey))

    def fill_key(var: str) -> str:
        if var != key:
            raise GeneratorError(
                process,
                PROC.correlationKey,
                f"path variable {var!r} of the completion of {task} is not the correlation key {key!r}",
            )
        return TASK_KEY

    submit = _submit(f, form, presenter, fill_key)
    if TASK_KEY not in submit.path:
        raise GeneratorError(
            process,
            PROC.correlationKey,
            f"{key!r} is not a path variable of {submit.operation}, "
            f"so the completion of {task} cannot name its instance",
        )
    fields = _fields(f, writes)
    bound = {
        local_name(t): p
        for p in f.objects(form, IFML.hasParameter)
        for t in [f.optional(p, IFML.boundTo)]
        if t is not None
    }
    by_name = {fl.name for fl in fields}
    unknown = sorted(set(bound) - by_name)
    if unknown:
        raise GeneratorError(bound[unknown[0]], IFML.boundTo, f"{unknown[0]!r} is not a datatype sh:path of {writes}")
    prefix = local_name(form)
    if prefix.endswith("_form") and len(prefix) > len("_form"):
        prefix = prefix[: -len("_form")]
    reads = f.optional(task, SEAM.reads)
    return TaskForm(
        name=f"{local_name(form)}.html",
        id=local_name(form),
        curie=f.curie(form),
        label=f.label(form),
        task=_task_curie(f, task),
        task_label=f.label(task),
        key=key,
        entity_class=f.label(reads).lower() if reads is not None else None,
        entity_fields=_fields(f, reads) if reads is not None else (),
        submit=submit,
        inputs=tuple(_task_input(prefix, fl) for fl in fields if fl.name in bound),
        unbound=tuple(fl.name for fl in fields if fl.name not in bound),
    )


def _task_process(f: _Facts, task):
    """The proc:Process whose seam:detailedBy BPMN model holds ``task`` (its
    IRI is <model>#<bpmn id>, or it is seam:inModel the model)."""
    models = set(f.objects(task, SEAM.inModel))
    found = [
        p
        for p in f.subjects(RDF.type, PROC.Process)
        if any(m in models or str(task).startswith(f"{m}#") for m in f.objects(p, SEAM.detailedBy))
    ]
    if len(found) != 1:
        raise GeneratorError(
            task,
            SEAM.detailedBy,
            f"expected one proc:Process seam:detailedBy the model holding the task, found {[str(p) for p in found]}",
        )
    return found[0]


def _task_curie(f: _Facts, task) -> str:
    """``prefix:rest`` for the longest bound namespace, keeping the whole rest
    (``:approval_bpmn#approve_expense``), so that seams.ModelGraph.curie expands it
    back to the task IRI; Facts.curie shortens a BPMN element to ``:id``,
    which would name a different, ungoverned IRI."""
    s = str(task)
    for ns, prefix in f._ns:
        if s.startswith(ns):
            return f"{prefix}:{s[len(ns) :]}"
    return s


def _screen_components(f: _Facts, presenter, task_forms, built_ids, sse_channels) -> tuple[Component, ...]:
    """The components on a task form's screen (the ifml:ViewContainer that
    ifml:contains it) that an operation the presenter seam:consumes
    seam:rendersComponent, and the landmark page does not already hold, so
    that the completion route's partial is generated. Sorted by IRI."""
    rendered = {c for op in f.objects(presenter, SEAM.consumes) for c in f.objects(op, SEAM.rendersComponent)}
    out = {}
    for tf in task_forms:
        form = f.m.curie(tf.curie)
        for screen in f.subjects(IFML.contains, form):
            if (screen, RDF.type, IFML.ViewContainer) not in f.ds:
                continue
            params = {f.label(p) for c in f.objects(screen, IFML.contains) for p in f.objects(c, IFML.hasParameter)}
            for c in f.objects(screen, IFML.contains):
                if c in rendered and local_name(c) not in built_ids and c not in out:
                    out[c] = _component(f, c, f.int_value(c, IFML.order) or 0, presenter, params, sse_channels)
    return tuple(out[c] for c in sorted(out, key=str))


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


def generate_pages(model: ModelGraph) -> dict[str, str]:
    """{file name: text}: the landmark page as <page local name>.html with
    its partials and task form partials, then each secondary page and its
    partials. Two pages naming the same partial must render it identically."""
    files: dict[str, str] = {}
    for page in [extract_page(model)] + [extract_page(model, p) for p in model.secondary_pages()]:
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

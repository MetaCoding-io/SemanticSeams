"""IFML diagram projection (M006/S05, D011), drawn on diagram-js (M007/S04, D023).

ifml_diagram() reads an IFML model through the seams library's
model.interfaces view (M010/S06), the view the htmx generator reads, so IFML
has one interpretation; it returns a dict that already has the IFML derivations and the geometry worked out, so the client
only draws and pytest can check everything (ifml_elk_graph() carries it to the
diagram-js canvas as a fixed ELK graph):

- containers (ifml:ViewContainer) with [L]/[XOR]/[D] markers, nested by
  ifml:contains;
- components (ifml:List/Details/Form) with a «DataBinding» strip per
  seam:reads/seam:writes shape, and, for forms, «SimpleField» rows taken only
  from the sh:property paths of the shape the form writes;
- events (ifml:Event, owned through ifml:hasEvent) as circles on their
  owner's right border;
- actions: one hexagon per distinct seam:triggers target of an event;
- navigation flows (solid), data flows (dashed, with a «ParamBindingGroup»
  note) and event → action flows;
- activation notes "[state = …]" from seam:visibleWhen, one per container
  or component ("[state in (…)]" when it has several guard states).

A flow without exactly one ifml:source and ifml:target, a parameter binding
without both parameters, or a form shape property without an IRI sh:path
raises seams.ResolutionError naming the subject and predicate, as in the
generators.

Geometry is deterministic and Python-only (no ELK): every box carries integer
x, y, w, h and the root carries the overall width and height. The loaded
model and the label/layer/seam helpers come from viewer.app through a late import, because viewer.app
imports this module.
"""

from __future__ import annotations

from rdflib import XSD, URIRef
from seams import IFML

STEREOTYPES = {IFML.List: "«List»", IFML.Details: "«Details»", IFML.Form: "«Form»"}
# seams Page flags (ifml:isLandmark, ifml:isXOR, ifml:isDefault) and their markers.
MARKERS = [("is_landmark", "[L]"), ("is_xor", "[XOR]"), ("is_default", "[D]")]
FIELD_KINDS = {
    XSD.string: "text",
    XSD.dateTime: "datetime",
    XSD.integer: "number",
    XSD.decimal: "number",
    XSD.boolean: "boolean",
}

# Geometry constants (px).
MARGIN = 20
PAD = 20
BOTTOM_PAD = 36  # leaves room for flows routed under a row
TITLE_H = 28
NOTE_H = 28
NOTE_ROW = 36
COMP_W = 200
COMP_HEADER = 44  # stereotype line + name line
BIND_ROW = 22
FIELD_ROW = 20
COMP_BOTTOM = 10
GAP = 90
EVENT_R = 8
EVENT_TOP = 30
EVENT_STEP = 28
ACTION_GAP = 80
ACTION_W = 180
ACTION_H = 48
ACTION_STEP = 12
CHAR_W = 7


def _app():
    from viewer import app

    return app


def _base(iri: str) -> dict:
    app = _app()
    return {"iri": iri, "label": app.label(iri), "layer": app.layer_of(iri), "seams": app.card_seams(iri)}


def _note_w(text: str) -> int:
    return len(text) * CHAR_W + 16


def _derive(model_iri: str) -> dict:
    app = _app()
    ui = app.get_model().interfaces
    scope = URIRef(model_iri)

    def in_scope(e) -> bool:
        return e.in_model(scope)

    pages = ui.pages().where(in_scope)
    # Only the concrete List/Details/Form classes have a stereotype to draw
    # (seams RENDERED_TYPES, what the generators render); a bare
    # ifml:ViewComponent is left out, as before.
    parts = ui.components().where(lambda c: in_scope(c) and bool(c.types))
    containers = {str(p.iri): _base(str(p.iri)) for p in pages}
    components = {str(c.iri): {**_base(str(c.iri)), "stereotype": STEREOTYPES[c.types[0]]} for c in parts}

    def parent(screens) -> str | None:
        # The first (minimum IRI) container of this model that contains it.
        return next((str(p.iri) for p in screens if str(p.iri) in containers), None)

    for p in pages:
        markers = [m for attr, m in MARKERS if getattr(p, attr)]
        c = containers[str(p.iri)]
        c.update(parent=parent(p.parents), markers=markers, title=" ".join(markers + [c["label"]]))

    for comp in parts:
        bindings = [
            {"shape": str(s.iri), "label": f"«DataBinding» {app.label(str(s.iri))}", "predicate": pred}
            for shapes, pred in ((comp.reads, "seam:reads"), (comp.writes, "seam:writes"))
            for s in shapes
        ]
        bindings.sort(key=lambda b: (b["shape"], b["predicate"]))
        fields = []
        if comp.types[0] == IFML.Form:
            for shape in comp.writes:
                for f in shape.fields():
                    fields.append(
                        {
                            "iri": str(f.iri),
                            "path": app.qname(f.iri),
                            "name": f.name,
                            "kind": FIELD_KINDS.get(f.datatype, "field"),
                            "label": f"«SimpleField» {f.name}",
                        }
                    )
            fields.sort(key=lambda f: f["iri"])
        components[str(comp.iri)].update(parent=parent(comp.screens), bindings=bindings, fields=fields)

    triggers: dict[str, list[str]] = {}
    owners: dict[str, str] = {}
    for ev in ui.events().where(in_scope):
        if ev.owners:
            owners[str(ev.iri)] = str(ev.owners[0].iri)
            triggers[str(ev.iri)] = [str(t) for t in ev.triggers_all.iris()]
    action_iris = sorted({t for ts in triggers.values() for t in ts})

    # Flow.source/target and Flow.binds raise ResolutionError on a flow or
    # binding without exactly one end: the htmx generator's rule.
    flows_in = ui.flows().where(in_scope)
    nav = [f for f in flows_in if f.kind == IFML.NavigationFlow]
    data = [f for f in flows_in if f.kind == IFML.DataFlow]

    # An event is "system" when a navigation flow leaves it and it belongs to
    # an action (it signals the action's completion); otherwise it is "user".
    nav_sources = {str(f.source.iri) for f in nav}
    events = {}
    for ev, owner in owners.items():
        system = ev in nav_sources and owner in action_iris
        events[ev] = {**_base(ev), "owner": owner, "kind": "system" if system else "user", "triggers": triggers[ev]}

    flows = []
    for f in nav:
        ends = {"from": str(f.source.iri), "to": str(f.target.iri)}
        flows.append({**_base(str(f.iri)), "kind": "navigation", **ends, "bindings": []})
    for f in data:
        ends = {"from": str(f.source.iri), "to": str(f.target.iri)}
        bindings = sorted(f"{app.label(str(b.source))} → {app.label(str(b.target))}" for b in f.binds)
        flows.append({**_base(str(f.iri)), "kind": "data", **ends, "bindings": bindings})
    for ev in sorted(triggers):
        for proc in triggers[ev]:
            flows.append(
                {
                    "iri": None,
                    "label": app.label(proc),
                    "layer": app.layer_of(proc),
                    "seams": [],
                    "kind": "action",
                    "from": ev,
                    "to": proc,
                    "bindings": [],
                }
            )

    notes = []
    guards = {str(b.iri): [str(s) for s in b.visible_when.iris()] for b in (*pages, *parts) if b.visible_when}
    for s, states in sorted(guards.items()):
        labels = sorted(app.label(o) for o in states)
        text = f"[state = {labels[0]}]" if len(labels) == 1 else f"[state in ({', '.join(labels)})]"
        notes.append({"iri": states[0], "kind": "activation", "for": s, "state": states[0], "text": text})
    for f in flows:
        if f["kind"] == "data" and f["bindings"]:
            text = "«ParamBindingGroup» " + "; ".join(f["bindings"])
            notes.append({"iri": f["iri"], "kind": "bindings", "for": f["iri"], "state": None, "text": text})

    actions = {a: {**_base(a)} for a in action_iris}
    return {
        "containers": containers,
        "components": components,
        "events": events,
        "actions": actions,
        "flows": flows,
        "notes": notes,
    }


def _rank_children(children: list[str], d: dict, ancestor_in) -> list[str]:
    """Order a row: sources of data/navigation flows before their targets,
    ties by label then iri. Longest-path rank with a cycle guard."""
    edges = set()
    for f in d["flows"]:
        if f["kind"] == "action":
            continue
        src = d["events"][f["from"]]["owner"] if f["from"] in d["events"] else f["from"]
        a, b = ancestor_in(src), ancestor_in(f["to"])
        if a and b and a != b:
            edges.add((a, b))
    rank = {c: 0 for c in children}
    for _ in range(len(children)):
        changed = False
        for a, b in sorted(edges):
            if rank[b] < rank[a] + 1 and rank[a] + 1 < len(children):
                rank[b] = rank[a] + 1
                changed = True
        if not changed:
            break
    labels = {**d["containers"], **d["components"]}
    return sorted(children, key=lambda c: (rank[c], labels[c]["label"], c))


def _layout(d: dict) -> tuple[int, int]:
    boxes = {**d["containers"], **d["components"]}
    kids: dict[str | None, list[str]] = {}
    for iri, b in boxes.items():
        kids.setdefault(b["parent"], []).append(iri)

    def ancestors(iri: str) -> list[str]:
        chain = [iri]
        while boxes.get(chain[-1], {}).get("parent"):
            chain.append(boxes[chain[-1]]["parent"])
        return chain

    def ancestor_in(siblings: list[str]):
        sset = set(siblings)

        def find(iri: str) -> str | None:
            return next((a for a in ancestors(iri) if a in sset), None) if iri in boxes else None

        return find

    events_of: dict[str, list[str]] = {}
    for ev, e in sorted(d["events"].items()):
        events_of.setdefault(e["owner"], []).append(ev)

    def comp_h(c: dict) -> int:
        body = COMP_HEADER + BIND_ROW * len(c["bindings"]) + FIELD_ROW * len(c["fields"]) + COMP_BOTTOM
        n = len(events_of.get(c["iri"], []))
        return max(body, EVENT_TOP + EVENT_STEP * n)

    # Notes that sit above an element or flow inside a container need a band;
    # the band height is decided after placement, so a first pass sizes boxes
    # and a second pass fixes the band per container.
    note_rows: dict[str, int] = {}

    def place(iri: str, x: int, y: int) -> None:
        b = boxes[iri]
        b["x"], b["y"] = x, y
        if iri in d["components"]:
            b["w"], b["h"] = COMP_W, comp_h(b)
            return
        row = _rank_children(kids.get(iri, []), d, ancestor_in(kids.get(iri, [])))
        b["children"] = row
        top = y + TITLE_H + note_rows.get(iri, 0) * NOTE_ROW + PAD
        cx = x + PAD
        bottom = top
        for child in row:
            place(child, cx, top)
            cx += boxes[child]["w"] + GAP
            bottom = max(bottom, top + boxes[child]["h"])
        inner_w = (cx - GAP - (x + PAD)) if row else COMP_W
        b["w"] = max(inner_w + 2 * PAD, len(b["title"]) * CHAR_W + 2 * PAD)
        b["h"] = (bottom - y) + BOTTOM_PAD if row else TITLE_H + PAD + BOTTOM_PAD

    roots = _rank_children(kids.get(None, []), d, ancestor_in(kids.get(None, [])))

    def place_roots() -> int:
        x = MARGIN
        for r in roots:
            place(r, x, MARGIN)
            x += boxes[r]["w"] + GAP
        return x - GAP if roots else MARGIN

    place_roots()
    _place_events(d, events_of)
    _route_flows(d, boxes)
    # Assign note rows per container, then re-place with the bands.
    note_rows.update(_note_rows(d, boxes))
    right = place_roots()
    _place_events(d, events_of)
    _route_flows(d, boxes)
    _place_notes(d, boxes)

    # Actions: a column right of the outermost containers, aligned with the
    # triggering event's y, pushed down when two would overlap.
    ax = right + ACTION_GAP
    next_free = MARGIN
    for a in sorted(d["actions"]):
        ys = [d["events"][f["from"]]["cy"] for f in d["flows"] if f["kind"] == "action" and f["to"] == a]
        cy = min(ys) if ys else next_free + ACTION_H // 2
        y = max(cy - ACTION_H // 2, next_free)
        act = d["actions"][a]
        act.update(x=ax, y=y, w=ACTION_W, h=ACTION_H)
        act["points"] = _hexagon(act)
        next_free = y + ACTION_H + ACTION_STEP
    _route_action_flows(d)

    width = max([right] + [a["x"] + a["w"] for a in d["actions"].values()]) + MARGIN
    height = (
        max([MARGIN] + [b["y"] + b["h"] for b in boxes.values()] + [a["y"] + a["h"] for a in d["actions"].values()])
        + MARGIN
    )
    return width, height


def _place_events(d: dict, events_of: dict) -> None:
    boxes = {**d["containers"], **d["components"]}
    for owner, evs in events_of.items():
        b = boxes.get(owner)
        for i, ev in enumerate(evs):
            e = d["events"][ev]
            if b is None:  # owner is not drawn (e.g. an action); placed with actions
                e.update(cx=0, cy=0, r=EVENT_R)
            else:
                e.update(cx=b["x"] + b["w"], cy=b["y"] + EVENT_TOP + EVENT_STEP * i, r=EVENT_R)
            e.update(x=e["cx"] - EVENT_R, y=e["cy"] - EVENT_R, w=2 * EVENT_R, h=2 * EVENT_R)


def _route_flows(d: dict, boxes: dict) -> None:
    for f in d["flows"]:
        if f["kind"] == "action":
            continue
        tgt = boxes.get(f["to"])
        if f["from"] in d["events"]:
            e = d["events"][f["from"]]
            start, src_box = (e["cx"] + e["r"], e["cy"]), boxes.get(e["owner"])
        else:
            src_box = boxes.get(f["from"])
            start = None
        if tgt is None or src_box is None:
            f["points"] = []
            continue
        if start is None:
            # Data flows leave the source's right border low down, below the events.
            sy = min(src_box["y"] + src_box["h"], tgt["y"] + tgt["h"]) - 16
            start = (src_box["x"] + src_box["w"], sy)
        sx, sy = start
        if tgt["x"] >= sx and tgt["y"] <= sy <= tgt["y"] + tgt["h"]:
            f["points"] = [[sx, sy], [tgt["x"], sy]]
        else:
            # Route under the row and come up into the target's bottom border.
            low = max(src_box["y"] + src_box["h"], tgt["y"] + tgt["h"]) + BOTTOM_PAD // 2
            tx = tgt["x"] + tgt["w"] // 2
            f["points"] = [[sx, sy], [sx + GAP // 3, sy], [sx + GAP // 3, low], [tx, low], [tx, tgt["y"] + tgt["h"]]]


def _route_action_flows(d: dict) -> None:
    for f in d["flows"]:
        if f["kind"] != "action":
            continue
        e, a = d["events"][f["from"]], d["actions"][f["to"]]
        sx, sy = e["cx"] + e["r"], e["cy"]
        ay = a["y"] + a["h"] // 2
        mid = a["x"] - ACTION_GAP // 2
        blockers = [
            b
            for iri, b in d["components"].items()
            if iri != e["owner"] and b["x"] + b["w"] > sx and b["x"] < a["x"] and b["y"] <= sy <= b["y"] + b["h"]
        ]
        if blockers:
            # A straight line would cross sibling components: drop under the
            # row (inside the container's bottom padding) and run across.
            low = max(b["y"] + b["h"] for b in d["components"].values()) + BOTTOM_PAD // 2
            step = sx + GAP // 3
            f["points"] = [[sx, sy], [step, sy], [step, low], [mid, low], [mid, ay], [a["x"], ay]]
        elif sy == ay:
            f["points"] = [[sx, sy], [a["x"], ay]]
        else:
            f["points"] = [[sx, sy], [mid, sy], [mid, ay], [a["x"], ay]]


def _hexagon(a: dict) -> list[list[int]]:
    x, y, w, h = a["x"], a["y"], a["w"], a["h"]
    k = h // 2
    return [[x + k, y], [x + w - k, y], [x + w, y + k], [x + w - k, y + h], [x + k, y + h], [x, y + k]]


def _note_anchor(n: dict, d: dict, boxes: dict) -> tuple[str | None, int]:
    """(container that holds the note, anchor centre x)."""
    if n["kind"] == "activation":
        b = boxes[n["for"]]
        return b.get("parent"), b["x"] + b["w"] // 2
    f = next(f for f in d["flows"] if f["iri"] == n["for"])
    pts = f.get("points") or [[0, 0]]
    mx = (pts[0][0] + pts[-1][0]) // 2
    src = d["events"][f["from"]]["owner"] if f["from"] in d["events"] else f["from"]
    return boxes.get(src, {}).get("parent"), mx


def _note_spans(d: dict, boxes: dict) -> list[tuple[dict, str | None, int, int]]:
    spans = []
    for n in sorted(d["notes"], key=lambda n: (n["iri"], n["for"])):
        holder, cx = _note_anchor(n, d, boxes)
        w = _note_w(n["text"])
        x = cx - w // 2
        if holder in boxes:
            hb = boxes[holder]
            x = max(hb["x"] + PAD, min(x, hb["x"] + hb["w"] - PAD - w))
        spans.append((n, holder, max(x, MARGIN), w))
    return spans


def _note_rows(d: dict, boxes: dict) -> dict[str, int]:
    """Greedy row assignment per container so notes never overlap sideways."""
    rows: dict[str | None, list[list[tuple[int, int]]]] = {}
    out: dict[str, int] = {}
    for n, holder, x, w in _note_spans(d, boxes):
        lanes = rows.setdefault(holder, [])
        for i, lane in enumerate(lanes):
            if all(x + w + 8 <= lx or lx + lw + 8 <= x for lx, lw in lane):
                lane.append((x, w))
                n["_row"] = i
                break
        else:
            lanes.append([(x, w)])
            n["_row"] = len(lanes) - 1
        if holder is not None:
            out[holder] = len(lanes)
    return out


def _place_notes(d: dict, boxes: dict) -> None:
    for n, holder, x, w in _note_spans(d, boxes):
        row = n.pop("_row", 0)
        hb = boxes.get(holder)
        band_top = (hb["y"] + TITLE_H) if hb else MARGIN
        n.update(x=x, y=band_top + 4 + row * NOTE_ROW, w=w, h=NOTE_H)
        if n["kind"] == "activation":
            b = boxes[n["for"]]
            n["connector"] = [[b["x"] + b["w"] // 2, n["y"] + NOTE_H], [b["x"] + b["w"] // 2, b["y"]]]
        else:
            f = next(f for f in d["flows"] if f["iri"] == n["for"])
            pts = f.get("points") or [[x, n["y"] + NOTE_H]]
            mx = (pts[0][0] + pts[-1][0]) // 2
            my = (pts[0][1] + pts[-1][1]) // 2
            n["connector"] = [[mx, n["y"] + NOTE_H], [mx, my]]


def ifml_diagram(model_iri: str) -> dict:
    """Derived IFML diagram (elements + integer geometry) for one IFML model."""
    app = _app()
    d = _derive(model_iri)
    width, height = _layout(d)

    def by_iri(items) -> list[dict]:
        return sorted(items, key=lambda i: i["iri"])

    for c in d["components"].values():
        c["events"] = sorted(ev for ev, e in d["events"].items() if e["owner"] == c["iri"])
    for c in d["containers"].values():
        c["events"] = sorted(ev for ev, e in d["events"].items() if e["owner"] == c["iri"])
    return {
        "model": model_iri,
        "label": app.label(model_iri),
        "layer": app.layer_of(model_iri),
        "width": int(width),
        "height": int(height),
        "containers": by_iri(d["containers"].values()),
        "components": by_iri(d["components"].values()),
        "events": by_iri(d["events"].values()),
        "actions": by_iri(d["actions"].values()),
        "flows": sorted(d["flows"], key=lambda f: (f["iri"] or "", f["kind"], f["from"], f["to"])),
        "notes": sorted(d["notes"], key=lambda n: (n["iri"], n["for"])),
    }


# --- ELK port graph (M007/S04, D023) ----------------------------------------

_FIXED = {
    "elk.algorithm": "fixed",
    "elk.padding": "[top=0,left=0,bottom=0,right=0]",
    "elk.nodeSize.fixedGraphSize": True,
}


def _note_layer(n: dict, owners: dict) -> str:
    """Same rule as the M006/S05 template: an activation note takes the layer
    of the owner's seam that targets its state, else lifecycle; a bindings
    note is interaction."""
    if n["kind"] != "activation":
        return "interaction"
    owner = owners.get(n["for"]) or {}
    seam = next((s for s in owner.get("seams", []) if s.get("target") == n["state"]), None)
    return seam["targetLayer"] if seam else "lifecycle"


def ifml_elk_graph(diagram: dict) -> dict:
    """Carry the ifml_diagram() geometry as an elkjs graph for the diagram-js
    canvas: {"elk": <root node>, "elements": {id: draw data}}.

    Every node uses the "fixed" algorithm, so ELK keeps the Python positions:
    containers and components nest under their parent container with x/y
    relative to it, actions and notes are root children at absolute x/y, and
    events are FIXED_POS ports on their owner's east border. Flows are root
    edges whose single section follows the Python points. Compound nodes and
    the root set elk.nodeSize.fixedGraphSize: without it ELK "fixed"
    shrink-wraps them to their children's bounding box (M007/S05).

    Note: an event whose owner is not drawn (an action; _place_events gives
    it cx = cy = 0) has no box to sit on, so it is left out of the ports and
    of the elements map. Flows with no points, or whose end is not drawn,
    are skipped too, so ELK never sees a dangling edge.
    """
    boxes = {b["iri"]: b for b in diagram["containers"] + diagram["components"]}
    containers = {c["iri"] for c in diagram["containers"]}
    elements: dict[str, dict] = {}

    def base(kind: str, el: dict, **extra) -> dict:
        return {
            "kind": kind,
            "iri": el["iri"],
            "label": el["label"],
            "layer": el["layer"],
            "seams": el["seams"],
            **extra,
        }

    ports_of: dict[str, list[dict]] = {}
    for e in diagram["events"]:
        owner = boxes.get(e["owner"])
        if owner is None:
            continue
        ports_of.setdefault(e["owner"], []).append(
            {
                "id": e["iri"],
                "x": e["cx"] - e["r"] - owner["x"],
                "y": e["cy"] - e["r"] - owner["y"],
                "width": 2 * e["r"],
                "height": 2 * e["r"],
                "layoutOptions": {"elk.port.side": "EAST"},
            }
        )
        elements[e["iri"]] = base("event", e, eventKind=e["kind"], owner=e["owner"], r=e["r"])

    def node(b: dict, parent: dict | None) -> dict:
        n = {
            "id": b["iri"],
            "x": b["x"] - (parent["x"] if parent else 0),
            "y": b["y"] - (parent["y"] if parent else 0),
            "width": b["w"],
            "height": b["h"],
            "layoutOptions": dict(_FIXED),
        }
        if b["iri"] in containers:
            kids = sorted(i for i, k in boxes.items() if k.get("parent") == b["iri"])
            n["children"] = [node(boxes[k], b) for k in kids]
            elements[b["iri"]] = base("container", b, title=b["title"], markers=b["markers"])
        else:
            elements[b["iri"]] = base(
                "component", b, stereotype=b["stereotype"], bindings=b["bindings"], fields=b["fields"]
            )
        if b["iri"] in ports_of:
            n["ports"] = sorted(ports_of[b["iri"]], key=lambda p: p["id"])
            n["layoutOptions"]["elk.portConstraints"] = "FIXED_POS"
        return n

    children = [node(b, None) for b in diagram["containers"] if b["parent"] is None]

    for a in diagram["actions"]:
        children.append({"id": a["iri"], "x": a["x"], "y": a["y"], "width": a["w"], "height": a["h"]})
        elements[a["iri"]] = base("action", a, points=[[px - a["x"], py - a["y"]] for px, py in a["points"]])

    owners = {**boxes}
    for n in diagram["notes"]:
        nid = f"note::{n['kind']}::{n['for']}"
        children.append({"id": nid, "x": n["x"], "y": n["y"], "width": n["w"], "height": n["h"]})
        elements[nid] = {
            "kind": "note",
            "iri": n["iri"],
            "label": n["text"],
            "layer": _note_layer(n, owners),
            "seams": [],
            "noteKind": n["kind"],
            "text": n["text"],
            "for": n["for"],
            "connector": n["connector"],
        }

    drawn = set(elements)
    edges = []
    for f in diagram["flows"]:
        pts = f.get("points") or []
        if not pts or f["from"] not in drawn or f["to"] not in drawn:
            continue
        fid = f["iri"] or f"flow::action::{f['from']}::{f['to']}"
        edges.append(
            {
                "id": fid,
                "sources": [f["from"]],
                "targets": [f["to"]],
                "sections": [
                    {
                        "id": f"{fid}::s0",
                        "startPoint": {"x": pts[0][0], "y": pts[0][1]},
                        "bendPoints": [{"x": x, "y": y} for x, y in pts[1:-1]],
                        "endPoint": {"x": pts[-1][0], "y": pts[-1][1]},
                    }
                ],
            }
        )
        elements[fid] = {
            "kind": "flow",
            "iri": f["iri"] or f["to"],
            "label": f["label"],
            "layer": f["layer"],
            "seams": f["seams"],
            "flowKind": f["kind"],
            "bindings": f["bindings"],
            "points": pts,
        }

    return {
        "elk": {
            "id": "root",
            "x": 0,
            "y": 0,
            "width": diagram["width"],
            "height": diagram["height"],
            "layoutOptions": dict(_FIXED),
            "children": sorted(children, key=lambda c: c["id"]),
            "edges": sorted(edges, key=lambda e: e["id"]),
        },
        "elements": elements,
    }

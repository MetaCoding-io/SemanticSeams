"""IFML diagram projection for server-side SVG (M006/S05, D011).

ifml_diagram() reads an IFML model out of the graph and returns a dict that
already has the IFML derivations and the geometry worked out, so the Jinja
template only draws and pytest can check everything:

- containers (ifml:ViewContainer) with [L]/[XOR]/[D] markers, nested by
  ifml:contains;
- components (ifml:List/Details/Form) with a «DataBinding» strip per
  seam:reads/seam:writes shape, and, for forms, «SimpleField» rows taken only
  from the sh:property paths of the shape the form writes;
- events (ifml:hasEvent) as circles on their owner's right border;
- actions: one hexagon per distinct seam:triggers target of an event;
- navigation flows (solid), data flows (dashed, with a «ParamBindingGroup»
  note) and event → action flows;
- activation notes "[state = …]" from seam:visibleWhen.

Geometry is deterministic and Python-only (no ELK): every box carries integer
x, y, w, h and the root carries the overall width and height. The graph
helpers come from viewer.app through a late import, because viewer.app
imports this module.
"""

from __future__ import annotations

from rdflib import RDF, XSD, Namespace, URIRef
from rdflib.namespace import SH

IFML = Namespace("https://w3id.org/seams/ifml#")
SEAM = Namespace("https://w3id.org/seams/seam#")

STEREOTYPES = {IFML.List: "«List»", IFML.Details: "«Details»", IFML.Form: "«Form»"}
MARKERS = [(IFML.isLandmark, "[L]"), (IFML.isXOR, "[XOR]"), (IFML.isDefault, "[D]")]
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


def _true(graph, s, p) -> bool:
    val = graph.value(s, p)
    return val is not None and bool(val.toPython()) is True


def _base(iri: str) -> dict:
    app = _app()
    return {"iri": iri, "label": app.label(iri), "layer": app.layer_of(iri), "seams": app.card_seams(iri)}


def _note_w(text: str) -> int:
    return len(text) * CHAR_W + 16


def _derive(model_iri: str) -> dict:
    app = _app()
    graph = app.get_graph()
    members = sorted(app.model_members(model_iri))

    def typed(cls) -> list[str]:
        return [m for m in members if (URIRef(m), RDF.type, cls) in graph]

    containers = {m: _base(m) for m in typed(IFML.ViewContainer)}
    components = {}
    for m in members:
        stereo = next((s for cls, s in STEREOTYPES.items() if (URIRef(m), RDF.type, cls) in graph), None)
        if stereo is not None:
            components[m] = {**_base(m), "stereotype": stereo}
    boxes = set(containers) | set(components)

    parents: dict[str, str] = {}
    for s, o in graph.subject_objects(IFML.contains):
        if str(s) in containers and str(o) in boxes:
            parents[str(o)] = min(parents.get(str(o), str(s)), str(s))

    for iri, c in containers.items():
        markers = [m for p, m in MARKERS if _true(graph, URIRef(iri), p)]
        c.update(parent=parents.get(iri), markers=markers, title=" ".join(markers + [c["label"]]))

    for iri, c in components.items():
        subj = URIRef(iri)
        bindings = [
            {"shape": str(o), "label": f"«DataBinding» {app.label(str(o))}", "predicate": pred}
            for p, pred in ((SEAM.reads, "seam:reads"), (SEAM.writes, "seam:writes"))
            for o in graph.objects(subj, p)
        ]
        bindings.sort(key=lambda b: (b["shape"], b["predicate"]))
        fields = []
        if c["stereotype"] == "«Form»":
            for shape in sorted(str(o) for o in graph.objects(subj, SEAM.writes)):
                for prop in graph.objects(URIRef(shape), SH.property):
                    path = graph.value(prop, SH.path)
                    if path is None:
                        continue
                    name = app.short_name(str(path))
                    kind = FIELD_KINDS.get(graph.value(prop, SH.datatype), "field")
                    fields.append(
                        {
                            "iri": str(path),
                            "path": app.qname(path),
                            "name": name,
                            "kind": kind,
                            "label": f"«SimpleField» {name}",
                        }
                    )
            fields.sort(key=lambda f: f["iri"])
        c.update(parent=parents.get(iri), bindings=bindings, fields=fields)

    triggers: dict[str, list[str]] = {}
    owners: dict[str, str] = {}
    for s, o in graph.subject_objects(IFML.hasEvent):
        if str(o) in members:
            owners[str(o)] = min(owners.get(str(o), str(s)), str(s))
    for ev in owners:
        triggers[ev] = sorted(str(t) for t in graph.objects(URIRef(ev), SEAM.triggers))
    action_iris = sorted({t for ts in triggers.values() for t in ts})

    def flows_of(cls) -> list[tuple[str, str, str]]:
        out = []
        for f in typed(cls):
            src = graph.value(URIRef(f), IFML.source)
            tgt = graph.value(URIRef(f), IFML.target)
            if src is not None and tgt is not None:
                out.append((f, str(src), str(tgt)))
        return out

    nav = flows_of(IFML.NavigationFlow)
    data = flows_of(IFML.DataFlow)

    # An event is "system" when a navigation flow leaves it and it belongs to
    # an action (it signals the action's completion); otherwise it is "user".
    nav_sources = {src for _, src, _ in nav}
    events = {}
    for ev, owner in owners.items():
        system = ev in nav_sources and owner in action_iris
        events[ev] = {**_base(ev), "owner": owner, "kind": "system" if system else "user", "triggers": triggers[ev]}

    flows = []
    for f, src, tgt in nav:
        flows.append({**_base(f), "kind": "navigation", "from": src, "to": tgt, "bindings": []})
    for f, src, tgt in data:
        bindings = []
        for b in graph.objects(URIRef(f), IFML.binds):
            sp = graph.value(b, IFML.sourceParameter)
            tp = graph.value(b, IFML.targetParameter)
            if sp is not None and tp is not None:
                bindings.append(f"{app.label(str(sp))} → {app.label(str(tp))}")
        flows.append({**_base(f), "kind": "data", "from": src, "to": tgt, "bindings": sorted(bindings)})
    for ev in sorted(triggers):
        for proc in triggers[ev]:
            flows.append(
                {"iri": None, "label": app.label(proc), "layer": app.layer_of(proc), "seams": [],
                 "kind": "action", "from": ev, "to": proc, "bindings": []}
            )

    notes = []
    for s, o in graph.subject_objects(SEAM.visibleWhen):
        if str(s) in boxes:
            text = f"[state = {app.label(str(o))}]"
            notes.append({"iri": str(o), "kind": "activation", "for": str(s), "state": str(o), "text": text})
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
    height = max(
        [MARGIN]
        + [b["y"] + b["h"] for b in boxes.values()]
        + [a["y"] + a["h"] for a in d["actions"].values()]
    ) + MARGIN
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
            b for iri, b in d["components"].items()
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

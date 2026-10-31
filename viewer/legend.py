"""C4 legend counts and click-to-hide contraction (M006/S04, D010).

Pure functions over the node/edge dicts c4_graph_data() returns — nothing
here touches the RDF graph, so hiding is testable without a browser.

Hiding a type must not orphan its neighbours:
- a hidden node with a visible ancestor collapses into that ancestor, so its
  edges reattach there;
- a hidden node with no visible ancestor is contracted out: edges are
  rerouted through it from its visible predecessors to its visible
  successors.
Rerouted edges carry kind "contracted" and the hidden ids they passed through
in "via".
"""

from __future__ import annotations

import re
from collections import deque

HIDE_TOKEN = re.compile(r"[A-Za-z][\w.-]*:[\w.-]+")


def parse_hide(raw: str) -> tuple[list[str], list[str]]:
    """Split a ?hide= value into (valid qname tokens, rejected tokens).
    Valid tokens are sorted and deduped; empty tokens are ignored."""
    valid: set[str] = set()
    rejected: list[str] = []
    for token in (raw or "").split(","):
        token = token.strip()
        if not token:
            continue
        if HIDE_TOKEN.fullmatch(token):
            valid.add(token)
        elif token not in rejected:
            rejected.append(token)
    return sorted(valid), rejected


def legend_entries(nodes: list[dict], hidden) -> list[dict]:
    """One entry per node type with its count over the unfiltered nodes."""
    hidden = set(hidden or ())
    entries: dict[str, dict] = {}
    for n in sorted(nodes, key=lambda n: n["id"]):
        entry = entries.setdefault(
            n["type"],
            {
                "type": n["type"],
                "label": n["typeLabel"],
                "layer": n["layer"],
                "count": 0,
                "hidden": n["type"] in hidden,
            },
        )
        entry["count"] += 1
    return sorted(entries.values(), key=lambda e: (e["label"], e["type"]))


def _path_label(labels: set[str]) -> str:
    return next(iter(labels)) if len(labels) == 1 else " / ".join(sorted(labels))


def contract_hidden(nodes: list[dict], edges: list[dict], hidden_types) -> tuple[list[dict], list[dict]]:
    hidden_types = set(hidden_types or ())
    hidden = {n["id"] for n in nodes if n["type"] in hidden_types}
    if not hidden:
        return nodes, edges

    parent_of = {n["id"]: n.get("parent") for n in nodes}

    def visible_ancestor(node_id: str) -> str | None:
        seen = set()
        p = parent_of.get(node_id)
        while p is not None and p in hidden and p not in seen:
            seen.add(p)
            p = parent_of.get(p)
        return None if p in hidden else p

    new_parent = {n["id"]: visible_ancestor(n["id"]) for n in nodes if n["id"] not in hidden}
    out_nodes = [{**n, "parent": new_parent[n["id"]]} for n in nodes if n["id"] not in hidden]

    def ancestors(node_id: str) -> set[str]:
        found = set()
        p = new_parent.get(node_id)
        while p is not None and p not in found:
            found.add(p)
            p = new_parent.get(p)
        return found

    # Visible nodes map to themselves, collapsed hidden nodes to their nearest
    # visible ancestor; free hidden nodes (no visible ancestor) map to None.
    target = {n["id"]: n["id"] for n in out_nodes}
    for h in hidden:
        target[h] = visible_ancestor(h)
    free = {h for h in hidden if target[h] is None}

    out_edges: dict[tuple, dict] = {}

    def add(frm: str, to: str, label: str, original: dict | None, via: set[str]) -> None:
        if frm == to or frm in ancestors(to) or to in ancestors(frm):
            return
        key = (frm, to, label)
        if original is not None:
            out_edges.setdefault(key, original)
            return
        existing = out_edges.get(key)
        if existing is None:
            out_edges[key] = {
                "from": frm,
                "to": to,
                "label": label,
                "kind": "contracted",
                "via": sorted(via),
            }
        elif existing.get("kind") == "contracted":
            existing["via"] = sorted(set(existing["via"]) | via)

    out_of: dict[str, list[dict]] = {}
    for e in edges:
        out_of.setdefault(e["from"], []).append(e)

    for e in sorted(edges, key=lambda e: (e["from"], e["to"], e["label"])):
        frm, to = e["from"], e["to"]
        if frm in free:
            continue  # reached by BFS from a visible predecessor instead
        src = target.get(frm)
        if src is None:
            continue
        start_via = {frm} & hidden
        if to not in free:
            dst = target.get(to)
            if dst is None:
                continue
            via = start_via | ({to} & hidden)
            add(src, dst, e["label"], e if not via else None, via)
            continue

        # Contraction: BFS through free hidden nodes to visible successors.
        # Each free node keeps the labels and hidden ids of its BFS-tree path.
        reached = {to: ({e["label"]}, start_via | {to})}
        queue = deque([to])
        while queue:
            node = queue.popleft()
            labels, via = reached[node]
            for nxt in sorted(out_of.get(node, []), key=lambda x: (x["to"], x["label"])):
                n_to = nxt["to"]
                path_labels = labels | {nxt["label"]}
                if n_to in free:
                    if n_to not in reached:
                        reached[n_to] = (path_labels, via | {n_to})
                        queue.append(n_to)
                    continue
                dst = target.get(n_to)
                if dst is None:
                    continue
                add(src, dst, _path_label(path_labels), None, via | ({n_to} & hidden))

    out_nodes.sort(key=lambda n: (n["parent"] or "", n["id"]))
    result = sorted(out_edges.values(), key=lambda e: (e["from"], e["to"], e["label"]))
    return out_nodes, result

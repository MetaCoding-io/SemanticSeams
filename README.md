# Seams

*A zoomable, multi-notation application graph. One RDF graph is the source of truth; diagrams are views.*

Click into a C4-style architecture component and land on an IFML interaction model. Click a UI event and land on the BPMN process it triggers. Click a business-rule task and land on a DMN decision table; click a data object and land on the RDF/SHACL shape graph. Four notations, one traversal — driven by 25 bridging predicates (the *seams*), not by tool integration glue.

Because everything shares one graph, you also get cross-layer queries no single-notation tool can answer:

- *Show me every UI event reachable by role X that eventually writes to this shape.*
- *Which BPMN tasks are allowed to fire this state transition?*
- *What breaks if db01 goes away?*

Full motivation, landscape survey, and design: [`docs/project-outline.md`](docs/project-outline.md).

## Layout

```
docs/       project outline (vision, pillars, landscape, stack, seam design rules)
  queries/  canned cross-layer queries (*.rq) — the query catalog the viewer's buttons and CI both drive
ontology/   seam.ttl        — the bridging ontology (the load-bearing part)
            arch.ttl        — minimal C4-style architecture vocabulary
            ifml.ttl        — IFML-inspired interaction vocabulary (documented correspondence + deviations vs OMG IFML)
            proc.ttl        — process/decision index types (NOT a BPMN ontology; see file header)
            state-comm.ttl  — statechart lifecycle + communication (channels; Hydra fills the rest)
            deploy.ttl      — deployment stub: artifact/config/placement; desired-state half of a GitOps loop
  shapes/   seam-shapes.ttl — SHACL constraints on the seams themselves (the project's own methodology, applied to itself)
examples/   checkout.ttl    — worked example exercising every non-reserved seam edge; the ontology smoke test
tests/      executable acceptance test: parse everything, validate against the shapes, assert the canned queries' rows
viewer/     (empty) the read-only multi-layer browser — v1 target
```

Notes on deliberate omissions: there is no BPMN/DMN ontology here. Native XML serializations are stored as `seam:renderPayload` and rendered by bpmn-js/dmn-js; only seam-participating elements get IRIs, using **BPMN element IDs as IRI fragments** (`:order_bpmn#persist_task`), which makes a stock bpmn-js viewer a full participant in the graph via its `element.click` event. Fragment naming serves renderer dispatch only — membership is data: every lifted element carries `seam:inModel`, the edge cross-layer SPARQL actually traverses. The thin `proc:`/`dec:` index vocabulary types only these seam-participating elements. The data layer needs no vocabulary at all — SHACL *is* the vocabulary.

## Tests

```
pip install -r requirements-dev.txt
pytest
```

The suite (also run in CI) parses every Turtle file, validates the example against `ontology/shapes/seam-shapes.ttl`, proves the shapes reject invalid seams, checks every non-reserved seam predicate is exercised, and asserts exact expected rows for the canned queries in `docs/queries/` — so the flagship cross-layer traversals can never silently regress to zero rows.

## v1: the viewer

Read-only, navigable, notation-switching browser over a hand-authored model. Stack:

- **Fuseki** — model store; one named graph per `seam:Model`
- **FastAPI** — three endpoints: describe node (JSON-LD, triples + seam edges), fetch render payload, SPARQL passthrough (HTTP QUERY, RFC 10008)
- **htmx shell** — every click is `hx-get /view/{iri}`; server dispatches on `seam:notation`
- **Renderers** — bpmn-js `NavigatedViewer` and dmn-js (read-only) for process/decision layers; a shared node-link renderer (elkjs layout) for architecture, IFML, statecharts, and shape graphs

Milestone 1: load `examples/checkout.ttl` + a hand-drawn `order_process.bpmn`, and complete the descent arch → IFML → BPMN → DMN/shape-graph purely by clicking.

## Roadmap (after v1)

Editing (embed modelers read-write) → SHACL-driven form generation → IFML→htmx generation → BPMN interpretation (SpiffWorkflow) → deployment generation (compose/Ansible from deploy: + drift detection as named-graph SPARQL diff) → methodology profiles as SHACL-shapes-over-the-model (IDesign first) → project-design projection (activities/Gantt derived from architecture, Löwy-style).

## License

TBD (intended: a standard OSI license; leaning Apache-2.0).

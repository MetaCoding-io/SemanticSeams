# SemanticSeams

*A zoomable, multi-notation application graph. One RDF graph is the source of truth; diagrams are views.*

A [MetaCoding](https://metacoding.io) project · [project page](https://metacoding-io.github.io/SemanticSeams/) · [project outline](docs/project-outline.md) · [decisions](docs/adr/)

**The pitch, in one paragraph.** Every tool that draws software draws one layer: C4 tools stop at the repository link, BPMN modelers never see the UI that fires a process, IFML never wired up its hooks to data, and SHACL lives in its own silo. SemanticSeams puts every element of every layer in one RDF graph, as a resource with an IRI, and treats each diagram as a view over it. Click a C4 container and land on its IFML interaction model; click a UI event and land on the BPMN process it triggers; click a business-rule task and land on the DMN table; click a data object and land on the SHACL shape. The cross-layer edges are the *seams*, a small bridging ontology of 25 predicates, and because the whole system is one graph, the questions no single-notation tool can answer become SPARQL.

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
site/       the public project page (GitHub Pages, no build step)
viewer/     the read-only multi-layer browser (FastAPI + htmx + bpmn-js/dmn-js)
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

## Status

Concept and proof-of-concept (July–September 2026): the bridging ontology, the SHACL
shapes over it, two worked examples (a checkout flow and a chat app), the canned
cross-layer queries, and a read-only viewer that completes the architecture → UI →
process → decision descent by clicking. See the [project outline](docs/project-outline.md)
for the design and the [ADRs](docs/adr/) for the decisions taken so far.

## Related

- [semantic-stack](https://github.com/MetaCoding-io/semantic-stack) — the Docker stack
  (Fuseki, QLever, RDF4J, OntoRefine, YASGUI, WebVOWL, Blueprint and more) this project
  is developed against.
- [MetaCoding](https://metacoding.io) — the data-centric consultancy behind both.

## License

[Apache-2.0](LICENSE). Copyright © 2026 MetaCoding.

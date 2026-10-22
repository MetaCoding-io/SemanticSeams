# Todos from the Wintercorn (2026) note

Things that should definitely be done as a result of reading this thesis. Each item names the file or ADR it lands in. Tick a box when the change has landed and link the commit, ADR or test.

## As-deployed graph (the half the thesis built)

- [ ] **Read the AFO source and write the mapping table** from AFO classes and properties (local cloud, system, husk, unit asset, host, server, provided and consumed service, core-system roles, dependency) onto `arch:`, `deploy:` and `comm:`, as a section in `docs/project-outline.md` §5 (landscape) or a new `docs/as-deployed.md`. Decide per row: same concept, reuse the term, or bridge by subsumption. Source: `github.com/oskwin/Arrowhead-Framework-Ontology`.
- [ ] **Amend ADR-0001**: the as-deployed graph becomes a family of timestamped snapshot graphs (`<urn:seams:graph:deployed:{iso-timestamp}>`) plus a derived current view; record that "current" is produced by an update step and is only as current as that step's last run. Update the graph table and the TriG convention.
- [ ] **Add deployed-graph shapes** in `ontology/shapes/deployed-shapes.ttl` with `sh:severity` on every shape and a stated policy in the file header: `sh:Violation` rejects the snapshot, `sh:Warning` records and keeps it. Add a test that a snapshot with a warning loads and a snapshot with a violation does not.
- [ ] **Classify drift differences**: specify in `ontology/deploy.ttl`'s header (or the ADR amendment) the three outcomes of an as-designed versus as-deployed diff: violation (design says X, deployment contradicts), decision (design silent, deployment chose; e.g. which provider a consumer bound to), and omission (design says X, deployment has nothing). The thesis's run-time bindings are the second class and must not be reported as the first.

## Occupancy over time (the third view)

- [ ] **Add a time-bounded placement record to `deploy:`**: a `deploy:Placement` with node, artifact (with version), start and optional end, and state in the vocabulary header that it is asserted per deployment and never derived. Add the "current placement is the one with no end" query to `docs/queries/` as `current-placement.rq` with its derived status documented, and a historical query `placements-on-node.rq`.
- [ ] **Exercise it in an example**: extend `examples/checkout.trig` (or the chat app) with two successive placements on one node so both queries have expected rows in `tests/test_acceptance.py`.

## Seams and identity

- [ ] **Record in ADR-0002 the reason it works**: the IRI-fragment-equals-element-id rule is the identifier agreement that lets a seam edge act on elements of two graphs that otherwise share nothing, and the correspondences stay valid only while identifiers survive revisions. Cite the thesis's "one explicit correspondence per deployed asset" result as the reason seams cannot be inferred from the layer vocabularies. One paragraph under Consequences.

## Competency questions

- [ ] **Add the three-condition pass criterion to `docs/queries/README.md`** and enforce the second condition in `tests/test_acceptance.py`: every canned query must be answerable from the layer graphs plus the seams graph without reading any `seam:renderPayload`. Add a column to the catalog table naming which named graphs each query crosses.

## Reasoning readiness

- [ ] **Add an `inferred` graph to ADR-0001's table** (`<urn:seams:graph:inferred>`) reserved for materialised entailments, with the rule that nothing writes inferred triples into a model graph or the seams graph. State the reasoner requirement if one is ever enabled: OWL 2 RL or another rule set with property chains, because `seam:triggers / seam:decidedBy / seam:invokes` collapsed to a derived reachability edge is a chain and OWL-Horst would drop it silently.
- [ ] **Add a test asserting that no canned query depends on entailment** (run each against the raw dataset with no inference and assert the same expected rows), so the day a reasoner is added, a query that silently starts depending on it is caught.

## Reference layer decision

- [ ] **Write ADR-0007, "Is `seam:` the reference or the bridge?"** Decide whether layer vocabularies align to `seam:` (reference) or whether a thinner reference sits above it, before the IDesign profile lands, because the profile is structurally a bridge ontology (a component taxonomy specialising `arch:` plus shapes). Record the thesis's rules that bridges assert subsumption never equivalence, and the least that suffices, whichever way the decision goes. Compare IDO's system, functional-object and physical-artefact terms against `arch:` as part of the decision so nothing is minted that a published reference already names.

## Notations

- [ ] **Decide on SysML v2 as a notation and record it** (an ADR, or a "deliberately deferred" line in `docs/project-outline.md` §3 beside CMMN). The decision should name what it would detail (`arch:` elements), how it would be carried (`seam:renderPayload` with the textual notation, seam-participating elements lifted by id), and cite Paper F's complementarity finding as the evidence that it is a projection worth having rather than a duplicate of `arch:`.

## Landscape

- [ ] **Add the thesis to `docs/project-outline.md` §5** as prior art for the deployment pillar's as-deployed half: the Arrowhead Framework Ontology (run-time generated, SHACL-validated, OWL 2 RL materialised, timestamped snapshot graphs) and the IDO-mediated alignment (reference layer, thin bridges, per-entity correspondences). Two sentences each, with the GitHub sources.

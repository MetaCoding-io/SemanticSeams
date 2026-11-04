# Decisions

Architecture decision records: each one states the context, the decision, the
alternatives and the consequences, and is not rewritten once accepted. A later decision
supersedes an earlier one instead.

| Record | Decision | Status |
|---|---|---|
| [ADR-0001](./0001-named-graph-partitioning) | Named-graph partitioning: one graph per model, one for the seams | Accepted |
| [ADR-0002](./0002-iri-identity-and-migration) | IRI identity and migration: native element IDs as IRI fragments | Accepted |
| [ADR-0003](./0003-payload-resolution) | Payload resolution: how native BPMN and DMN files are found and served | Accepted |
| [ADR-0004](./0004-view-response-contract) | View response contract: the JSON the viewer's `/view` endpoint returns | Accepted |
| [ADR-0005](./0005-navigation-resolution) | Navigation resolution: which edges a click follows, and how far | Accepted |
| [ADR-0006](./0006-index-payload-drift-lint) | Index-payload drift lint: keeping the graph and the native files in step | Accepted |
| [ADR-0007](./0007-execution-strategy) | Execution strategy: interpret where an engine exists, generate where none does | Proposed |
| [ADR-0008](./0008-node-link-renderer) | Node-link renderer: elkjs layout with hand-rolled SVG cards, shared by C4 and shape graphs | Accepted |
| [ADR-0009](./0009-human-tasks) | Human tasks: a BPMN user task points at the form it is completed on (`seam:completedOn`) | Accepted |
| [ADR-0010](./0010-channel-started-processes) | Channel-started processes: a message start event that `seam:subscribesTo` a channel starts its process on each publish | Accepted |
| [ADR-0011](./0011-storage-resolution) | Storage resolution: a shape is `seam:storedIn` a store whose `deploy:storeKind` the runtime supports, reached through a `deploy:connectsTo` binding | Accepted |
| [ADR-0012](./0012-operation-implementation) | Operation implementation: an operation `seam:implementedBy` an LLM completion, a Python handler in the handlers package, or an HTTP endpoint | Accepted |
| [ADR-0013](./0013-error-shapes-and-boundaries) | Error shapes and boundaries: an operation's `hydra:possibleStatus` carries a `comm:errorCode` and a problem+json error shape, and a lifted BPMN error boundary event `seam:catches` it | Accepted |
| [ADR-0014](./0014-scenarios-and-derived-tests) | Scenarios and derived tests: `verify:` scenarios, decision examples and shape examples in the seams graph, and ODRL policies, become generated pytest files under `generated/tests` | Accepted |
| [ADR-0015](./0015-environments) | Environments: development and production are `arch:Environment`s, an environment-scoped `deploy:override` replaces the shared fact of the same predicate, and the compose generator writes one file per environment | Accepted |
| [ADR-0016](./0016-generator-protocol) | Generator protocol: a generator is a `seams_gen.protocol.Generator` (name, version, preconditions, extract, render, sources) registered in the `seams.generators` entry-point group; `seams generate` checks its precondition shapes strictly and `seams.lock` records its version | Accepted |
| [ADR-0017](./0017-write-path-and-editor) | Write path and editor: a patch edits the source TriG text at the triple level so comments and layout survive, the write path is a new `seams_edit` package outside the read-only `seams` library, and editing is a viewer mode that is off by default | Accepted |
| [ADR-0018](./0018-domain-profiles) | Domain profiles: a `profiles/<name>/profile.ttl` package attached by `seam:conformsTo` lists the classes the editor offers (`seam:offersClass`) with SKOS or RDFS labels, the generators it previews (`seam:usesGenerator`) and shapes merged into health (`seam:profileShapes`); out-of-profile classes are flagged, never refused | Accepted |
| [ADR-0019](./0019-generation-trace) | Generation trace: `seams generate` writes a line-level `<output>.trace.json` sidecar beside each output (template origins by sentinel render, model IRIs through `finalize`), records it in `seams.lock`, and derives the lock's `sources` from it | Accepted |
| [ADR-0020](./0020-llm-drafts) | LLM drafts: `seams propose` sends a versioned, data-quoted prompt to a provider command, caches the response by context hash, and writes the handlers module only when its acceptance tests pass in a scratch copy | Accepted |
| [ADR-0021](./0021-vocabulary-versions) | Vocabulary versions: each vocabulary carries an `owl:versionIRI` (`MAJOR.MINOR`), a model `owl:imports` the versions it targets in the manifest graph, `seams.load` loads same, refuses newer and migrates older models in memory with one SPARQL Update file per major step, `seams migrate` persists through `seams_edit`, and a deprecated term gets an `sh:Warning` shape | Accepted |
| [ADR-0022](./0022-ontology-notation) | Ontology notation: a `seam:Ontology` model graph per model is also an `owl:Ontology` with one `owl:versionIRI`; its `owl:imports` name version IRIs resolved offline against files vendored under `ontology/vendor/` (gistCore 14.0.0), an unresolved or mismatched import is a `ResolutionError(ontology, owl:imports)`, and the viewer draws it with the shape-graph card renderer | Accepted |

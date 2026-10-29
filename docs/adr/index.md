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

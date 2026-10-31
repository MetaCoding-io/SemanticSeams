# Canned query catalog

The cross-layer questions the graph exists to answer, as parameterized SPARQL.
Each query leaves its focus node as a free variable (`?shape`, `?node`,
`?state`) — callers bind it (rdflib `initBindings`, or `VALUES` injection in the
viewer). In the v1 viewer these become buttons on the inspector, not SPARQL a
user sees (RDF-invisibility principle, see `orig_convo/product-brief.md`).

| Query | Question | Focus variable |
|---|---|---|
| `what-writes-shape.rq` | Which UI events can eventually write this data shape, and through which task? | `?shape` |
| `impact-of-node.rq` | What breaks — containers, processes *and data* — if this deployment node goes away? | `?node` |
| `what-moves-state.rq` | Which process tasks may move an entity out of this state? | `?state` |
| `screens-by-role-writing-shape.rq` | Which screens can each role use to eventually write this data shape, and through which event and task? | `?shape` |
| `screens-to-finish-process.rq` | Which screens must a person visit to finish this process, and which policy governs each? | `?process` |
| `c4-l1-rollup.rq` | Which systems talk to which, and where are they deployed, with container detail rolled up? | none |

`c4-l1-rollup.rq` is a projection query, not a Questions-catalog entry: it
feeds the C4 L1 (system context) view's rolled-up edges (ADR-0008) and is not
exposed as an inspector button.

`tests/test_acceptance.py` runs each query against `examples/checkout.ttl` and
the chat-app model and asserts the exact expected rows; a change that silently
breaks a traversal breaks CI.

`screens-to-finish-process.rq` follows `seam:completedOn` (ADR-0009), which neither
example uses yet, so its expected row comes from the human-task fixture,
`tests/fixtures/human_task/approval.trig`; it returns no rows on the chat app.
`tests/test_human_task_vocabulary.py` checks it too.

`screens-by-role-writing-shape.rq` takes the `what-writes-shape.rq` path and adds the
screen that holds the event, plus each `odrl:assignee` of a policy governing the event or
the operation it submits to. An unbound role means the write is ungoverned. The viewer
binds only `?shape`, so you answer a question about one role by reading the role column.
The acceptance tests pin its rows on the chat app (`MessageShape`, role
`:authenticated_user`) and on the human-task fixture (`ExpenseShape` and `ApprovalShape`,
role `:employee`). They also check the ungoverned case on an in-memory copy of the
fixture with its policy links removed.

`complexity/` holds the three model-size measurements used by
`python -m seams_gen.complexity` (models per notation, the most-reached elements and
the cross-layer seam edge count; see [seams_gen/README.md](../../seams_gen/README.md)).
They are not focus-node questions and are not rendered on the query reference page,
which only reads the `.rq` files at this top level. `tests/test_complexity.py` checks
their results against the chat app, checkout and expense chapter-08 models.

`gates/` holds gate queries: SELECT queries that must return no rows.
`seams check` runs the ones a project lists under `gates` in its seams.toml and reports
every row as a problem (see [the CLI reference](../reference/seams-cli.md#seams-check)).
`gates/ungoverned-writes.rq` lists each UI event that can write a data shape with no policy
governing it; the chat app and expense chapters 7 and 8 run it. Like `complexity/`, the
gates are kept off the query reference page. `tests/test_gate_queries.py` checks their rows.

`coverage/` holds coverage queries (decision D054): SELECT queries that list the parts of a
model no test exercises. Like a gate, each returns no rows when the model is covered, so a
project can list it under `gates`.
`coverage/unfired-transitions.rq` lists each `state:Transition` that no element `seam:fires`,
with the lifecycle it is `seam:inModel`. `coverage/policies-without-deny.rq` lists each
`odrl:permission` the `tests` generator writes no party deny test for: anyone may use it (it
has no `odrl:assignee`, or its assignee is an `odrl:PartyCollection`), or no `odrl:Party` in
the model is outside its assignee. Bind `?lifecycle` or `?policy` to check one element. The
`seams` library bundles them as package data and loads them by folder-qualified name:
`model.question("coverage/unfired-transitions")`, with `seams.question_names("coverage")`
listing them. `question_names()` with no folder still returns only the top-level questions, so
coverage stays off the query reference page. `tests/test_coverage_queries.py` checks their
rows (none on expense chapter 9; the chat app's two failure transitions and its
party-collection send policy), that the deny query matches what the generator emits, and that
the bundled copies are byte-identical to these files.

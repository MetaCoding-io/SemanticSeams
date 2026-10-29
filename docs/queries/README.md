# Canned query catalog

The cross-layer questions the graph exists to answer, as parameterized SPARQL.
Each query leaves its focus node as a free variable (`?shape`, `?node`,
`?state`) — callers bind it (rdflib `initBindings`, or `VALUES` injection in the
viewer). In the v1 viewer these become buttons on the inspector, not SPARQL a
user sees (RDF-invisibility principle, see `orig_convo/product-brief.md`).

| Query | Question | Focus variable |
|---|---|---|
| `what-writes-shape.rq` | Which UI events can eventually write this data shape, and through which task? | `?shape` |
| `impact-of-node.rq` | What breaks — containers *and processes* — if this deployment node goes away? | `?node` |
| `what-moves-state.rq` | Which process tasks may move an entity out of this state? | `?state` |
| `c4-l1-rollup.rq` | Which systems talk to which, and where are they deployed, with container detail rolled up? | none |

`c4-l1-rollup.rq` is a projection query, not a Questions-catalog entry: it
feeds the C4 L1 (system context) view's rolled-up edges (ADR-0008) and is not
exposed as an inspector button.

`tests/test_acceptance.py` runs each query against `examples/checkout.ttl` and
the chat-app model and asserts the exact expected rows; a change that silently
breaks a traversal breaks CI.

`complexity/` holds the three model-size measurements used by
`python -m seams_gen.complexity` (models per notation, the most-reached elements and
the cross-layer seam edge count; see [seams_gen/README.md](../../seams_gen/README.md)).
They are not focus-node questions and are not rendered on the query reference page,
which only reads the `.rq` files at this top level. `tests/test_complexity.py` checks
their results against the chat app and checkout models.

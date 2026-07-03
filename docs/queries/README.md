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

`tests/test_acceptance.py` runs all three against `examples/checkout.ttl` and
asserts the exact expected rows; a change that silently breaks a traversal
breaks CI.

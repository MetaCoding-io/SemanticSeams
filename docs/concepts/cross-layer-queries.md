# Cross-layer queries

The second payoff of one graph, arguably bigger than navigation, is that questions which
span layers become a single SPARQL query. No toolchain of separate modelers can answer
them, because no single tool holds both ends.

## The questions

Four ship today as canned queries. Each leaves one variable free, the element you are
asking about, and the viewer binds it to whatever you are looking at.

| Question | Why it matters |
|---|---|
| Which UI events can eventually write this data shape, and through which task? | Compliance and security review: everything a user can do that changes this data |
| What breaks, containers and processes both, if this deployment node goes away? | Impact analysis, and later drift detection between designed and deployed state |
| Which process tasks may move an entity out of this state? | Lifecycle audit, and the inverse view of `seam:fires` |
| Which screens can each role use to eventually write this data shape? | Access review: which roles can reach a write to this data, and from which screen |

The [query catalog](/reference/queries) shows each one in full, generated from
[`docs/queries/`](../queries/).

## How they work

The queries are SPARQL 1.1 property paths through the [seams](/concepts/the-seams). The
first one walks from an IFML event, through the process it triggers and that process's
tasks, through decisions and operation invocations and any asynchronous hop through a
channel, to whatever `seam:writes` the shape. `seam:inModel` is what lets the path step
from a process down into its tasks.

Adding a question is adding a `.rq` file with a free focus variable and a line in the
catalog's table; the viewer offers it on every element of the focus type.

## How you see them

In the viewer, applicable queries appear as buttons under **Questions**, and results
render inline with each value linked to its own view. You never see SPARQL there; that
is the project's RDF-invisibility principle.

The same canned queries run from Python through the `seams` library, which ships them
as package data: `seams.load("examples/chat-app/chat-app.trig").question("impact-of-node",
node=":db01")` returns the rows as dicts, and `model.sparql(...)` runs your own read-only
query with the project's prefixes already declared.

## How they are kept honest

`tests/test_acceptance.py` runs every query against the worked examples and asserts the
exact rows it should return. A change to the ontology, an example or a query that breaks
a traversal fails CI instead of quietly returning nothing.

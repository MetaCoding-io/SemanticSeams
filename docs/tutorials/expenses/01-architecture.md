# 1. An empty file and an architecture

At the end of this chapter you have a model with one system and two containers, open in
the viewer as a C4 architecture view, with the model-health badge green.

## An empty file

Create `expenses.trig` anywhere you like. A model is a TriG file: Turtle triples grouped
into named graphs. Start with the prefixes:

```trig
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix :       <https://example.org/expenses/> .
```

`seam:` is the vocabulary that ties models together, `arch:` is the architecture layer's
vocabulary, and `:` is your app's own namespace. `xsd:` and `sh:` are not used yet;
chapter 2 needs them.

## The architecture model

Each model is a `seam:Model` and gets a named graph of its own. The architecture model
holds the system and the two containers it is built from: an employee portal that people
use, and the API it calls.

```trig
<urn:seams:graph:model:expense_architecture> {

    :expense_architecture a seam:Model ;
        rdfs:label "Expense Architecture" .

    # The system and the two containers it is built from.
    :expense_system a arch:System ; rdfs:label "Expense Approval" ;
        arch:contains :employee_portal , :expense_api ;
        seam:inModel :expense_architecture .

    :employee_portal a arch:Container ; rdfs:label "Employee Portal" ;
        arch:technology "htmx + server-rendered fragments" ;
        arch:dependsOn :expense_api ;
        seam:inModel :expense_architecture .

    :expense_api a arch:Container ; rdfs:label "Expense API" ;
        arch:technology "FastAPI" ;
        seam:inModel :expense_architecture .
}
```

`seam:inModel` says which model an element belongs to. The viewer uses it to decide what
to draw in a model's view, and the shapes check that it always points at a `seam:Model`.

## The seams graph

Links between models, and every `seam:` annotation about a model, live in one more named
graph, the seams graph. For now it holds a single triple: the architecture model's
notation.

```trig
<urn:seams:graph:seams> {

    # The viewer opens at the model whose notation is C4.
    :expense_architecture seam:notation seam:C4 .
}
```

`seam:notation` tells the viewer how to draw a model. Every `seam:Model` must have exactly
one; you will see what happens when one is missing in chapter 2. The viewer's root opens
the model whose notation is `seam:C4`.

## View it

Point the viewer at your file with `SEAMS_MODEL` (here, the checkpoint):

```sh
SEAMS_MODEL=examples/expenses/chapter-01/expenses.trig python3 -m uvicorn viewer.app:app --port 8000
```

Open <http://localhost:8000>. The root redirects to the Expense Architecture view: the
Expense Approval system with its two containers and the `depends on` edge between them.
The bar above the breadcrumbs is the model-health badge. It reads **✓ Conforms** on a
green background: the model passes the [seam shapes](/reference/shapes).
[Using the viewer](/guide/the-viewer) explains the rest of the page.

## Checkpoint

Your file should now match
[`examples/expenses/chapter-01/expenses.trig`](../../../examples/expenses/chapter-01/expenses.trig).
Next: [2. The data](./02-data).

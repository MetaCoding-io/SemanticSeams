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
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix :       <https://example.org/expenses/> .
```

`seam:` is the vocabulary that ties models together, `arch:` is the architecture layer's
vocabulary, and `:` is your app's own namespace. `owl:` is for the version declaration at
the end of the file. `xsd:` and `sh:` are not used yet; chapter 2 needs them.

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

## The vocabulary versions

Each vocabulary has a version, and the vocabularies change over time. The last graph in
the file, the manifest graph, says which version of each one the model is written for. It
imports the version of every vocabulary the model uses, here `arch:` and `seam:` at 1.0:

```trig
<urn:seams:graph:manifest> {

    # One owl:imports per vocabulary the model uses (ADR-0021).
    <urn:seams:graph:manifest> a owl:Ontology ;
        owl:imports <https://w3id.org/seams/arch/1.2> ,
                    <https://w3id.org/seams/seam/1.4> .
}
```

When a later version of a vocabulary renames or removes a term, the tools migrate a model
that targets the older version as they load it, and `seams migrate` writes the migration
into your file. A model with no declaration for a vocabulary targets its 1.0.
[Authoring a model](/guide/authoring-a-model#vocabulary-versions) has the details.

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

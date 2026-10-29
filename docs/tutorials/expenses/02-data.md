# 2. The data

At the end of this chapter your model has a second model, a SHACL shape graph holding
`:ExpenseShape`. You will also have broken the model on purpose, watched the health
badge turn red and name what is wrong, and fixed it.

## The shape graph

In SemanticSeams the data layer is written in SHACL. A shape is the vocabulary the other
layers share: chapter 3's form will write an `:ExpenseShape`, its list will read them,
and the generated API will validate what it receives against this shape.

Add a new named graph for the data model, between the architecture graph and the seams
graph:

```trig
<urn:seams:graph:model:expense_data> {

    :expense_data a seam:Model ; rdfs:label "Expense Data" .

    # Identifier convention (as in the chat app): a shape addressed in a URL
    # carries exactly one string :id. The other properties are what a form asks for.
    :ExpenseShape a sh:NodeShape ; rdfs:label "Expense" ;
        sh:property [ sh:path :id ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] ;
        sh:property [ sh:path :description ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ;
                      sh:order 0 ] ;
        sh:property [ sh:path :amount ; sh:datatype xsd:decimal ; sh:minCount 1 ; sh:maxCount 1 ;
                      sh:minInclusive 0.01 ; sh:order 1 ] ;
        sh:property [ sh:path :date ; sh:datatype xsd:date ; sh:minCount 1 ; sh:maxCount 1 ;
                      sh:order 2 ] ;
        seam:inModel :expense_data .
}
```

An expense has exactly one description (a string), one amount (a decimal of at least
0.01) and one date. The `:id` is how the app addresses an expense; the runtime assigns it,
so no form will ask for it. `sh:order` fixes the order the form shows its fields in.

Then give the new model its notation in the seams graph:

```trig
<urn:seams:graph:seams> {

    # The viewer opens at the model whose notation is C4.
    :expense_architecture seam:notation seam:C4 .
    :expense_data seam:notation seam:ShapeGraph .
}
```

## A deliberate mistake

Now break it. Delete the line you just added, as if you had forgotten it:

```diff
 <urn:seams:graph:seams> {

     # The viewer opens at the model whose notation is C4.
     :expense_architecture seam:notation seam:C4 .
-    :expense_data seam:notation seam:ShapeGraph .
 }
```

Start the viewer on your file (with `SEAMS_MODEL=expenses.trig`, or wherever you saved it):

```sh
SEAMS_MODEL=expenses.trig python3 -m uvicorn viewer.app:app --port 8000
```

The viewer reads the model once at start-up, so restart it after each edit. The health
badge is now red: **✗ 1 violation(s)**. Open **Violations** under it. The entry reads
"Every seam:Model has exactly one seam:notation, and it is a seam:Notation." and names
the element, `https://example.org/expenses/expense_data`.

That message comes from `seamsh:ModelShape` in the [seam shapes](/reference/shapes).
The viewer runs the shapes against every model it loads, so a broken seam shows up the
moment you look at the model, not when something downstream fails. The same check runs
from the command line; see [Validate it](/guide/authoring-a-model#validate-it).

## Fix it

Put the line back:

```trig
    :expense_data seam:notation seam:ShapeGraph .
```

Restart the viewer and the badge is green again. The architecture view looks the same as
in chapter 1: the data model is not linked to anything yet. Chapter 3 links it.

## Checkpoint

Your file should now match
[`examples/expenses/chapter-02/expenses.trig`](../../../examples/expenses/chapter-02/expenses.trig).
To see only what this chapter added:

```sh
diff examples/expenses/chapter-01/expenses.trig examples/expenses/chapter-02/expenses.trig
```

Next: [3. The screens](./03-screens).

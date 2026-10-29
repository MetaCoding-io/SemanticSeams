# 3. The screens

At the end of this chapter your model has an interaction model: one page with a list of
expenses and a form for a new one, and the two API operations the page calls. You
generate the route module and htmx templates from it and run the app. The form rejects
invalid input against `:ExpenseShape` with a 422 and stores valid input.

There is no process yet. The form's operation validates what it receives and stores it
directly; chapter 4 puts a BPMN process in between.

## Three more prefixes

The interaction layer, the API operations and their HTTP details need three more
vocabularies. Add them to the prefixes at the top of the file:

```trig
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix ifml:   <https://w3id.org/seams/ifml#> .
@prefix hydra:  <http://www.w3.org/ns/hydra/core#> .
@prefix comm:   <https://w3id.org/seams/comm#> .
@prefix :       <https://example.org/expenses/> .
```

`ifml:` is the interaction layer (IFML), `hydra:` describes API operations, and `comm:`
adds what Hydra leaves out, such as the request media type and the path.

## The interaction model

Add a third model graph after the data graph. It holds one page, the landmark the app
serves at `/`, containing two components: the list and the form.

```trig
<urn:seams:graph:model:expense_ifml> {

    :expense_ifml a seam:Model , ifml:InteractionModel ;
        rdfs:label "Expense Interface" ;
        ifml:contains :expenses_page .

    # The landmark page: the generated app serves it at ifml:path.
    :expenses_page a ifml:ViewContainer ; rdfs:label "Expenses Page" ;
        ifml:isLandmark true ;
        ifml:path "/" ;
        ifml:title "Expenses"@en ;
        ifml:contains :expense_list , :expense_form ;
        seam:inModel :expense_ifml .

    # The expenses submitted so far, one item per expense.
    :expense_list a ifml:Details ; rdfs:label "My Expenses" ;
        ifml:order 0 ;
        seam:inModel :expense_ifml .
```

The list is an `ifml:Details`, not an `ifml:List`: a list's items are links to somewhere
else, and these items are not links yet. A details component can have items appended to
it, which is what the form will do.

The form has one event, the submit, and one parameter per field it asks for. Each
parameter is `ifml:boundTo` a property of `:ExpenseShape`. There is no parameter for
`:id`, so the form does not ask for one.

```trig
    # The form asks for the three fields its parameters are bound to.
    :expense_form a ifml:Form ; rdfs:label "New Expense" ;
        ifml:order 1 ;
        ifml:hasEvent :submit_expense ;
        ifml:hasParameter :description_input , :amount_input , :date_input ;
        seam:inModel :expense_ifml .

    :description_input a ifml:Parameter ; rdfs:label "description" ;
        ifml:boundTo :description ;
        seam:inModel :expense_ifml .
    :amount_input a ifml:Parameter ; rdfs:label "amount" ;
        ifml:boundTo :amount ;
        seam:inModel :expense_ifml .
    :date_input a ifml:Parameter ; rdfs:label "date" ;
        ifml:boundTo :date ;
        seam:inModel :expense_ifml .

    :submit_expense a ifml:Event ; rdfs:label "Submit Expense" ;
        ifml:trigger "submit" ;
        seam:inModel :expense_ifml .

    # Submitting appends the stored expense to the list.
    :submit_to_list a ifml:NavigationFlow ;
        ifml:source :submit_expense ; ifml:target :expense_list ;
        ifml:swap ifml:Append ;
        seam:inModel :expense_ifml .
}
```

The navigation flow says what the page does after a submit: the response is appended to
`:expense_list`.

## The seams

Everything that links one model to another goes in the seams graph. First the new
model's notation:

```trig
    # The viewer opens at the model whose notation is C4.
    :expense_architecture seam:notation seam:C4 .
    :expense_data seam:notation seam:ShapeGraph .
    :expense_ifml seam:notation seam:IFML .
```

Then the links. Each one is a question the graph can now answer:

```trig
    # Architecture to UI and API: the portal presents the screens and calls
    # the operations the API exposes.
    :employee_portal seam:presents :expense_ifml ;
        seam:consumes :submit_expense_op , :list_expenses_op .
    :expense_api seam:exposes :submit_expense_op , :list_expenses_op .

    # UI to data and API: the form writes an ExpenseShape, its event submits
    # it to the operation, and the list reads ExpenseShapes.
    :expense_form seam:writes :ExpenseShape .
    :expense_list seam:reads :ExpenseShape .
    :submit_expense seam:submitsTo :submit_expense_op .

    # Operation to the component whose partial its response renders.
    :submit_expense_op seam:rendersComponent :expense_list .
    :list_expenses_op seam:rendersComponent :expense_list .
```

- `seam:presents`: the portal container is what shows the interaction model to people.
- `seam:exposes` and `seam:consumes`: the API container serves the two operations, and the
  portal calls them.
- `seam:writes` and `seam:reads`: the form produces an `:ExpenseShape` and the list
  shows them.
- `seam:submitsTo`: submitting the form calls `:submit_expense_op`.
- `seam:rendersComponent`: both operations answer with the list's HTML fragment.

Last, in the same graph, the two operations themselves. The submit operation accepts an
`:ExpenseShape` as a urlencoded form, the list operation returns them, and both answer
with a UI fragment rather than JSON:

```trig
    # Communication contract: the two operations.
    :submit_expense_op a hydra:Operation ; rdfs:label "Submit Expense" ;
        hydra:method "POST" ;
        seam:acceptsShape :ExpenseShape ;
        seam:returnsShape :ExpenseShape ;
        seam:mediaKind seam:UIFragment ;
        comm:requestMediaType "application/x-www-form-urlencoded" ;
        comm:path [ a hydra:IriTemplate ;
                    hydra:template "/expenses" ] .

    :list_expenses_op a hydra:Operation ; rdfs:label "List Expenses" ;
        hydra:method "GET" ;
        seam:returnsShape :ExpenseShape ;
        seam:mediaKind seam:UIFragment ;
        comm:path [ a hydra:IriTemplate ;
                    hydra:template "/expenses" ] .
}
```

Restart the viewer on your file. The badge is green, and clicking **Employee Portal** in
the architecture view follows `seam:presents` to the Expense Interface, drawn in IFML
notation.

## Generate the app

The form's event `seam:submitsTo` a POST operation that `seam:acceptsShape :ExpenseShape`,
and the form `seam:writes :ExpenseShape`. Because the event does not `seam:triggers` a
process, the generated handler validates the input and stores it itself
([Saving a form without a process](/guide/authoring-a-model#saving-a-form-without-a-process)).

Run the two generators from the repository root. These write into the chapter 3
checkpoint directory; point the arguments at your own file and an output directory of
your choice to generate from your copy.

```sh
python -m seams_gen fastapi examples/expenses/chapter-03/expenses.trig --out examples/expenses/chapter-03/generated
python -m seams_gen htmx examples/expenses/chapter-03/expenses.trig --out examples/expenses/chapter-03/generated/templates
```

`fastapi` writes `expense_api.py`, the route module of `:expense_api`, the container that
exposes the operation the form submits to. `htmx` writes the landmark page
(`expenses_page.html`) and the list partials the routes render. The checkpoint's
generated files are committed, so `git diff` after regenerating shows nothing, and CI
fails if they ever differ.

## Run it

The runtime's host serves one generated route module. Tell it which model to load
(`SEAMS_MODEL`), where the templates are (`SEAMS_TEMPLATES`) and where to keep its store
(`SEAMS_DB`), and pass it the route module. Port 8001 leaves port 8000 for the viewer:

```sh
SEAMS_MODEL=examples/expenses/chapter-03/expenses.trig \
SEAMS_TEMPLATES=examples/expenses/chapter-03/generated/templates \
SEAMS_DB=/tmp/expenses.sqlite \
python -m seams_runtime.host --routes examples/expenses/chapter-03/generated/expense_api.py --port 8001
```

Open <http://localhost:8001>. The page has an empty list and a form with three fields:
description, amount and date. The fields come from the form's parameters, in the
shape's `sh:order`.

Submit an invalid expense first. The browser fields are only marked required, so the
easiest way to see the whole answer is from a second terminal:

```sh
curl -i -X POST http://localhost:8001/expenses -d description= -d amount=-5 -d date=2026-10-01
```

The answer is `422 Unprocessable Entity`. Its body is a `ContractViolation` for
`https://example.org/expenses/ExpenseShape` with one result per failing path: `amount`
(`MinInclusiveConstraintComponent`, the amount is below 0.01) and `description`
(`MinCountConstraintComponent`, it is missing). Nothing is stored. In the browser, the
same submit leaves the list unchanged. A malformed date, or an amount that is not a
number, is refused the same way.

Now submit a valid one, in the browser or with curl:

```sh
curl -X POST http://localhost:8001/expenses -d "description=Train to Leeds" -d amount=42.50 -d date=2026-10-01
```

The answer is the new list item, and the browser appends it to the list. The runtime
assigned the expense its `:id`. Reload the page and the expense is still there: it is in
the store `SEAMS_DB` names.

Every rule the API enforced here is a line of `:ExpenseShape`. None of it is in the
generated code; change the shape, regenerate, and the app follows.

This chapter runs the app in a local Python process. Running it with `docker compose`
needs the compose file the `compose` generator writes, which arrives with the full
deployment model in chapter 8 (decision D026).

## Checkpoint

Your file should now match
[`examples/expenses/chapter-03/expenses.trig`](../../../examples/expenses/chapter-03/expenses.trig),
and the generated code
[`examples/expenses/chapter-03/generated/`](../../../examples/expenses/chapter-03/generated/README.md).
To see only what this chapter added:

```sh
diff examples/expenses/chapter-02/expenses.trig examples/expenses/chapter-03/expenses.trig
```

Next, [chapter 4](./04-process) puts a BPMN process between the form and the store.

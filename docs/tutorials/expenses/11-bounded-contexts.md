# 11 · A second bounded context

Ten chapters have grown one file, and one team could keep it all in their heads. Now
finance wants to own payouts: its own words for a payment, its own process, its own
screens, and the freedom to change them without reading the approval flow. This
chapter splits the model into two **bounded contexts**
([ADR-0030](../../adr/0030-domains-and-bounded-contexts.md)): the expense context,
which approves expenses, and the finance context, which pays them. Each gets its own
file and its own ontology, and the `:payouts` channel becomes the one line between them.

Nothing new is generated. The same app runs, with one difference you can see in the
storm: a payment is now written only from the finance side.

## Why split

Run chapter 10's storm for the approval process:

```sh
seams storm approval_process --project examples/expenses/chapter-10
```

Step 8 is the odd one out:

```
8. **Pay Expense** (`pay_expense`)
   - actor: Finance (policy `finance_payment_policy`)
   - command: Pay Expense (`pay_expense`) on `payment_form` → POST `pay_expense_op` [PaymentShape]
   - aggregate: Payment (`PaymentShape`), class `Payment`, stored in `expense_db`, lifecycle `payment_lifecycle`
   - domain event: paid (`t_pay`: approved → paid, Expense Lifecycle)
```

The approval process writes a payment, and the expense lifecycle has a `paid` state.
Everything else about payments (scheduling, batching, the payout decision, the
finance console) already lives in the payout process that chapter 8 started from
`:payouts`. One finance step sits on the wrong side of the channel. Drawing the
boundary is what makes that visible, and moving the step is what fixes it.

## Two files, one model

From this chapter the checkpoint is a directory with two TriG files:

- `expenses.trig` holds the architecture, the expense context's models and the seams
  graph;
- `finance.trig` holds the finance context's models: its ontology, the payout process
  and decision, the payment lifecycle, the vendor review and the finance console.

The project file names the directory instead of a file:

```toml
model = "."
```

Every `*.trig` file in it is loaded into one dataset, so the generators, `seams check`
and the viewer see one model, as before. One file per context is a convention, not a
rule (ADR-0030 section 3): ownership is a fact in the model, never read from the file
layout, so moving a graph between the files changes nothing the model says. The seams
graph, the one graph of cross-model links, stays in `expenses.trig`, so the one write
path ([ADR-0017](../../adr/0017-write-path-and-editor.md)) knows where each seams fact
goes.

Move these graphs, unchanged, from `expenses.trig` into a new `finance.trig`:
`payout_bpmn`, `payout_dmn`, `payment_lifecycle`, `vendor_bpmn` and `finance_console`.
`finance.trig` needs the prefixes those graphs use. The BPMN and DMN payload files stay
beside it.

## Domains and contexts

In the architecture graph, declare the two business areas and a context in each.
An `arch:Domain` has exactly one classification, `arch:Core`, `arch:Supporting` or
`arch:Generic`. Paying people quickly is what this business competes on, so finance
is core; approving expenses is supporting work:

```trig
    :expense_management a arch:Domain ; rdfs:label "Expense Management" ;
        arch:classification arch:Supporting ;
        arch:contains :expense_system , :expense_context ;
        seam:inModel :expense_architecture .
    :finance a arch:Domain ; rdfs:label "Finance" ;
        arch:classification arch:Core ;
        arch:contains :finance_context ;
        seam:inModel :expense_architecture .
    :expense_context a arch:BoundedContext ; rdfs:label "Expenses" ;
        seam:inModel :expense_architecture .
    :finance_context a arch:BoundedContext ; rdfs:label "Payouts" ;
        seam:inModel :expense_architecture .
```

A context is an element of the architecture, not a model. It does not say which
containers run it: a container that `seam:executes` or `seam:presents` a model the
context owns runs that context. Here both contexts run in the same portal and API, and
the checkpoint keeps one deployment.

The new terms need the vocabulary versions that declare them. In the manifest graph,
import `arch` 1.1 and `seam` 1.4:

```trig
        owl:imports <https://w3id.org/seams/arch/1.1> ,
                    <https://w3id.org/seams/comm/1.0> ,
                    <https://w3id.org/seams/deploy/1.0> ,
                    <https://w3id.org/seams/ifml/1.0> ,
                    <https://w3id.org/seams/proc/1.0> ,
                    <https://w3id.org/seams/seam/1.4> ,
```

## What each context owns

Ownership is a cross-model fact, so it goes in the seams graph. `seam:owns` joins a
context to each model written in its language:

```trig
    :expense_context seam:owns :expense_ontology , :expense_data , :expense_ifml ,
        :approval_bpmn , :approval_dmn , :expense_lifecycle .
```

```trig
    :finance_context seam:owns :finance_ontology , :payout_bpmn , :payout_dmn ,
        :finance_console , :payment_lifecycle , :vendor_bpmn .
```

The seam shapes check the rules. A context owns exactly one ontology, its language. A
model has at most one owner, and once a model declares any context, every model except
the architecture model has exactly one. The architecture model is owned by no one: it
is where the boundaries are drawn. Leave a model out of both lists and `seams check`
names it.

An element belongs to a context when its `seam:inModel` model does, so no element
needs a context fact of its own.

## The finance ontology

Finance's words get an ontology of their own in `finance.trig`. `:Payment` and
`:Vendor` move here from the expense ontology:

```trig
    :finance_ontology a seam:Model , owl:Ontology ;
        rdfs:label "Finance Ontology" ;
        owl:versionIRI <https://example.org/expenses/finance_ontology/1.0> ;
        owl:imports <https://w3id.org/semanticarts/ontology/gistCore14.0.0> .

    # The company's transfer that reimburses an expense. gist: a transfer of funds.
    :Payment a owl:Class ;
        rdfs:subClassOf gist:Transaction ;
        rdfs:label "Payment" ;
        skos:definition "Money the company transfers to reimburse an expense." ;
        seam:inModel :finance_ontology .
```

Only `seam:inModel` changes. The IRIs stay
([ADR-0002](../../adr/0002-iri-identity-and-migration.md)): an IRI never names the context that owns
it, so every shape, policy and stored payment that names `:Payment` still means the
same thing. Register the ontology's notation in the seams graph as chapter 9 did for
the expense ontology.

## Importing by version IRI

The expense context still uses the finance words: `:PaymentShape` and `:VendorShape`
target `:Payment` and `:Vendor`. A context reaches another's classes the way the model
already reaches gist, by `owl:imports` of a version IRI. Add the finance version to
the expense ontology's imports, and move its own version on, because its classes
changed:

```trig
        owl:versionInfo "1.2.0" ;
        owl:versionIRI <https://example.org/expenses/expense_ontology/1.2> ;
        # Chapter 11: Payment and Vendor are the finance context's words now,
        # declared by :finance_ontology in finance.trig. This ontology imports
        # that one by its version IRI (ADR-0030 section 4); seams check finds
        # it in the same dataset before it looks in ontology/vendor/.
        owl:imports <https://w3id.org/semanticarts/ontology/gistCore14.0.0> ,
            <https://example.org/expenses/finance_ontology/1.0> .
```

An import resolves first to an ontology model in the same dataset whose
`owl:versionIRI` matches, then to the files in `ontology/vendor/`. The finance context
owns `:finance_ontology` and moves its version. If finance releases 1.1 and the expense
ontology still imports 1.0, the model does not load, and the error names the importing
ontology, `owl:imports` and both versions:

```
seams check: examples/expenses/chapter-11: cannot load the model: cannot resolve https://example.org/expenses/expense_ontology: missing http://www.w3.org/2002/07/owl#imports (imports <https://example.org/expenses/finance_ontology/1.1>; the dataset's finance_ontology is version <https://example.org/expenses/finance_ontology/1.0>)
```

The same happens if you load `expenses.trig` on its own: without `finance.trig`, the
import names no ontology in the dataset. Imported classes are read-only to the
importer. The viewer's class view draws them as it draws gist's, and the expense
context's shapes may target them, but the classes are finance's to change.

## Moving Pay Expense

Now fix what the storm showed. In `approval.bpmn`, delete the Pay Expense user task and
end the approved path at the message end event that publishes on `:payouts`, now named
**Approved**. In `payout.bpmn`, add the task between the start event and Schedule
Payout:

```xml
    <bpmn:userTask id="pay_expense" name="Pay Expense">
      <bpmn:incoming>flow_to_pay</bpmn:incoming>
      <bpmn:outgoing>flow_to_schedule</bpmn:outgoing>
    </bpmn:userTask>
```

The task's model element moves from `approval_bpmn` to the `payout_bpmn` graph in
`finance.trig`, under the payout namespace. In the seams graph, its links move with it.
Finance still completes it on `:payment_form`, and it still writes the payment:

```trig
    <https://example.org/expenses/payout_bpmn#pay_expense>
        seam:reads :ExpenseShape ;
        seam:completedOn :payment_form ;
        seam:writes :PaymentShape .
```

Point `:finance_payment_policy`'s `odrl:target` and the `seam:governedBy` fact at the new
IRI, so only finance can pay.

Whether an approved expense has been paid is now the payment lifecycle's business, so
the expense lifecycle loses `paid` and its `t_pay` transition. It ends at approved or
rejected:

```trig
    :expense_lifecycle a state:StateMachine , seam:Model ;
        rdfs:label "Expense Lifecycle" ;
        state:initial :s_draft ;
        state:hasState :s_draft , :s_submitted , :s_approved , :s_rejected ;
        state:final :s_approved , :s_rejected ;
        state:hasTransition :t_submit , :t_approve , :t_reject .
```

## The storm, after

Run the storm again on this chapter:

```sh
seams storm approval_process --project examples/expenses/chapter-11
```

The approval now ends at its message end event, and no step writes `PaymentShape`:

```
7. **Record Approval** (`record_approval`)
   - domain event: approved (`t_approve`: submitted → approved, Expense Lifecycle)
8. **Record Rejection** (`record_rejection`)
   - domain event: rejected (`t_reject`: submitted → rejected, Expense Lifecycle)
9. **Approved** (`approved_end`)
   - channel: payout requested (`payouts`)
   - process started: Expense Payout (`payout_process`) via `payouts`
```

The payout storm opens with the hand-over and the payment:

```sh
seams storm payout_process --project examples/expenses/chapter-11
```

```
1. **Payout Requested** (`payout_requested`)
   - command: Payout Requested (`payout_requested`) on channel `payouts`, published by `approved_end` (Expense Approval)
2. **Pay Expense** (`pay_expense`)
   - actor: Finance (policy `finance_payment_policy`)
   - command: Pay Expense (`pay_expense`) on `payment_form` → POST `pay_expense_op` [PaymentShape]
   - aggregate: Payment (`PaymentShape`), class `Payment`, stored in `expense_db`, lifecycle `payment_lifecycle`
```

The `:payouts` channel is the only line between the two storms.

## Generate, check and run

```sh
seams generate --project examples/expenses/chapter-11
seams check --project examples/expenses/chapter-11
```

`seams check` validates the domains, contexts and ownership against the seam shapes
and resolves the finance import from the dataset. The generated app has the same routes
as chapter 10's. The approval instance now completes as soon as the expense is
approved, and Pay Expense waits in the payout instance, in the `/tasks` inbox.

Run the host against the directory. As the test harness does, keep everything in
SQLite:

```sh
SEAMS_MODEL=examples/expenses/chapter-11 \
SEAMS_TEMPLATES=examples/expenses/chapter-11/generated/templates \
SEAMS_DB= \
SEAMS_STORE_OVERRIDE=sqlite \
python -m seams_runtime.host --routes examples/expenses/chapter-11/generated/expense_api.py --port 8002
```

Submit and approve an expense as before, then pay it as finance:

```sh
curl -X POST http://localhost:8002/expenses/hotel/payment -d reference=PAY-0042 -d paid_on=2026-10-05 \
  -H "X-Forwarded-User: carol" -H "X-Forwarded-Groups: finance"
```

The payment completes the payout instance's task, and the payout process schedules
and batches or sends it. The expense stays `approved`. To run the whole stack, start
`examples/expenses/chapter-11/compose.development.yaml` as in chapter 10.

The project file drops chapter 10's `mentalmodel` generator: a SemPKM Mental Model is
written for one ontology, and this dataset has two.

## Checkpoint

Your files should now match
[`examples/expenses/chapter-11/expenses.trig`](../../../examples/expenses/chapter-11/expenses.trig),
[`finance.trig`](../../../examples/expenses/chapter-11/finance.trig),
[`approval.bpmn`](../../../examples/expenses/chapter-11/approval.bpmn),
[`payout.bpmn`](../../../examples/expenses/chapter-11/payout.bpmn) and
[`seams.toml`](../../../examples/expenses/chapter-11/seams.toml). To see what moved,
compare chapter 10's file with the two files together:

```sh
diff examples/expenses/chapter-10/expenses.trig examples/expenses/chapter-11/expenses.trig
```

`tests/test_expense_chapter11.py` checks this chapter. It checks the two classified
domains and the two contexts, that every model but the architecture has exactly one
owner and lives in its owner's file, and that the expense ontology imports the finance
ontology by version IRI from the dataset. It also checks that `expenses.trig` alone, or
a finance version the import does not name, fails with a `ResolutionError` naming
`owl:imports`. It checks that the approval storm writes no payment and its one channel
is `:payouts`, and it serves the app: an approved expense opens Pay Expense in its
payout instance, an employee's payment is a 403, and finance's payment is batched while
the expense stays approved.

# ADR-0014: Scenarios and Derived Tests — a Model States What It Should Do, a Generator Tests It

**Status:** Accepted

**Date:** 2026-10-31

**Source:** milestone M015/S03; backlog U5; research:
[UML coverage and gaps](../research/2026-10-29-uml-coverage-and-gaps.md)

## Context

A model says what an application *is*: its processes, decisions, shapes and policies.
It cannot yet say what the application should *do* with a given input. The expense
tutorial's behaviour is checked by hand-written tests (`tests/test_expense_roles.py`,
`tests/test_expense_process_app.py`) that restate the model's facts: the routing
thresholds, the role that approves, the state an approved expense ends in. When the
model changes, those tests are edited by hand, and nothing ties a failing test back to
the model fact that broke. That breaks principle 1 (the model is the source of truth),
and leaves backlog U5 open.

UML covers this with sequence diagrams and test cases, and DMN with test-case tables. A
scenario here needs four things:

1. **A scenario**: start a process as a party with some input, complete its user tasks
   as named parties, and expect a lifecycle state or an end event.
2. **A decision example**: a decision's inputs and the output the DMN must return.
3. **A shape example**: a node a SHACL shape must accept, or must reject.
4. **A policy test**: for each ODRL permission, the assignee is allowed and every other
   party is denied.

### What DASH offers

[DASH](https://datashapes.org/dash) is the SHACL extension vocabulary pyshacl already
ships (`pyshacl/assets/dash.ttl`), and its test cases were checked first (principle 4).

- **`dash:GraphValidationTestCase`** validates the *whole* data graph and compares the
  result with a full stored `sh:ValidationReport` (`dash:expectedResult`). Rejected for
  shape examples: an example is one node checked against one shape, and the answer is
  conforms or not. Writing out the full report makes every example restate generated
  messages and result paths, which change when a shape's wording changes. And
  whole-graph validation would validate the example nodes against every shape in the
  model, not the one under test.
- **`dash:FunctionTestCase`** tests a SHACL function (`dash:expression`) against a
  `dash:expectedResult`. Rejected for decision examples: a DMN decision is not a SHACL
  function, and the decision is evaluated from its native XML (ADR-0007), not from an
  expression in the graph.
- **`dash:expectedResult`** on its own: rejected. Its domain is `dash:TestCase`, so
  using it on a decision example claims the example is a DASH test case that a DASH
  runner (TopBraid) would try to execute. Its value is one result, not a set of
  `(output variable, value)` pairs.
- **`dash:InferencingTestCase`, `dash:QueryTestCase`, `dash:ActionTestCase`,
  `dash:ScriptTestCase`, `dash:GraphStoreTestCase`** test inference rules, SPARQL
  queries, scripts and graph stores. None of them runs a process.
- DASH has no term that links a shape to an example node, and nothing for a process
  scenario.

So DASH is not reused, and the reason for each term is recorded above. Existing terms
are reused where they fit: `odrl:Party` for actors, `proc:Process` and `proc:UserTask`
for the process and its steps, `state:State` for the expected state, and **`dec:variable`**
(the DMN-side output name the runtime's output binding already uses) for a decision
example's expected output.

## Decision

### A small `verify:` vocabulary

A new namespace, `verify:` = `https://w3id.org/seams/verify#` in
[`ontology/verify.ttl`](../../ontology/verify.ttl), following the other ontology files.
It has two classes and thirteen properties:

| Term | Used on | Meaning |
|---|---|---|
| `verify:Scenario` | | One run of a process |
| `verify:process` | scenario | The `proc:Process` it runs |
| `verify:actor` | scenario, step | The `odrl:Party` who starts the process, or completes the step |
| `verify:given` | scenario, step, decision example | One input: a blank node with `verify:field` and `verify:value` |
| `verify:field` | given | The `sh:path` the value fills, e.g. `:amount` |
| `verify:value` | given, expected output | A literal |
| `verify:step` | scenario | An RDF list of steps, in order |
| `verify:task` | step | The `proc:UserTask` the step completes |
| `verify:expectState` | scenario | The `state:State` the entity ends in |
| `verify:expectEndEvent` | scenario | The BPMN end event the run finishes on |
| `verify:DecisionExample` | | One expected decision outcome |
| `verify:decision` | decision example | The `dec:Decision` it evaluates |
| `verify:expectOutput` | decision example | A blank node with `dec:variable` and `verify:value` |
| `verify:validExample` | `sh:NodeShape` | A node the shape must accept |
| `verify:invalidExample` | `sh:NodeShape` | A node the shape must reject |

A step's form values use `verify:given`, the same term as the scenario's start values, so
an outcome such as "the manager approves" is just the approval form's `:decision` field.
No separate outcome term is needed.

A scenario's process must be one a UI event `seam:triggers`, so a test starts it the way
a person does: through the route that event submits to. A channel-started process (ADR-0010)
is tested through the scenario of the process that publishes to its channel.

A scenario's expected state names the entity through the state: the entity is the one
whose shape `seam:lifecycle` holds that state. An expected end event is the BPMN end
event's IRI (ADR-0002) and is lifted into the process's model graph. A scenario now names
it, so it takes part in a cross-layer fact.

### Where scenarios and examples live

Every triple that uses a `verify:` term lives in the **seams graph**
`<urn:seams:graph:seams>`, next to the ODRL policies. ADR-0001 keeps a model graph to
layer-internal triples. Each `verify:` fact joins layers: a scenario names a process, data
paths, parties and a lifecycle state, a decision example names a decision and data paths,
and a shape example links a data shape to a node. They are cross-layer facts, but not
seam predicates. They join layers for testing, and the viewer does not navigate along
them, so they carry no `seam:reveal` mode.

A scenario could have lived in a layer graph of its own, a `seam:Model` with a new
"scenario" notation. That would add a notation, a model node and a renderer question
for a layer that has no diagram. The seams graph already holds the other cross-layer,
non-diagram facts (policies, bindings), so scenarios join them. All of a model's
verification is then one graph query.

Example nodes (the objects of `verify:validExample` and `verify:invalidExample`) live
there too. An example node carries no `rdf:type` that any shape targets, so it never makes
the model fail its own shapes. A test checks it against the one shape that names it.

### Scenarios, examples and generated tests are IRIs

A scenario, a decision example and an example node are IRIs, not blank nodes. The
generated test's name embeds the IRI's local name, so a CI failure names the model fact
that broke (`test_scenario_manager_approved`). Blank nodes have no stable name or order,
which principle 6 needs. Givens and steps stay blank nodes. Givens are sorted by field
IRI, steps keep their list order, and expected outputs are sorted by variable.

### Policy tests need no terms

Policy tests derive from what the model already says (ADR-0009). For each `odrl:Policy`
and each of its `odrl:permission`s:

- the `odrl:assignee` reaching the `odrl:target` is allowed. The target is either an
  operation (its submitting route) or a user task (completing it);
- every other declared `odrl:Party` is denied with the `PolicyDenied` problem response
  (403);
- a request with no identity is denied with 401.

So the number of policy tests is fixed by the model: one per permission for each party,
plus one no-identity case per permission.

### Shapes

[`ontology/shapes/seam-shapes.ttl`](../../ontology/shapes/seam-shapes.ttl) gets a
"Scenarios and examples" section. Each constraint is a fault the tests generator would
otherwise reject (principle 5):

- **`seamsh:ScenarioShape`**: a scenario is an IRI typed `verify:Scenario`, with exactly
  one `verify:process` (a `proc:Process` some event `seam:triggers`) and one `verify:actor`
  (an `odrl:Party`). It has at most one `verify:step`, which is an RDF list whose members
  each have one `verify:task` (a `proc:UserTask` in the process's model) and one
  `verify:actor`. It has at least one expectation. `verify:expectState` is a `state:State`
  of a lifecycle some shape names, and `verify:expectEndEvent` is an IRI in the process's
  model.
- **`seamsh:GivenShape`** and **`seamsh:GivenUniqueShape`**: a given has exactly one IRI
  `verify:field`, which is the `sh:path` of some shape property, and exactly one literal
  `verify:value`. No subject gives the same field twice.
- **`seamsh:DecisionExampleShape`**: an IRI typed `verify:DecisionExample`, with exactly
  one `verify:decision` (a `dec:Decision`). Its given fields are exactly the decision's
  `dec:input` `dec:fromPath`s, none missing and none extra. It has at least one
  `verify:expectOutput`, each with one string `dec:variable` naming one of the decision's
  `dec:output`s and one literal `verify:value`.
- **`seamsh:ShapeExampleShape`**: only a `sh:NodeShape` has examples, examples are IRIs,
  and no node is both a valid and an invalid example of one shape.

Two conditions stay generator-only. A user task or end event named in the graph but
missing from the BPMN XML is caught when the generator or the runtime reads the XML.
SHACL cannot read it. A given value whose lexical form does not fit the field's
`sh:datatype` makes the generated test fail, which is the point of the test.

### Example

This is the expense model's manager-approved scenario, its decision example and a pair of
shape examples, with the facts they point at. In a TriG model the first block of triples
lives in the model graphs, and the rest live in the seams graph.

```turtle
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix ifml:   <https://w3id.org/seams/ifml#> .
@prefix proc:   <https://w3id.org/seams/proc#> .
@prefix dec:    <https://w3id.org/seams/dec#> .
@prefix state:  <https://w3id.org/seams/state#> .
@prefix odrl:   <http://www.w3.org/ns/odrl/2/> .
@prefix verify: <https://w3id.org/seams/verify#> .
@prefix :       <https://example.org/expenses/> .

# Model graphs: the facts the scenario and examples point at.
:approval_bpmn a seam:Model .
:approval_process a proc:Process ; seam:inModel :approval_bpmn .
<https://example.org/expenses/approval_bpmn#approve_expense> a proc:UserTask ;
    seam:inModel :approval_bpmn .
<https://example.org/expenses/approval_bpmn#approved_end> a proc:MessageThrowEvent ;
    seam:inModel :approval_bpmn .
:submit_expense a ifml:Event .
:ExpenseShape a sh:NodeShape ;
    sh:property [ sh:path :description ; sh:datatype xsd:string ; sh:minCount 1 ] ;
    sh:property [ sh:path :amount ; sh:datatype xsd:decimal ; sh:minCount 1 ; sh:minInclusive 0.01 ] ;
    sh:property [ sh:path :date ; sh:datatype xsd:date ; sh:minCount 1 ] .
:ApprovalShape a sh:NodeShape ;
    sh:property [ sh:path :decision ; sh:datatype xsd:string ; sh:minCount 1 ] .
:expense_lifecycle a state:StateMachine ; state:hasState :s_submitted , :s_approved .
:s_submitted a state:State .
:s_approved a state:State .
:approval_routing a dec:Decision ;
    dec:input [ a dec:InputBinding ; dec:variable "amount" ; dec:fromPath :amount ] ;
    dec:output [ a dec:OutputBinding ; dec:variable "Route" ; dec:processVariable "route" ] .
:employee a odrl:Party .
:manager a odrl:Party .

# Seams graph: the seams they rely on, then the scenario and examples.
:approval_bpmn seam:notation seam:BPMN ; seam:renderPayload <approval.bpmn> .
:submit_expense seam:triggers :approval_process .
:ExpenseShape seam:lifecycle :expense_lifecycle .

:manager_approved a verify:Scenario ;
    verify:process :approval_process ;
    verify:actor :employee ;
    verify:given [ verify:field :description ; verify:value "Train to Leeds" ] ,
                 [ verify:field :amount ; verify:value 200.00 ] ,
                 [ verify:field :date ; verify:value "2026-10-01"^^xsd:date ] ;
    verify:step ( [ verify:task <https://example.org/expenses/approval_bpmn#approve_expense> ;
                    verify:actor :manager ;
                    verify:given [ verify:field :decision ; verify:value "approved" ] ] ) ;
    verify:expectState :s_approved .

:routes_mid_amounts_to_manager a verify:DecisionExample ;
    verify:decision :approval_routing ;
    verify:given [ verify:field :amount ; verify:value 200.00 ] ;
    verify:expectOutput [ dec:variable "Route" ; verify:value "manager" ] .

:ExpenseShape verify:validExample :expense_train ;
    verify:invalidExample :expense_negative_amount .
:expense_train :description "Train to Leeds" ; :amount 42.50 ; :date "2026-10-01"^^xsd:date .
:expense_negative_amount :description "Refund" ; :amount -5.00 ; :date "2026-10-01"^^xsd:date .
```

### Generated tests

A new `tests` generator (T03, T04) writes pytest files to **`generated/tests/`** in the
example's directory. It is listed in `seams.toml` like any other generator, its outputs
are committed, and `seams.lock` tracks them, so the "Generated outputs are current" CI
step catches drift:

| File | One test per |
|---|---|
| `test_scenarios.py` | `verify:Scenario`. It drives the host app in-process (`seams_runtime.host.build_app` on a temporary store), acting as each named party |
| `test_decisions.py` | `verify:DecisionExample`. It evaluates the DMN through the runtime's evaluator |
| `test_shape_examples.py` | valid or invalid example. pyshacl must conform, or must not |
| `test_policies.py` | permission × party, plus a no-identity case per permission |

Each file carries the generator's header and the model hash (principle 7). Test names
embed the local names of the scenario, example or policy they check. All data comes from
the model, and the templates hold no domain literals (principle 1). Because CI collects
only `tests/`, a test there (T05) runs the generated suite.

## Alternatives Considered

- **Reuse DASH test cases.** Rejected, term by term, in "What DASH offers" above.
- **A scenario layer graph with its own notation.** Rejected: it needs a new notation,
  a model node and a renderer question, and buys nothing over the seams graph, which
  already holds the cross-layer facts that have no diagram.
- **Scenarios as seam predicates (`seam:expects…`).** Rejected: seam predicates are the
  viewer's navigation edges and each declares a reveal mode (ADR-0005). Scenario facts
  are test data, so navigating along them would only clutter every view.
- **A separate outcome term for steps (`verify:outcome "approve"`).** Rejected: the
  outcome of a user task is the form it is submitted with. `verify:given` on the step
  says that already, and covers tasks with more than one field (the payment form).
- **A decision example's output as a bare literal.** Rejected: it only works for
  single-output decisions. `dec:variable` already names DMN outputs.
- **Policy-test terms (`verify:allowedFor` …).** Rejected: the ODRL policy already says
  who may reach what, and restating it would break principle 1.
- **Blank-node scenarios and examples.** Rejected: their tests could not be named or
  ordered stably.

## Consequences

- **T01** (this ADR) adds `ontology/verify.ttl` and the shapes above.
- **T02** declares scenarios, decision examples and shape examples in expense chapter 9.
- **T03** adds the `tests` generator for scenarios, decision examples and shape examples.
  **T04** adds the policy tests. **T05** runs the generated suite in CI.
- Models with no `verify:` triples are unaffected. Their `tests` output is empty files with
  headers, if they list the generator at all.
- The tests that restate expense facts by hand can later shrink to what the model cannot
  say. S04 adds coverage queries over these terms.

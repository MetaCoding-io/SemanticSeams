# ADR-0043: Latency Budgets — an `nfr:LatencyBudget` on a Flow Node or Operation Is a Model Fact, Checked Against the `obs:duration` of the Steps That Measured It at a Nearest-Rank Percentile, and Reported Met, Missed or Unobserved

**Status:** Accepted

**Date:** 2026-11-15

**Source:** milestone M032/S02; backlog X2 (non-functional requirements); research note
[UML coverage and gaps](../research/2026-10-29-uml-coverage-and-gaps.md) section 3.7;
answers the timing open question of
[ADR-0042](./0042-as-observed-graph.md); builds on
[ADR-0001](./0001-named-graph-partitioning.md),
[ADR-0002](./0002-iri-identity-and-migration.md),
[ADR-0007](./0007-execution-strategy.md) and
[ADR-0021](./0021-vocabulary-versions.md)

## Context

ADR-0042 loads recorded runs as an as-observed graph beside the model and answers two
questions with it: which model elements no run reached, and which steps the model does
not explain. Both are about *what* ran. Backlog X2 asks the next question, *how well*:
a service-level objective such as "approving an expense answers within 300 ms" is a
requirement on the application, so it belongs in the model, and the observations are
what it is checked against.

Two things are missing:

- **A vocabulary to state the requirement.** No layer vocabulary says how long an
  element may take. The bound is not a seam (it joins no two layers, ADR-0001) and not
  part of a notation's own vocabulary.
- **Step timing.** ADR-0042 left timing open: trace rows carry no times, and the
  as-observed graph records none. OTLP spans do carry `startTimeUnixNano` and
  `endTimeUnixNano`.

What must not change: the model is the source of truth and read-only; `Model.hash` reads
only the model's files and payloads; the as-observed graph stays outside the model.

## Decision

### 1. The `nfr:` vocabulary

A new vocabulary, `ontology/nfr.ttl`, at `https://w3id.org/seams/nfr#` (prefix `nfr:`,
ontology IRI `https://w3id.org/seams/nfr`, version `https://w3id.org/seams/nfr/1.0` per
ADR-0021), with one class and three properties:

| Term | Kind | Meaning |
|---|---|---|
| `nfr:LatencyBudget` | class | An upper bound on how long one element may take, at one percentile of its observed durations |
| `nfr:budgetOf` | property, exactly one | The IRI of the element the budget bounds |
| `nfr:maxMilliseconds` | property, exactly one | The bound in milliseconds: an `xsd:decimal` (an `xsd:integer` is one) greater than 0 |
| `nfr:percentile` | property, at most one | The percentile the bound applies to, greater than 0 and at most 100; absent means 100 |

```turtle
@prefix nfr: <https://w3id.org/seams/nfr#> .
@prefix :    <https://example.org/expenses/> .

<urn:seams:graph:model:expense_architecture> {
    :approve_budget a nfr:LatencyBudget ;
        nfr:budgetOf :approve_expense_op ;
        nfr:maxMilliseconds 300 ;
        nfr:percentile 95 .
}
```

**The element** is named by its IRI (ADR-0002) and is one of two kinds:

- **A BPMN flow node**, by its BPMN model's IRI, `#` and the node id. Its steps are those
  whose `obs:reached` is the IRI.
- **A `hydra:Operation`**. Its steps are those whose `obs:invokes` is the IRI: the
  service tasks that invoked it, whichever process they belong to.

The element is not checked against the graph: a flow node no seam names has no triples
(ADR-0007), so a shape cannot tell a flow node from a typo. A budget of an element no
step measured is reported unobserved (section 3), which shows the mistake as soon as
there are observations.

### 2. Where budgets live

**A budget is a model fact.** It is written in a model's named graph: the BPMN model's
graph for one of its flow nodes, and the architecture (C4) model's graph for an
operation, since the containers that serve operations are declared there and the
operations themselves are declared beside the seams. It is not a seam, so it never goes
in the seams graph (ADR-0001) or the manifest graph (ADR-0021), and it is never written
in an as-observed graph. The check reads budgets from every model graph, so the
placement is a convention the shapes do not enforce. Like every other model triple, it enters
`Model.hash`: changing a budget changes the model. Nothing generated reads a budget, so
the generators' outputs do not change when one is added.

The seam shapes check every budget (`seamsh:LatencyBudgetShape`): exactly one
`nfr:budgetOf`, an IRI; exactly one `nfr:maxMilliseconds`, a number greater than 0; at
most one `nfr:percentile`, a number in (0, 100]; the subject an IRI typed
`nfr:LatencyBudget`; and at most one budget per element and percentile (an absent
percentile counts as 100). Each message names the predicate. A model with no budget is
unaffected.

### 3. Step timing and the check

**`obs:duration`** (obs 1.1, a compatible widening): how long a step took, in
milliseconds, as an `xsd:decimal`: `(endTimeUnixNano - startTimeUnixNano) / 1e6` of the
element span. The two nanosecond times are integers; a span whose end is before its
start, or whose times are not integers, is refused with
`ResolutionError(span, "endTimeUnixNano", detail)`, naming the span. **Trace rows carry
no times, so a step read from trace rows has no `obs:duration`.** The duration is the
only timing the graph carries: start and end times are not facts the budgets need, and
leaving them out keeps the graph the same for the same spans.

**The check** joins the model's budgets with one as-observed graph, as ADR-0042's
questions do, without mutating either. For each budget:

1. The samples are the `obs:duration` of every step that measured the element
   (section 1). Steps with no duration are not samples.
2. With `n` samples sorted ascending, the observed value is the one at position
   `ceil(p / 100 × n)` (1-based), the **nearest-rank** percentile of `p`. It is always
   one of the observed durations, so the result needs no interpolation and is the same
   on every platform.
3. The verdict is:
   - **met** when the observed value is at most `nfr:maxMilliseconds`;
   - **missed** when it is above;
   - **unobserved** when there are no samples (no run reached the element, or only
     trace rows were loaded); the observed value is then absent.

Each result names the budget, the element, the bound, the percentile, the observed value,
the number of samples and the verdict, and the results are sorted by element then
budget IRI. `seams.budget_results(model, graph)` computes them (S02/T02); `seams
observed` and the viewer's Questions panel report them (S02/T03).

## Alternatives considered

- **Budgets in a side file or an as-observed graph.** Rejected: a budget is a
  requirement on the application, stated once for every deployment, which is what the
  model is for; observations are one deployment's history.
- **A seam predicate** (`seam:latencyBudget`). Rejected: a budget joins no two layers,
  and seam predicates are reserved for the joins (ADR-0001).
- **Interpolated percentiles.** Rejected: they report a value no run produced and differ
  between methods; nearest rank is the simplest definition that is exact.
- **Recording start and end times.** Rejected for now: the check needs only durations,
  and absolute times would make the graph depend on when the runs happened rather than
  on what they did. A later question (throughput, time of day) can add them as another
  compatible widening.
- **Timing from trace rows.** Rejected: the worker records no times in rows, and adding
  them would change every recorded trace; spans already carry them.
- **Error-rate and availability objectives.** Left out: X2 starts with latency, the one
  objective the observations can already answer per element. Other objectives are new
  classes in `nfr:` later.

## Consequences

- `ontology/` gains `nfr.ttl` at 1.0, and `obs.ttl` moves to 1.1 with `obs:duration`;
  the layer vocabularies reference page lists `nfr`.
- `ontology/shapes/seam-shapes.ttl` gains `seamsh:LatencyBudgetShape`.
- `seams.spans_to_runs` carries each element span's duration and `seams.observed_graph`
  writes it as `obs:duration`; `seams.budget_results` checks the budgets (S02/T02).
- `seams observed` prints a budgets section and the viewer answers a latency-budgets
  question (S02/T03).

## Open questions

- **Budgets on a whole process** (start to end of a run). The instance span carries the
  run's times, but the as-observed graph has no run duration yet.
- **Several deployments.** As in ADR-0042, one graph per load.

## Revision notes

None yet.

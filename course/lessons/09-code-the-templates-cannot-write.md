# Lesson 9 · Code the templates cannot write

*A stub written once and then owned, errors declared in the model, and a language model
that drafts behind the stub while tests derived from the model decide. The project's answer
to the first failure, past the cliff.*

## Outcomes

After this lesson you can:

- Locate the expressiveness cliff in a SemanticSeams model exactly: the operation that is
  `seam:implementedBy` a Python handler, and nothing else.
- Explain the stub-once-then-owned rule and what the generator does and does not do to a
  handler on regeneration.
- Write a service-task handler, declare the error it can raise and the boundary event that
  catches it, run the acceptance tests the model derives for it, and, optionally, have a
  language model draft it under the same tests.

## The story

### Where the cliff is, exactly

Lesson 2 said the problem with declarative languages is not that they end but that nobody
marks where. Lesson 7 pushed the edge a long way out: process order, decisions,
validation, lifecycle and policy all run from the model, so none of them is code anyone
writes. What is left is the body of a task whose work happens outside the model. The
tutorial meets it at "Notify Manager": send the manager a message about an expense that
is waiting. No shape, table or statechart says how to compose a message, and no engine
sends one.

[ADR-0012](../../docs/adr/0012-operation-implementation.md) marks the spot with one
predicate. An operation is `seam:implementedBy` an implementation node whose type is its
kind: an LLM completion, which is how the chat app's completion operation had always
worked without the graph saying so; an HTTP endpoint on another container; or a Python
handler, a function in a handlers package beside the model, named by a dotted path. The
predicate sits on the operation, not on the task, because the operation is the contract
and every task that invokes it gets the same implementation. The kind is a class, so the
shapes can check it, and each kind must agree with where the operation is served: a
Python handler runs in the runtime's process, so its operation must be exposed by the
container that executes the process. In the lab you write exactly this: a notification
shape, an operation that accepts an expense and returns a notification, an implementation
node of the Python kind, and a handler path that resolves to one function in one file.

Two guarantees come with the location. The handler path is resolved only inside the
handlers package, segment by segment, so a model cannot make the runtime import code its
owner did not put there. And the handler never sees the store, the bus, the lifecycle or a
secret: it takes the validated entity as a plain dictionary and returns one, which the
runtime validates against the returned shape and stores, firing whatever transition the
task declares. The handler only computes.

### The stub is written once

The hand-written half still has to fit the generated half, and that is what the stub is
for. A stub generator writes the handlers package once: an `__init__`, a module per
handler, and for each one a typed signature built from the shapes. The accepted shape
and the returned shape become typed dictionaries, with a decimal amount typed as a
`Decimal`, an optional field marked as not required, and the function signature using
both. The docstring says which task invokes the operation, which decision routes to it
and which transition it fires, read from the same context the runtime uses. The body
raises "not implemented" with the operation's name in it. Two header lines record the
model hash and the context hash the stub was written from, and a trace sidecar links each
stub line to its model terms.

Then the file is yours. The chapter says it in one sentence: run the command again and it
writes nothing, because a file in the handlers package that exists is never opened for
writing. The stub generator is not in the project's generator list, so `seams generate`
never runs it and the lock never records its files; the handlers directory is linted like
any other code; and the committed handler in the tutorial still has the older signature
an earlier stub generator wrote, which the chapter leaves alone on purpose, because owned
code stays as it is. That is principle 8 as a mechanism rather than a rule: generated
files are never edited by hand, owned code lives in its own files behind a generated
stub, and the two never share a file. Lesson 3's workarounds, protected regions and
generation gaps, were conventions enforced by comments. Here the boundary is a directory
the generator does not visit and a predicate that says what lives there.

What checks the fit is not the header. The chapter is candid that nothing reads the two
hashes, so they can go stale without harm. The fit is checked by the runtime at load,
which refuses a handler path that no longer resolves and names the implementation node and
the predicate, and by the tests of the next section.

### Failure is declared, and routed

A handler that raises an exception the model knows nothing about fails the instance, and
the error names the operation. That is the right default and the wrong ending for a
business process, so the chapter adds the second half of
[ADR-0013](../../docs/adr/0013-error-shapes-and-boundaries.md). The operation declares a
possible status: a 502 with an error code, "notify-failed", whose body is a shape over RFC
9457 problem details, with a required title and status and an optional detail. The handler
raises an `OperationError` with that code and a detail when the message is too long for a
text message. And the BPMN gains an error boundary event on the task, with the same error
code in the XML, whose outgoing flow escalates the expense to finance. In the graph the
boundary is lifted and `seam:catches` the declared status; the attachment and the code
stay in the XML, and the runtime checks that the two agree when it loads.

What you see in the lab is the whole route. A 161-character description gets a problem
body with the title and status filled in from the model and the detail from the handler.
The trace shows the error and the boundary that caught it. The manager has no task; finance
does. The viewer's seam badge reads "catches" with the status's label. The failure path is
a fact in the diagram, not a `try` block the model cannot see, and the generated route
passed the error along without knowing what it meant, which is rule one of lesson 7
holding under pressure.

### Tests derived from the model

Lesson 3 asked how you verify code you did not write. The project's answer is to let the
model write the tests. [ADR-0014](../../docs/adr/0014-scenarios-and-derived-tests.md)
gives a model a small vocabulary for saying what it should do: a scenario starts a process
as a party with some input, completes its user tasks as named parties, and expects a
lifecycle state or an end event; a decision example names the inputs and the output a
table must return; a shape names a node it must accept and one it must reject; and every
policy permission implies that the assignee is allowed and every other party denied. A
generator turns those facts into pytest files, and `seams coverage` lists the paths,
transitions and permissions no scenario or test exercises. Chapter 9 runs it, finds five
paths uncovered, writes the scenarios, and turns path coverage into a gate.

A second generator writes acceptance tests for the handler itself: a type check against
the stub's typed dictionaries, shape conformance of the result for each valid example or a
declared error status, the legal-transition guard for the transition the task fires, and
the decision's routing to the task. The chapter's remark is the point: the tests import
your handler, so they test the code you own, not the stub. These are the tests any draft
must pass before it is accepted, whoever or whatever wrote it.

### A language model behind the stub

Now the newest generator from lesson 3, under the oldest discipline.
[ADR-0020](../../docs/adr/0020-llm-drafts.md) lets `seams propose` ask a language model for
a handler body, and every rule in it answers a failure from lesson 4. The provider is a
command named in the project file that reads a prompt on standard input and writes a
draft to standard output; the repository holds no SDK, no key and no network code, so any
model, or a person, or a fake in a test can answer. The prompt is deterministic and
versioned, filled from the same context the stub cites, the stub and the acceptance tests,
and every piece of model text sits in a block the prompt declares to be data, never
instructions. Bindings appear by name only; no secret value is read. The response is cached
by the hash of the context, the template, the provider and the model name, so the same
facts give the same draft for free and a changed fact misses the cache.

Then the test. The project is copied to a scratch directory, the draft is written at the
handler's path there, and the acceptance tests run. Only on pass is the draft written into
the handlers package, and only there; an existing module is replaced only when you ask.
On failure nothing is written and each failing test is named. An accepted draft is recorded
in the lock with its context hash and file hash, so `seams check` can later say
`draft-stale` when a fact it was written from changes and `draft-hand-edited` when the
file does, and from that moment the file is ordinary owned code: the chapter tells you to
read it before you commit it, like code you typed. Continuous integration runs the
acceptance tests against committed handlers and never calls a provider.

The chapter opens with a line worth keeping beside all of this, about why the notification
is not itself an LLM call: plain code gives the same message for the same expense every
time, tests can check it, and it costs nothing to run. Use a language model only for work
that needs one. Everything else is a function.

### The cliff, closed

Against lesson 4's test for F1, where does the first `if` about the business live, the
answer is now a file in a directory the generator never visits, reached through one
predicate, typed by the shapes, checked by tests the model derived, and refused at load if
it stops fitting. A language model may write it, under tests it did not write, and its
acceptance is recorded so that its staleness can be reported. The expressiveness cliff is
still there. It is simply marked, fenced and watched, which is what lesson 2 said a fix
would have to do. The lab is chapter 9.

## Read in the repo

- [ADR-0012](../../docs/adr/0012-operation-implementation.md) and
  [ADR-0020](../../docs/adr/0020-llm-drafts.md).
- [An LLM generator for the code templates cannot
  write](../../docs/research/2026-10-31-llm-generator.md). The argument, and its revision
  notes recording C1 to C5 as they shipped.
- The prompt template itself,
  [`draft-v1.txt`](../../packages/seams-cli/src/seams_cli/prompts/draft-v1.txt). Notice how
  the model's facts are quoted.

## Lab: chapter 9

Work through [chapter 9, Hand-written code](../../docs/tutorials/expenses/09-hand-written-code.md):
the Notify Manager service task, the operation and its implementation, the stub, the
handler, and the error path. Then:

1. Run `seams generate` again and confirm the handler is untouched. Run `seams check` and
   read what it says about the stub's context hash.
2. Change the shape the handler accepts, by adding a required field, and run the
   acceptance tests. Read the failure: it is the model telling the owned code it has
   drifted.
3. Optional, with a provider command: run `seams propose` for the notify task, with
   `--force` since the handler exists, read the draft before you accept it, and find its
   record in `seams.lock`. Then change one fact the handler depends on and run
   `seams check`: the record is reported as `draft-stale`. Without
   a provider, read the prompt template and write down what the language model is and is
   not allowed to see.

Diff against `examples/expenses/chapter-09/expenses.trig` and
[`examples/expenses/chapter-09/handlers/`](../../examples/expenses/chapter-09/handlers/)
when done.

## Scorecard

- **F1, closed.** The cliff is one predicate. The hand-written code sits behind a generated
  stub in its own file, the generator never visits it, and a change to the facts it depends
  on is reported rather than overwritten.
- **F6, moved.** The language model is a generator whose output is admitted only by tests
  the model derived, and never in continuous integration.
- **F2, framed.** The owned code knows its facts by hash. Lesson 10 is about edits in the
  other direction.

## Further reading

- Thomas Stahl and Markus Völter, *Model-Driven Software Development*, 2006, on the
  separation of generated and manual code, which this lesson implements with a predicate
  instead of a convention.
- IETF, *RFC 9457*, problem details, the error contract.
- The project's [domain vocabulary as spec note](../../docs/research/2026-11-03-domain-vocabulary-as-spec.md),
  on what a coding agent should be given from the model, and what it must never be the
  source of.

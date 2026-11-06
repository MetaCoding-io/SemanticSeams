# Lesson 2 · Saying what, not how

*Declarative programming from the relational model to shapes, hypermedia and desired
state. It wins in a closed domain with a trusted evaluator, and falls off a cliff outside
it.*

## Outcomes

After this lesson you can:

- Define declarative programming in one sentence and name the two conditions under which
  it has succeeded at scale.
- Read a TriG file, a SPARQL property path and a SHACL shape well enough to follow the
  rest of the course, and say what each is for.
- Explain the difference between a vocabulary that *infers* and a shape that *rejects*,
  and why that difference cost the SemanticSeams project its first review.

## The story

### Logic plus control

Robert Kowalski's formula from 1979, "algorithm = logic + control", is the cleanest
statement of what declarative means. An algorithm has a part that says what is true, or
what is wanted, and a part that says in what order to work it out. A declarative language
lets you write the first part and hands the second to an evaluator. The promise is
twofold: the statement is readable and checkable on its own, and the evaluator may be
smarter than you about the control.

Every declarative success in this lesson has the same shape. There is a closed domain,
small enough that the evaluator can be complete. There is a trusted evaluator, one whose
answers you do not have to debug. And there is an escape hatch, for the day the domain
turns out not to be closed. The history of declarative programming is largely the history
of what happened at the hatch.

### The relational bet

Edgar Codd's relational model (1970) and the query language that grew from it, SQL,
standardised in 1986, is the one declarative language in daily use by most of the world's
programmers. You write what rows you want. The optimizer decides how to get them. The
domain is closed: tables, rows, a handful of operators. The evaluator is trusted: nobody
reads a query plan unless something is slow. And the model, the schema, is the thing that
runs, which is why the entity-relationship diagram from lesson 1 survived.

The relational bet also shows the hatch. When the question is not relational, you fall
into stored procedures, user-defined functions and application code, and the hatch
becomes most of the program. SQL did not fail at this; it simply ends, and what lies past
the end is written by hand. Keep that picture. It is the whole of failure F1 in lesson 4,
and lesson 9 is about where SemanticSeams puts the hatch.

### Logic and rules

Prolog (1972) made logic itself the language, and Datalog cut it down to the part that
always terminates. Production-rule systems took a different route: Charles Forgy's Rete
algorithm (1979) made it practical to match thousands of if-then rules against changing
facts, OPS5 and CLIPS carried it into expert systems, and Drools (2001) carried it into
Java shops as the "business rules engine". The business-rules movement of the 1990s argued
that the rules of a business should be stated once, in a form the business could read, and
executed by an engine rather than scattered through code.

Decision tables are the oldest form of this, in use since the late 1950s, and the one that
survived best, because a table is legible to the person whose rule it is. DMN (2015)
standardised them with explicit hit policies, so that the evaluator's behaviour when more
than one row matches is a declared property of the table rather than an accident of the
engine. The SemanticSeams project outline calls decision tables "the single most
business-legible artifact in the entire stack", and lesson 7 shows a rule changing with no
code changing.

Rule engines stalled at two places. Ordering: when rules interact, the evaluator's control
is no longer something you can ignore, and debugging a rule base means reading the engine's
mind. And language: rules written in a vendor's dialect were owned by the vendor. Both
return as F4 and F6.

### Schemas, shapes and the open world

A schema is a declarative statement about data, and generations of them have been
evaluated by machines: database constraints, Document Type Definitions, XML Schema (2001),
JSON Schema. The Resource Description Framework (1999, revised 2004 and 2014) added a
twist that matters for this course. RDF data is a graph of triples, subject, predicate,
object, where every node has a global identifier, an IRI, and the vocabulary that describes
the data is itself data in the same graph. OWL (2004, 2009) describes classes and
properties in a logic that *infers*: if a property's range is a class, then anything the
property points at is inferred to be a member of that class. Nothing is ever rejected.

That is the open-world assumption, and it is right for the web and wrong for an
application. An application needs to say "this field is required, this value is a number
between these bounds, this shape must have exactly one of these", and have the data refused
when it does not. The Shapes Constraint Language, SHACL (2017), is that: a shape is a
declarative description of what a valid node looks like, and a validator *rejects*. A
shape can also drive a form (SHACL 1.2 UI continues DASH), describe an API payload and
generate a test. One statement, four uses. Lesson 6 is about shapes doing triple duty.

The project learned the inference-versus-rejection distinction the hard way, and the
record is in the repository. Its first external reviews, in July 2026, found that the seam
ontology used `rdfs:domain` and `rdfs:range` to constrain which kinds of element a seam
could join, and that those declarations constrained nothing: an RDFS range infers, it does
not reject. The flagship cross-layer queries returned zero rows because the data they
assumed was never checked. The fix was a SHACL shapes file over the model itself, and a
test suite that validates every example against it. You will read the triage in lesson 4.

Alongside RDF came SPARQL (2008, 1.1 in 2013), the query language, with property paths
that let one pattern follow a chain of predicates of unknown length. That one feature is
what makes a question like "which screens can eventually write this data" a single query,
and lesson 8 is built on it. Turtle and TriG (2014) are the text forms you will read and
write; JSON-LD (2014) is the same graph as JSON for an API.

### Declarative interfaces and desired state

Two more declarative traditions bear on the course. The first is hypermedia. Roy Fielding's
dissertation (2000) described the web's architecture as state transitions driven by links
and forms the server sends, and HTML forms and XForms (2003) are declarative descriptions
of an interaction. The single-page application turned away from that toward imperative
client code; htmx (2020) turned back, with a handful of attributes that say what a click
fetches and where the result goes. The project outline makes the historical point: IFML, a
2013 standard for modelling user interaction as containers, components, events and flows,
describes the same machine htmx returned to, which is why IFML generates to htmx so
cleanly.

The second is desired state. A Makefile, a Kubernetes manifest, a Terraform plan and a
compose file all say what should exist, and a controller works out how to get there.
Infrastructure became declarative at scale in the 2010s for the relational reason: a closed
domain and a trusted evaluator. In SemanticSeams the deployment layer is desired state in
the graph, and the compose files are generated projections of it (lesson 11).

A last example to keep in mind: the spreadsheet (VisiCalc, 1979) is, as Simon Peyton Jones
observed in 2003, the most widely used functional language in the world. It succeeded with
non-programmers because every cell shows its own value and the evaluator is instant and
visible. Trust in the evaluator came from seeing it work.

### Where it stalls

Two failures recur. The first the project outline calls the **expressiveness cliff**: a
declarative language ends, and what lies beyond the edge is written imperatively in the
hatch, and the hatch grows until it is the program. Rule engines grew Java callouts.
Low-code platforms grew script blocks. SQL grew stored procedures. The lesson is not to
avoid the cliff. It is to know exactly where it is, mark it in the model, and keep what is
beyond it from mixing with what is before it.

The second is **trust**. A declarative statement is only as good as its evaluator, and an
evaluator you cannot see into cannot be debugged. The spreadsheet earned trust by showing
every value; the rule engine lost it by hiding the ordering. In lessons 10 and 11 you will
see the project's answer: every generated line traces to the facts behind it, and every
generator produces the same bytes from the same model.

## Read in the repo

- [`examples/chat-app/chat-app.trig`](../../examples/chat-app/chat-app.trig). Open it and
  find the named graphs: one block per model, and one block holding every seam. You do not
  need to understand each triple. Notice that the prefixes at the top are the only place
  vocabulary IRIs are spelled out, and that each element has one IRI used everywhere it is
  mentioned.
- [`docs/queries/what-writes-shape.rq`](../../docs/queries/what-writes-shape.rq). One
  SPARQL query, mostly a property path. Read the comment, then the path: alternatives
  separated by `|`, inverses marked `^`, repeated by `+`.
- [Cross-layer queries](../../docs/concepts/cross-layer-queries.md). How the catalog works
  and how continuous integration keeps it honest.

## Lab: read three declarative texts

1. **A graph.** In `examples/chat-app/chat-app.trig`, find the triple that gives the chat
   page its title (`ifml:title "Chat"@en`). Then find every other place the page's IRI is
   mentioned. Each is a fact about the same resource; none of them repeats the title.
2. **A query.** Start the viewer and open the chat app's **Message** shape. Under Questions,
   press **What writes this shape?** Compare the rows with the path in
   `what-writes-shape.rq`: the hops it names are the hops the viewer walked. Then run the suite's version of the same assertion and find the
   expected rows in it:

   ```sh
   pytest -q tests/test_acceptance.py -k what_writes
   ```

3. **A shape.** Run the checker and read its output:

   ```sh
   seams check --project examples/chat-app
   ```

   The eleven `review` lines are model-review warnings, not shape violations, and the exit
   code is zero. Now open `ontology/shapes/seam-shapes.ttl` and find the shape that says a
   `seam:Model` has exactly one `seam:notation`. That is a constraint over the *model*, not
   over business data: the project's method applied to itself.

Write down one sentence for each text: what it declares, and what evaluates it.

## Scorecard

Seeds for [lesson 4](04-why-it-kept-stalling.md):

- **F6, trust in the evaluator.** The spreadsheet earned trust by showing every value, the
  rule engine lost it by hiding its ordering, and the SemanticSeams review found a
  vocabulary that constrained nothing because its evaluator inferred instead of rejecting.
- **F1, by way of the cliff.** Every declarative language ends, and what lies past the end
  is written by hand. Where it ends, and how the two sides are kept apart, is the question.

## Further reading

- Robert Kowalski, "Algorithm = Logic + Control", *Communications of the ACM*, 1979.
- E. F. Codd, "A Relational Model of Data for Large Shared Data Banks", *Communications of
  the ACM*, 1970.
- Charles Forgy, "Rete: A Fast Algorithm for the Many Pattern/Many Object Pattern Match
  Problem", *Artificial Intelligence*, 1982.
- Roy T. Fielding, *Architectural Styles and the Design of Network-based Software
  Architectures*, dissertation, 2000, chapter 5.
- Simon Peyton Jones, Alan Blackwell and Margaret Burnett, "A User-Centred Approach to
  Functions in Excel", *ICFP*, 2003.
- W3C, *SHACL: Shapes Constraint Language*, 2017; *SPARQL 1.1 Query Language*, 2013;
  *RDF 1.1 TriG*, 2014.
- Dean Allemang, James Hendler and Fabien Gandon, *Semantic Web for the Working
  Ontologist*, third edition, 2020. The open world, explained for people who build things.
- Carson Gross, Adam Stepinski and Deniz Akşimşek, *Hypermedia Systems*, 2023. htmx's own
  account of why it went back.

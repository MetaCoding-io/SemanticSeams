# Lesson 10 · Getting changes back into the model

*The generation trace, the lock, write-back from an output line, and a copilot that
proposes model patches. The project's answer to the second failure, in tiers.*

## Outcomes

After this lesson you can:

- Explain the three tiers of bidirectionality the project chose, navigate, write back a
  literal, propose a structural change, and why it refused a general bidirectional
  transformation language.
- Trace an output line to its facts in the viewer's generation view and send an edit back
  as a one-triple patch that is accepted only when regeneration reproduces it.
- Describe the one write path, why it edits TriG text in place, and how a copilot's
  suggestion waits for a person.

## The story

### Record, do not reverse-engineer

Round-trip engineering, lesson 3 said, failed in both directions: the forward trip lost
the method bodies, and the reverse trip tried to recover a model from code that had
already lost the model's intent. The project's research note on the subject draws the
opposite conclusion from the same history. Do not reverse-engineer anything. Record, at
generation time, where every line came from, and then every later question about an
edited output has an answer that was written down rather than guessed.

[ADR-0019](../../docs/adr/0019-generation-trace.md) is the record. Beside every generated
file sits a sidecar, `<output>.trace.json`, with one entry per non-blank line of the
output: the template lines that emitted it, outermost include first, and the sorted list
of model IRIs behind it. The sidecar is produced by rendering the same view model a
second time through a tracing template environment that appends a sentinel to every
text-emitting template line; stripping the sentinels must give exactly the normal
output, or the generator refuses to write anything. The output itself does not change by
a byte, which is why the goldens and the freshness tests were untouched when tracing
arrived. The sidecar is an output like any other, recorded in the lock with its own hash,
so a hand-edited trace is caught the same way as a hand-edited template. And the lock's
`sources` for a traced output are no longer computed separately by each generator: they
are the union of the trace's terms, because two computations of one fact can drift and
the trace is what rendering actually used.

The decision record is candid about what line-level tracing does not know. About a fifth
of the template expressions compute something in the template, a filter or a
concatenation, and drop the origin of the value they used, so a line can name the
elements behind it but not which literal produced which span. Value-level traces wait
for those expressions to move into the extract step. Line level matches the granularity
of the golden markers the project already had, and it was enough to build the next two
tiers on.

### Three tiers, and what stays out

The research note proposes bidirectionality in tiers, and the tiers are the structure of
this lesson. The first is **navigation**, free once traces exist: the viewer's generation
view joins model, template and output line by line, so selecting an output line shows its
template line and its elements, and selecting an element shows every line it reaches in
every file. The second is **write-back of a single literal**: a span whose origin is one
literal can be edited in place and becomes a one-triple patch. The third is **proposing a
structural edit**: an edit no single literal produces becomes a proposed model patch,
accepted only if regeneration reproduces it. The note's benchmark found that this works
for small edits and fails for reorganisations, so the project started it deliberately
narrow.

Just as important is what the note keeps out. Hand-written code lives outside generated
files, behind a stub, so it never needs round-tripping; lesson 9 was about that. BPMN and
DMN are already bidirectional, because the native XML is the source and a modeler edits
it directly. And there is no general bidirectional transformation language, because its
cost is a second way of writing every generator and the three tiers cover the edits a
domain expert actually makes. That refusal is the lesson-4 test applied to the project's
own ambitions: the general problem is hard, the literature says so, and a narrow answer
that is right beats a general one that is almost right.

### Tier two: one literal, or a refusal

The write-back rules in the viewer guide are worth reading as a specification of honesty.
In edit mode, the generation view's output pane has a one-line editor for the selected
line. Change the text and ask for a preview. The viewer takes the changed span, between
the line's unchanged start and end, looks at the model terms the line's trace cites and
their literal values, and keeps the ones that were written on the old line over that
span. Exactly one must remain. On the chat app, changing the page title in the generated
page to "Chat room" finds the one `ifml:title` literal and drafts a patch replacing that
triple, with its language tag and its named graph intact. When no literal covers the
span, or more than one does, the edit is refused and the refusal lists the candidates. The
Send Message button's line is covered by three literals, so it is refused with three
names. Only literals write back: a label, a title, a path. An edit to fixed template text
is refused too.

Then the edit must regenerate to itself. The patch is applied to a temporary copy of the
model, the project's generators run on it, and the output you edited must come back
equal to what you typed, model-hash lines aside. If it does not, the first differing
line is named and nothing is written. A raw ampersand typed into a page title is refused
this way, because the template escapes it. This is the golden test reused as a round-trip
check, and the trace note points out that it is the property one bidirectional-transformation
system, FuseDM, guaranteed by construction; here it is guaranteed by running the
generator.

Before anything is applied, the viewer shows the effects: the triple, the files it
touches, and every other output line the same patch changes, as before-and-after pairs,
because a literal often has reach beyond the line you edited. Renaming a list in the chat
app also changes a line in another partial. Apply runs the whole check again against the
model as it is now, so a preview left open across other edits cannot write a stale patch,
and then the patch goes through the one write path, which the next section is about. The
model changes; the outputs do not until you regenerate, and the lock says so in the
meantime.

### Tier three, narrowly

The structural tier starts with one case: adding or removing a form input. Open the whole
output in the editor, add or remove one input, and preview. The viewer diffs your text
against the output by line, requires the change to be one contiguous block with exactly
one named input appearing or disappearing, finds the form through the trace by the nearest
traced lines above and below the block, and drafts the patch: for a removal, every triple
of the parameter and the form's `ifml:hasParameter` to it, each in its own graph; for an
addition, a new parameter bound to the field. The same acceptance rule applies: regenerate
with the patch, and the result must be what you typed. Everything beyond that case is
refused with a reason, and the backlog records the next tiers as proposals, sentence
editing for the rest of the model and the storm board as a capture tool.

### The one write path

Every patch, from the write-back, the forms, the modelers and the copilot, goes through
[ADR-0017](../../docs/adr/0017-write-path-and-editor.md), and the decision is driven by a
fact the examples made plain: the chat app had 61 comment lines in 434, and chapter 8 of
the tutorial had 173 in 799. Serialising a graph with rdflib keeps every triple and
loses every comment, and reorders the rest, so a one-triple edit would produce a diff
nobody could review. The write path therefore edits the TriG text at the triple level and
never re-serialises. A removed quad deletes the text of that one triple; an added quad
joins its subject's statement as one more line, written with the file's own prefixes.
Within a patch the changes apply in sorted order, so the same source and the same patch
give the same bytes. An empty patch returns the original bytes. After writing, the
writer re-parses the text and checks that the dataset equals the old one with the patch
applied, graph by graph, and raises rather than save a file that means something other
than the patch.

Three consequences follow. Undo is a record of the spans a patch changed, so a patch and
its undo give the original bytes back. The write path lives in its own package, because
the read-only library must stay read-only. And editing is a mode of the viewer that is
off by default, so a reader who only browses keeps the guarantee that nothing they do can
change a file.

### A copilot that proposes patches

The last piece applies the same discipline to a language model.
[ADR-0028](../../docs/adr/0028-copilot-suggestions.md) notes that a model change is
riskier than a handler draft: it touches the seams graph and the native payloads that
every generator reads, and a language model writing those bytes directly could break
identity, break the partitioning, or scramble a modeler's layout, with output that is not
repeatable. So the model never writes a byte. `seams suggest` sends a versioned prompt,
with every piece of model text in a block the prompt declares to be data, to the same
provider command `seams propose` uses, and the answer must be one JSON object of a named
kind. The first kind moves an inline gateway condition into a DMN decision. Deterministic
code turns the suggestion into a patch and new payload text, editing the XML the way the
modelers do; the project is copied to a scratch directory; the copy must pass the shapes,
the decision checks and generation; and a passing suggestion is stored as pending, with
one unified diff per file, and nothing else happens. A person lists it, reads the diff, and
accepts it, and acceptance re-checks the suggestion against the current model hash and
refuses a stale one. Continuous integration never calls a provider.

### What is closed, and what is not

Put against lesson 4's test for F2, change one line of generated output and ask what
should change in the model, the answer is now specific. For a literal, the viewer says
which triple, proves it by regenerating, shows the other lines it touches, and writes it
through a path that keeps your comments. For one kind of structural edit, the same. For
everything else, a refusal with the reason, which is the honest half of the answer: the
project does not accept a fork and call it a round trip. The scorecard marks the row
closed for literals and form inputs and names the backlog items for the rest. The lab is
the only one in the course that uses the chat app rather than the expense model, because
the chat app's generated page is where the viewer's own examples live.

## Read in the repo

- [ADR-0019](../../docs/adr/0019-generation-trace.md) and
  [ADR-0017](../../docs/adr/0017-write-path-and-editor.md).
- [Using the viewer](../../docs/guide/the-viewer.md#write-back-from-output), the
  write-back section, including the rules for refusal.
- [Generation trace research note](../../docs/research/2026-10-31-generation-trace.md),
  section 5.3, "Bidirectional, in tiers".

## Lab: break the round trip, then honour it

1. **Break it.** Hand-edit the chat app's generated page title and run `seams check`. It
   reports `hand-edited`. Restore with `git checkout`.
2. **Navigate.** Start the viewer in edit mode on the chat app:

   ```sh
   SEAMS_EDIT=1 python3 -m uvicorn viewer.app:app --port 8000
   ```

   Open the generation view for `chat_page.html` and click the `<title>` line. Read the
   template line and the model terms it cites.
3. **Write back.** Change `Chat` to `Chat room` in the line editor and press **Preview
   write-back**. Read the patch and the other output lines it changes. Apply it, then run
   `seams generate` and `git diff`. One triple changed in the TriG, and the comment above it
   survived.
4. **Be refused.** Edit the *Send Message* button's line the same way. The refusal names the
   three literals that cover the span. Then type a raw `&` into a title and watch the
   regeneration check refuse it.
5. **Structural.** Use **Edit output** to remove the message input from the compose form and
   preview the structural edit. Read the patch before you apply it.
6. **Copilot, optional.** With a provider command, run `seams suggest` on your chapter 5
   file, where a gateway condition keeps a rule in the BPMN, list the pending suggestion and
   read the patch it proposes before accepting or discarding it.

## Scorecard

- **F2, closed for literals and form inputs.** An edit to an output line becomes a model
  patch, proved by regeneration, through the one write path. Edits the trace cannot
  attribute to one fact are refused with the reason, which is the honest half of the answer.
  Backlog V2 (sentence editing) and V4 (the storm board) propose the next tiers.
- **F6, closed.** The trace is what makes every generated line explainable.

## Further reading

- Perdita Stevens, "Bidirectional model transformations in QVT: semantic issues and open
  questions", *Software and Systems Modeling*, 2010, on why the general problem is hard.
- Markus Völter and colleagues, *mbeddr* and the projectional editing literature, on
  editing a projection and storing the model.
- The project's [data-centric model and copilot note](../../docs/research/2026-10-31-data-centric-model-and-copilot.md),
  on starting a copilot with deterministic checks.

# Lesson 10 · Getting changes back into the model

*The generation trace, the lock, write-back from an output line, and a copilot that
proposes model patches. The project's answer to the second failure, in tiers.*

::: info Module C draft
This lesson's outcomes, readings, lab and scorecard are final. The story section is a
summary; the full text is written in the module C pull request.
:::

## Outcomes

After this lesson you can:

- Explain the three tiers of bidirectionality the project chose, navigate, write back a
  literal, propose a structural change, and why it refused a general bidirectional
  transformation language.
- Trace an output line to its facts in the viewer's generation view and send an edit back
  as a one-triple patch that is accepted only when regeneration reproduces it.
- Describe the one write path, why it edits TriG text in place, and how a copilot's
  suggestion waits for a person.

## The story, in brief

Round-trip engineering failed, lesson 3 said, because it tried to recover a model from code
that had lost the model's intent. The project's generation-trace research note draws the
opposite conclusion from the same history: do not reverse-engineer, record. Every output
line gets a trace entry naming the template line and the model terms behind it
([ADR-0019](../../docs/adr/0019-generation-trace.md)), the lock records each output's hash
and sources, and `seams check` detects a hand edit by bytes. That is tier one, navigation:
the viewer's generation view joins model, template and output line by line.

Tier two is write-back of a literal. In edit mode, change an output line and the viewer
finds the one literal the line's trace cites that covers the changed span, drafts a patch
replacing that triple, applies it to a temporary copy, reruns the project's generators, and
accepts only if the output comes back equal to what you typed. If no single literal covers
the edit, it refuses and lists the candidates. Tier three is structural and narrow by
design: adding or removing one form input becomes an `ifml:Parameter` patch on the same
rule. Everything goes through the one write path of
[ADR-0017](../../docs/adr/0017-write-path-and-editor.md): a patch of quads, applied by
editing the TriG text in place so comments and layout survive, with undo. The copilot of
[ADR-0028](../../docs/adr/0028-copilot-suggestions.md), `seams suggest`, is the same
discipline applied to a language model: it proposes one JSON change, deterministic code
builds the patch, the patch is checked in a scratch copy, and nothing happens until a person
runs `--accept`.

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

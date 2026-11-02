# ADR-0019: Generation Trace — A Line-Level `<output>.trace.json` Sidecar Beside Each Generated File

**Status:** Accepted

**Date:** 2026-11-02

**Source:** milestone M020/S01; backlog T1; research note
[Tracing generation, and running it backwards](../research/2026-10-31-generation-trace.md)
section 5.1; builds on [ADR-0016](./0016-generator-protocol.md) and the A2 lockfile
(`seams.lock`)

## Context

Generated files carry comments naming the facts they came from, and the goldens in
`docs/generation/golden/` mark every line with the model terms it *should* cite. Nothing
machine-readable says what the generator *did* cite. The research note's prototype
showed that line-level tracing is cheap: rendering each template with a sentinel
appended to every text-emitting line traced every non-blank line of the chat page to
the template line that wrote it, with no change to the output.

`seams.lock` (A2) already records, per output, a `sources` list of model element IRIs,
but each generator computes it separately from rendering (`Generator.sources`), so it
can drift from what the templates actually emit. Backlog T1 asks for traces that the
generation view (T3) and write-back (T4) can read, with A2's provenance derived from
them.

The research note left two questions open: where traces live (a sidecar per output, one
file per generator run, or the lockfile itself) and their granularity (line or value).
Value-level traces need the 43 lossy template expressions moved into `extract` first
(T2, not done). This ADR settles both.

## Decision

### Storage: one sidecar per output

Each generated file `<output>` gets a sidecar **`<output>.trace.json` beside it**, in the
same directory. `seams generate` writes it after the output, from the generator's
`trace` hook (below). The output itself is unchanged, byte for byte, so the goldens and
the freshness tests are unaffected.

The sidecar is recorded in `seams.lock` as an **output of the same generator**, with its
own `sha256`, the generator's version and the same `sources` as the file it traces. The
existing lock audit therefore covers it: a hand-edited sidecar is reported, a missing one
is regenerated, and an orphan sidecar is deleted with its output. `seams check` flags
them as it flags any other output.

### Format

Sorted-key JSON, two-space indented, ending in a newline, with no timestamps and no
absolute paths:

```json
{
  "generator": "htmx",
  "lines": [
    {
      "line": 1,
      "templates": ["htmx_page.html.j2:1"],
      "terms": ["https://example.org/chat#chat_page"]
    },
    {
      "line": 17,
      "templates": ["htmx_page.html.j2:12", "htmx_component.html.j2:5"],
      "terms": ["https://example.org/chat#conversation_list"]
    }
  ],
  "output": "chat_page.html",
  "trace_version": 1
}
```

- `trace_version` is `1`.
- `output` is the file name the generator returned it under: a posix path relative to
  the generator's output directory, the key of `render(view)`.
- `generator` is the generator's entry-point name (ADR-0016).
- `lines` holds one entry per **non-blank** output line, in line order; blank and
  whitespace-only lines are omitted. `line` is 1-based.
- `templates` lists the template origins of that line as `<template file>:<line>`,
  **outermost include first**: the line of the including template, then the line of the
  included one, down to the template line whose text was emitted. Every listed line has
  at least one origin.
- `terms` is the sorted, de-duplicated list of full model IRIs behind the line (below).
  It may be empty for a line of fixed text.

### Template origins: a sentinel render

The trace is produced by a second render of the same view model with a tracing Jinja2
environment. Its loader appends a unique sentinel naming the file and line to each
template line that emits text (block-only tag lines and comment lines get none), so the
sentinels in the rendered text say which template lines produced each output line.
Stripping the sentinels must give exactly the normal render; if it does not, or if a
sentinel string already occurs in the normal output, tracing raises `GeneratorError`
naming the template and line, and nothing is written. Templates are not edited for
tracing.

### Model terms: origin-carrying values, else the enclosing view object

A view model value that carries an `iri` (the view objects' `iri` fields) is emitted
through the tracing environment's `finalize`, which adds a term sentinel for that IRI;
the terms of a line are the IRIs whose sentinels land on it. A line with no such value
falls back to the IRIs of the enclosing view object passed to the template that emitted
it. This is line-level evidence; value-level spans wait for T2.

### Lock sources from traces

For a generator with a `trace` hook, an output's lock `sources` are the **sorted union
of its trace's terms**, replacing that generator's `sources` function for that output.
Generators without a `trace` hook keep `Generator.sources` and write no sidecar.

### The protocol hook

`seams_gen.protocol.Generator` gains an optional field
`trace: Callable[[V], dict[str, Trace]] | None = None`: from the view model, a `Trace`
per file name, with exactly the file names `render` returns. The built-in htmx, FastAPI
and compose generators provide it. A third-party generator may leave it `None`.

## Alternatives Considered

- **Traces inside `seams.lock`.** Rejected: one entry per output line makes the lock
  large and churns it on every template change, and the viewer would have to parse the
  whole lock to show one file.
- **One trace file per generator run.** Rejected: it does not map to the lock's per-file
  entries, and a viewer showing one output would load every file's trace.
- **Traces embedded in the output as comments.** Rejected: it changes the output bytes,
  so every golden and freshness test would change, and not every format has comments.
- **Value-level spans now.** Deferred: about a fifth of template expressions compute in
  the template and drop the origin. Line level matches the golden markers' granularity
  and needs no template refactor. Value-level spans can be added after T2 without
  changing where traces live.
- **Keeping `Generator.sources` as the lock's provenance.** Rejected for traced
  generators: two computations of the same fact can drift; the trace is what rendering
  actually used.

## Consequences

- `seams_gen/trace.py` holds `Trace` and `TraceLine` and renders the JSON;
  `seams_gen/protocol.py` gains the `trace` hook, wired for the built-ins in
  `seams_gen/builtin.py` (M020/S01/T02).
- `seams generate` writes the sidecars, lists them in `seams.lock` and derives the lock
  `sources` from them; the committed outputs of the chat app and the expense examples
  gain sidecars and their locks change once (T03).
- A test compares the traces with the golden markers: each `[graph: ...]` term must be
  in the line's trace terms or its enclosing view object's, and each `[fixed]` line must
  have a template origin (T04).
- The generation view (T3) and write-back (T4) read the sidecars.
- If a formatter ever runs over generated code, traces need remapping or the formatter
  runs before tracing. Today none runs.

## Implementation Notes

- T02: `seams_gen/trace.py`, the tracing environment in `seams_gen/htmx.py`, the
  protocol hook and `tests/test_generation_trace.py` (byte equality, origins on every
  non-blank line, determinism, sentinel collision and mismatch).
- T03: sidecars and trace-derived sources in `packages/seams-cli/src/seams_cli/generate.py`;
  regenerated examples.
- T04: the golden-marker comparison and the backlog status. To make the traces name what
  the goldens cite, a view object's IRIs are its `iri` plus an optional sorted `origins`
  tuple: the further model elements its extraction read (`seams_gen.trace.view_iris`).
  A value read off it carries all of them, and a fallback takes all of them. Because a
  line-level trace records no loop scope, the test takes a line's enclosing view object's
  terms to be those of the include it is in. One cited element the generator does not
  read, `:select_to_thread` on `chat_api.py` line 31, is a known gap (backlog T1).
- M021/S01: the traces drive write-back (backlog T4). `viewer/writeback.py` reads an
  edited output line's trace terms to find the one model literal written over the
  changed span, and accepts the one-triple patch only when regenerating with it gives
  back the edited output ([guide](../guide/the-viewer.md#write-back-from-output)).

## Revision notes

- 2026-11-02 (backlog T5, M021/S02): structural edit proposals also read the traces.
  `viewer/structural.py` finds the form around an added or removed input from the trace
  terms of the nearest traced lines above and below the edited block, because an input
  line traces only the form's written shape, not its `ifml:Parameter`. The drafted
  patch is accepted only when regenerating with it reproduces the edited block; lines it
  changes elsewhere are shown as effects first
  ([guide](../guide/the-viewer.md#structural-edits-adding-or-removing-a-form-input)).

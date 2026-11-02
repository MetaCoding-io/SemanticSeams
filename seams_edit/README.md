# seams_edit

The model's one write path ([ADR-0017](../docs/adr/0017-write-path-and-editor.md),
[principle 10](../docs/project/principles.md#_10-the-model-is-editable-through-one-write-path)).
Every edit to a model is a patch, the quads it adds and the quads it removes, and this
package is the only code that writes it into a model file. The `seams` library stays
read-only; the viewer, the CLI and any later tool that edits the model call
`seams_edit`.

## Boundary

- Owns the patch value, the TriG text writer, file apply and undo, and the XML payload
  writer for BPMN and DMN (backlog I4): saving a payload and renaming an element id.
- Writes model files only through the writer below; nothing else in the repository
  writes them.
- Depends on `semanticseams`, rdflib and lxml, and imports only public `seams` names.
  It is a virtual workspace member (D033): installed by `uv sync --all-packages`,
  resolved from the repository root. Checked with strict pyright, like `seams`.

## How the writer edits TriG

The writer never re-serialises the graph, which would drop every comment and reorder
the file. It reads the source text far enough to know where each triple is written
(prefixes, graph blocks, statements, `;` and `,` lists, `a`, `[ ]` blank nodes,
collections, long and multi-line literals, comments) and edits only that text:

- **Removing** a quad deletes its text: the whole line when the pair is alone on it, one
  object of an object list (`p o1 , o2`), the first pair (the subject stays) or the last
  pair (the final `.` moves up). Removing a statement's last triple removes the
  statement; the comments above it stay. A `[ ]` or `( )` object goes with its pair, so
  the patch must remove the triples inside it too.
- **Adding** a quad joins its subject's statement in that graph as a new
  `predicate object ;` line before the last pair, or inline as `; predicate object`
  when the statement is on one line. A new subject becomes a statement just before its
  graph's closing `}`; a new graph becomes a block at the end of the file. New text is
  laid out canonically: sorted, one pair per line. Terms use the file's prefixes,
  numbers and booleans their bare form, and an IRI under the file's folder is written
  relative, so no host path reaches the file.
- A patch applies in sorted (graph, subject, predicate, object) order: the same text
  and the same patch give the same bytes.
- After editing, the writer re-parses the result and checks, per named graph by
  isomorphism, that it is the old model with the patch applied. A mismatch is a writer
  bug: it raises rather than return text that means something else.

## API

```python
from seams_edit import Patch, PatchError, apply_text, declared_graphs, text_quads

patch = Patch(adds=[(s, p, o, g)], removes=[(s, p, old, g)])
new_text = apply_text(text, patch, base=path.as_uri())
undo_text = apply_text(new_text, patch.inverse(), base=path.as_uri())
```

- `Patch(adds=(), removes=())`: a frozen value; quads are `(subject, predicate, object,
  graph)`, deduplicated and sorted. `inverse()` swaps adds and removes; `is_empty` is
  true when both are empty. A quad both added and removed raises `PatchError`.
- `apply_text(text, patch, *, base=...)`: the edited text. An empty patch returns
  `text` itself. Pure: it reads and writes no files. `base` is the file's URI, so
  relative IRIs mean what they mean to `seams.load`; the default is a fixed `file:///`.
- `text_quads(text, *, base=...)`: the quads the text states, sorted. Blank nodes
  written as `[ ]` or `( )` have no names in the text, so the writer labels them in
  document order under a hash of the text; a patch that names an existing blank node
  takes it from here. A blank node the text does not have is written inline as `[ ]`
  under the added quad that has it as its object.
- `declared_graphs(text, *, base=...)`: the graphs the text has a `{ }` block for.

Because labels are scoped to one version of the text, applying `patch.inverse()` to the
edited text refuses an inverse that names an existing `[ ]` node by its old label (an
edit inside a blank node). It fails loudly rather than attach triples to the wrong node.
Undo restores the changed spans directly, so it does not need the inverse.

## Applying to files, and undo

```python
import seams
from seams_edit import apply, undo

record = apply(seams.load("examples/chat-app").files, patch)  # or explicit TriG paths
redo = undo(record)
```

- `apply(paths, patch)`: reads every TriG file named, and sends each quad to the one
  file that declares its graph (`GRAPH g { }` or `g { }`). A default-graph quad being
  removed goes to the one file that states it; an added quad whose graph no file
  declares goes to the only file of a one-file model. Each file's share goes through
  `apply_text` with the file's URI as base, as `seams.load` reads it. Only when every
  file has succeeded are they written, each through a temporary file and a rename; if
  writing one fails, the files already written get their old bytes back. An empty
  patch writes nothing.
- `EditRecord(patch, files)`: a frozen value. Each `FileEdit(path, patch, start,
  before, after)` is one file's share of the patch and the one byte span it changed:
  at `start`, `before` became `after`.
- `undo(record)`: when every file still holds `after` at its span, puts `before` back,
  keeping the rest of the file as it is now (so a later hand edit after the span
  stays). Otherwise, after a hand edit inside or before a span, applies each file's
  share of `patch.inverse()` to that file through the writer, and raises if the file
  no longer holds what the patch added. It returns the record of the undo, so undoing
  that redoes the edit.

The record is the session's history: it lives in memory, and nothing about an edit is
written anywhere but the model files. The inverse fallback has the writer's blank node
limit (above): it cannot remove a `[ ]` node the patch added, since its label changed
with the text.

## BPMN and DMN payloads

```python
from seams_edit import rename_id, save_payload, undo

model = seams.load("examples/chat-app")
record = save_payload(model.files, model.payload_path(process), new_xml)
record = rename_id(model.files, model.payload_path(process), process, "old_id", "new_id")
undo(record)
```

The payload and the model IRI come from the loaded model: the payload must be a file
that one of `model_files` names by `seam:renderPayload`, and for a rename the model IRI
must be the model that renders it.

- `save_payload(model_files, payload_path, new_xml)`: parses `new_xml` (text or bytes)
  with lxml, entities unexpanded and no network, then writes it exactly as given, so a
  modeler's layout is its own. The same bytes write nothing. The record holds one
  payload edit: the span that changed.
- `rename_id(model_files, payload_path, model_iri, old, new)`: an element id rename
  under ADR-0002's atomic update (rule 5). In the payload it rewrites, at the byte
  level, the element's `id="old"` and every reference to it: `...Ref` attributes other
  than `typeRef` (sourceRef, targetRef, attachedToRef, dmnElementRef and the rest),
  `bpmnElement`, `default`, `calledElement`, `sourceElement`, `targetElement`, DMN's
  `href="#old"`, and the text of `incoming`, `outgoing` and `...Ref`/`...Refs`
  elements. Comments, CDATA and every other byte stay as they were. It checks that the
  edited text parses to the old payload with the same rename made in the tree (by
  canonical XML), and raises otherwise. In the model it builds a patch that replaces
  every quad with `<model_iri#old>` as subject or object by the same quad with
  `<model_iri#new>`; a `[ ]` object of the old IRI moves with all its triples. A
  decision `seam:inModel` the model whose `dec:payloadElement` is `old` gets `new`, so a
  DMN decision rename keeps its binding. The payload and every model file the patch
  touches are written together, or none of them.
- Records: a payload's `FileEdit` has `payload=True` and an empty share of the patch.
  `undo` puts its span back with the model files' spans. A payload has no patch to
  invert, so when it no longer holds its after bytes undo raises `PatchError` and
  writes nothing; when only a model file changed, the model files take the inverse
  patch through the writer and the payload gets its span back.

The renamed subject's statement is removed and added through the TriG writer, so it
moves to the end of its graph block, laid out canonically; comments stay where they were.

## Errors

`PatchError(subject, predicate, detail)` names the quad and the reason, and the writer
returns nothing:

- a removed quad the text does not state, or an added quad it already states;
- a `[ ]` or `( )` object removed without the triples inside it, one cell of a
  collection, an addition to a collection cell;
- a new blank node that no added quad has as its object, or a second reference to an
  unlabelled blank node of the text;
- an invalid IRI, or text the writer cannot read (the detail names the line);
- an edit that does not re-parse to the patched model;
- from `apply` and `undo`: a graph declared in more than one model file, an added quad
  whose graph no file declares in a model of several files, a removed quad no file (or
  more than one) states, a model file that is not UTF-8. Nothing is written.
- from `save_payload` and `rename_id`: XML that is not well-formed (the detail names the
  line), a payload no model file names, a model IRI that does not render the payload,
  an `old` id the payload lacks, a `new` id it already has or that is not an XML name,
  an edit that does not parse to the renamed payload; from `undo`, a payload changed
  after the edit. Nothing is written.

These are writer faults, not shape faults. An edit that only breaks the shapes is
applied and flagged (principle 5).

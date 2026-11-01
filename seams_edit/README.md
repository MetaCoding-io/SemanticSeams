# seams_edit

The model's one write path ([ADR-0017](../docs/adr/0017-write-path-and-editor.md),
[principle 10](../docs/project/principles.md#_10-the-model-is-editable-through-one-write-path)).
Every edit to a model is a patch, the quads it adds and the quads it removes, and this
package is the only code that writes it into a model file. The `seams` library stays
read-only; the viewer, the CLI and any later tool that edits the model call
`seams_edit`.

## Boundary

- Owns the patch value, the TriG text writer and (M019/S02) file apply and undo. The XML
  payload writer for BPMN and DMN comes with backlog I4.
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

## Errors

`PatchError(subject, predicate, detail)` names the quad and the reason, and the writer
returns nothing:

- a removed quad the text does not state, or an added quad it already states;
- a `[ ]` or `( )` object removed without the triples inside it, one cell of a
  collection, an addition to a collection cell;
- a new blank node that no added quad has as its object, or a second reference to an
  unlabelled blank node of the text;
- an invalid IRI, or text the writer cannot read (the detail names the line);
- an edit that does not re-parse to the patched model.

These are writer faults, not shape faults. An edit that only breaks the shapes is
applied and flagged (principle 5).

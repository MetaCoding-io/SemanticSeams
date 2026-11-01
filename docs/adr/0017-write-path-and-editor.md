# ADR-0017: Write Path and Editor — Patches Edit the TriG Text in Place, in `seams_edit`, Behind a Viewer Edit Mode

**Status:** Accepted

**Date:** 2026-11-01

**Source:** milestone M019/S01; backlog I1 and P2 item 13; principle 10; research note
[Projection and editing](../research/2026-10-30-domain-ide-and-generator-kit.md)
section 4

## Context

[Principle 10](../project/principles.md#_10-the-model-is-editable-through-one-write-path)
makes the model editable from the start: in the viewer, through forms built from the
shapes or the BPMN and DMN modelers, or in a text editor, with both routes leaving the
same files. Every edit is a patch (quads added and removed, or an XML change for BPMN and
DMN) through one write path that supports undo, and no other code writes model files.
The principle leaves three questions to this ADR, and the research note lists them as
open:

1. **Comments.** The examples rely on hand-written comments: the chat app has 61 comment
   lines in 434, and the expense tutorial's chapter 8 has 173 in 799. rdflib drops
   comments and reorders triples when it serialises, yet a one-triple edit must give a
   one-line diff (principle 6) and the comments must survive.
2. **Where the write path lives.** `packages/seams` is read-only: its package-boundary
   row says it must not write, and it depends only on rdflib and lxml.
3. **Where the editor lives.** A mode of the viewer, which already has the renderers, the
   routes and the health badge, or a separate app. The viewer's read-only guarantee is a
   feature for people who only browse.

The spike `tests/test_adr0017_spike.py` (M019/S01/T01) is the evidence for the first
answer. A minimal quad-patch text writer, written only in the test, shows that:

- an empty patch returns the original bytes for every `examples/**/*.trig` outside the
  generated directories (11 files);
- removing one triple from the chat app, or adding one, changes exactly one line under
  `difflib`, and the edited text re-parses to the expected dataset, compared per named
  graph by isomorphism;
- every comment line survives such an edit, in order;
- re-serialising the chat app or chapter 8 with rdflib keeps the graph but leaves zero
  comment lines.

## Decision

### Comments: a patch-based text writer over the source TriG

The write path applies a patch by **editing the source TriG text at the triple level**,
never by re-serialising the graph. Text the patch does not touch, comments and layout
included, is kept byte for byte. So:

- An empty patch writes the original bytes, which is the round-trip check principle 10
  names. A patch followed by its undo also gives the original bytes (see Undo below).
- A removed quad deletes only the text of that one triple. When it sits alone on a
  `predicate object ;` line, as in the spike, that is one line. The real writer also
  handles what the spike leaves out: the first or last pair of a statement (moving the
  subject or the final `.`), one object of an object list (`p o1, o2`), the `a`
  shorthand, blank-node objects (`[ ... ]`) and multi-line literals. Removing the last
  triple of a statement removes the statement; comment lines above it stay.
- An added quad joins its subject's existing statement in its named graph when there is
  one, as a new `predicate object ;` line after the last pair. Otherwise it becomes a new
  statement line just before its graph's closing `}`, as in the spike. Terms are written
  with the file's own prefixes, and numbers and booleans in their bare form, as authors
  write them.
- Within one patch, removals and additions are applied in sorted (graph, subject,
  predicate, object) order, so the same source text and the same patch give the same
  bytes (principle 6).
- Text the writer creates from nothing, such as a new named-graph block or a new file, is
  laid out canonically: prefixes, graphs and subjects sorted, one `predicate object`
  pair per line. That keeps the next edit to it line-local too.
- A quad the writer cannot place in the text raises an error naming the quad and the
  reason, as `PatchError(subject, predicate, detail)` does in the spike, and the writer
  writes nothing: a removed quad that is not in the model, an added quad that already is,
  or a graph declared in more than one file of a multi-file model. These are writer
  faults, not shape faults. An edit that only breaks the shapes is still saved and
  flagged (principle 5).

After writing, the writer re-parses the edited text and checks that the dataset equals
the old one with the patch applied, per named graph by isomorphism. A mismatch is a bug
in the writer, so it raises and writes nothing rather than save a file that means
something other than the patch.

### Where the write path lives: a new `seams_edit` package outside `packages/seams`

The write path is a new workspace member, **`seams_edit`**, at the repository root
beside `seams_gen` and `seams_runtime`. It is virtual like them (D033): its
`pyproject.toml` declares its dependencies (`semanticseams` and rdflib, plus lxml for
the XML edits of I4), and the package resolves from the repository root. It reads the
model only through the public names of `seams` (`seams.load` and the views) and never
imports a `seams` private name.

It owns:

- the **patch**: a frozen value holding the sorted quads it adds and the sorted quads it
  removes, with its inverse (adds and removes swapped);
- the **TriG text writer** described above, the only code that writes a TriG model file;
- the **XML payload writer** for BPMN and DMN files, which I4 (M019/S04) designs,
  including the ID rename that rewrites the seams graph in the same edit
  ([ADR-0002](./0002-iri-identity-and-migration.md));
- **undo**, below.

`packages/seams` stays read-only, depends on rdflib and lxml only, and gains no write
code; its README and its package-boundary row are unchanged. The viewer, the CLI and any
later tool that edits the model call `seams_edit`, which the package-boundary table
records as the one write path.

### Undo

Applying a patch returns a record of the text it changed in each file: the file, the
byte span and the text before and after. Undoing restores the old text of those spans
when the file still holds the new text there, so a patch followed by its undo gives the
original bytes. When the file has changed since (a later edit, or a hand edit in a text
editor), undo applies the inverse patch through the writer instead, which restores the
graph but may place the restored lines differently. The undo history is per editing
session and is not stored in the model; git keeps the history across sessions.

### Where the editor lives: an edit mode of the viewer, off by default

Editing is a **mode of the viewer**, not a separate app:

- The renderers, routes, navigation and health badge it needs are already in the viewer,
  and every layer of the edit work (I2 forms, I3 preview, I4 modelers, I6 IFML diagram)
  draws on a view the viewer already shows. A second app would copy them or import the
  viewer's private names.
- The package-boundary table already gives the viewer "rendering, navigation and
  editing", and principle 10 names the viewer as where a person changes the model.

The read-only guarantee stays the default. The viewer starts read-only; edit mode is
switched on explicitly when it starts (an environment variable beside `SEAMS_MODEL`,
named by M019/S03). Without it, no route that writes is mounted, so a browsing user
cannot change a file, and the modelers stay viewers. With it, every write goes through
`seams_edit`; the viewer itself never opens a model file for writing.

## Alternatives Considered

- **Move explanations into `rdfs:comment` triples and re-serialise.** Rejected: the
  comments in the examples explain the file to its reader (sections, rationale,
  cross-references to ADRs), not facts about one element, and turning them into triples
  would put text in the model that no shape or generator uses. It would also still need
  a serialiser that keeps the author's order and layout, which is the problem this ADR
  solves. Authors can still write `rdfs:comment` where the viewer should show the text.
- **A canonical, sorted serialisation for files the IDE writes.** Rejected for existing
  files: the spike shows rdflib keeps none of the examples' comment lines, and the first
  save would reorder every hand-written file into one large diff. The canonical layout is
  kept only for text the writer creates from nothing.
- **Write path inside `packages/seams`.** Rejected: the library's package boundary is
  read-only, and principle 10 says its views stay read-only. Putting writes there would
  break both.
- **A separate editor app.** Rejected: it would duplicate the viewer's renderers and
  routes, or import its private names, for a read-only guarantee that an edit mode off
  by default already gives.
- **RDF Patch as the patch format.** Not chosen now: nothing yet exchanges patches
  between processes, and an in-memory value with sorted quads is enough for apply and
  undo. RDF Patch can serialise the same value later if collaboration or an audit log
  needs it.

## Consequences

- Hand-written TriG files keep their comments and layout through every edit, and a
  one-triple edit gives a one-line diff (at most two when it moves a statement's final
  `.`), so model changes stay reviewable in git.
- The writer is a text-level Turtle editor and must cover the TriG syntax the examples
  and users write. M019/S02 grows the spike's cases into a round-trip suite: an empty
  patch on every example, and removing and re-adding each triple of each example with an
  isomorphism check.
- `seams_edit` is a new workspace member, so `pyproject.toml`, `uv.lock` and the
  package-boundary table in the principles change with S02.
- The viewer's read-only mode is unchanged for anyone who does not switch editing on.
  The viewer guide documents edit mode when S03 adds it.

## Implementation Notes

- Spike: `tests/test_adr0017_spike.py`, a minimal patcher in the test only. Its known
  limits (first or last pair of a statement, object lists, blank nodes, multi-line
  literals) are the requirements listed above for the real writer.
- M019/S02 builds `seams_edit` (patch, TriG text writer, undo) and the round-trip tests.
  S03 adds the viewer edit mode and the shape-derived forms; S04 adds the XML payload
  writer and ID rename.
- This ADR's own test: `tests/test_adr0017_doc.py`.

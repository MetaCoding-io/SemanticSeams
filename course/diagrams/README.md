# Course diagrams

The figures the lessons embed with `<Diagram name="..." />`. Each is a light and dark
pair, `<name>.svg` and `<name>-dark.svg`, inlined by `course/.vitepress/theme/diagram.ts`
and switched by the site's dark-mode class.

| Name | Lesson | Type |
|---|---|---|
| `notations-timeline` | 1 | Timeline: the notations that had an engine, and the ones that did not |
| `descent` | 5 | Architecture: the expense app's descent through four notations, one seam predicate per arrow |
| `interpret-generate` | 7 | Layer stack: which layers an engine interprets and which are generated |
| `round-trip` | 10 | Architecture: generation, trace and lock, and the write-back of one literal |

They are drawn with the [diagram-design](https://github.com/cathrynlavery/diagram-design)
skill under its SemanticSeams profile (the project page's colours and IBM Plex; the
`.diagram-design` marker at the repository root names it). The sources are the HTML files
in `src/`, written by `build.py` from one geometry per diagram, so the light and dark
variants cannot drift. `export.sh` rebuilds the sources, runs the skill's self-check and
exports the SVGs; it needs the skill installed (`DIAGRAM_DESIGN_SKILL` overrides the
path). Do not edit the SVGs by hand: change `build.py` and run `export.sh`.

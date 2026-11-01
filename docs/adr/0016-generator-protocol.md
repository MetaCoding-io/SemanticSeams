# ADR-0016: Generator Protocol — Generators Are Objects Found Through One Entry-Point Group

**Status:** Accepted

**Date:** 2026-11-01

**Source:** milestone M018/S01; backlog K3; decision D056

## Context

Until M018 a generator was a pair in `GENERATORS` in `seams_gen/__main__.py`: a help
text and a `generate(trig, out)` function returning `{file name: text}`. The model
elements each file came from were a separate table, `SOURCES` in `seams_gen/sources.py`.
`seams generate` accepted only the names of that dict, and `seams.lock` recorded
`seams_gen.__version__` for every output.

That left three gaps:

- **No way in for a generator from somewhere else.** A team that wrote its own generator,
  as the [Write your own generator](../guide/write-your-own-generator.md) guide shows,
  could run it by hand but could not list it in `seams.toml`. Its outputs were not in
  `seams.lock`, so `seams check` could not report them as stale or hand-edited.
- **One version for all.** The lock's `generator_version` was the version of `seams_gen`,
  even for a file another package wrote.
- **No stated input contract.** A generator that needs, say, every `seam:Model` to have a
  notation found that out half-way through `extract` and raised `GeneratorError` on the
  first gap. The shapes already state most of these facts (K1, M017/S01), but nothing
  connected a generator to the shapes it relies on.

## Decision

### The protocol

A generator is a **`seams_gen.protocol.Generator`**: a frozen, keyword-only dataclass with

| Field | Type | Meaning |
|---|---|---|
| `name` | `str` | the name `seams.toml` and `python -m seams_gen` use; equal to the entry-point name |
| `version` | `str` | recorded per output in `seams.lock` as `generator_version` |
| `help` | `str` | one line, shown by `python -m seams_gen --help` |
| `extract` | `(trig: Path, out: Path) -> V` | reads the model into a frozen view model `V`. Every check and every computation is here; a missing or ambiguous fact raises `GeneratorError` |
| `render` | `(view: V) -> dict[str, str]` | the view model as `{relative file name: text}`; no model access |
| `sources` | `(trig: Path, out: Path) -> dict[str, tuple[str, ...]]` | `{relative file name: full IRIs}` of the model elements each file comes from, with exactly the file names `render` returns |
| `preconditions` | `tuple[str, ...]`, default `()` | full IRIs of the `sh:NodeShape`s the model must conform to before the generator runs |

`Generator.generate(trig, out)` is `render(extract(trig, out))`. The class is generic in
`V`, so a type checker sees that `render` takes what `extract` returns. `out` is passed
to `extract` for generators whose output names paths relative to it (`compose`).

The seven built-ins (`compose`, `dockerfile`, `fastapi`, `htmx`, `ifmledit`, `smoke`,
`tests`) are module-level objects in `seams_gen/builtin.py`, each split into a real
extract and render step over its existing `extract_*` and `render_*` functions. Their
version is `seams_gen.__version__`, their sources come from `seams_gen/sources.py`, and
they declare no preconditions. Every golden and committed output is byte-identical.

### Discovery: the `seams.generators` group

`seams_gen.registry.discover()` loads every entry point of the
**`seams.generators`** group (`importlib.metadata.entry_points`) and returns
`{name: Generator}` sorted by name. A distribution registers a generator with

```toml
[project.entry-points."seams.generators"]
checklist = "seams_checklist:generator"
```

`discover()` raises `seams_gen.registry.RegistryError`, a `GeneratorError`, when an entry
point does not load, loads an object that is not a `Generator`, loads a generator whose
`name` differs from the entry-point name, or repeats a name another entry point has
already registered. The message names the entry point (`name = value`) and its
distribution with version, so the user knows which package to fix or remove. Entry
points are visited in (name, value) order, so the same environment always reports the
same error.

`seams_gen.__main__.GENERATORS` and `seams_gen.sources.output_sources` are views of the
registry, so `python -m seams_gen <name>` runs a third-party generator too.
`seams.toml` accepts any discovered name; an unknown one is still a `ProjectError` that
lists the known names.

### Where the built-in entry points live (D056)

The built-ins' entry points are declared in `packages/seams-cli/pyproject.toml`
(`semanticseams-cli`), pointing at `seams_gen.builtin:<name>`. Entry points are
distribution metadata, and `seams_gen` is a virtual workspace member that installs no
metadata of its own (D033). `semanticseams-cli` is the one installed member that imports
`seams_gen`, so declaring them there gives built-in and third-party generators one
discovery path without moving any code (D031). When `seams_gen` becomes a real package,
the entry points move into its own `pyproject.toml`.

### The lock records each generator's version

`seams generate` carries each generator's `version` in its `Output`, and
`lockfile.build_lock` writes it as that output's `generator_version`. The lock schema
(`lockfile_version` 1) is unchanged, so existing `seams.lock` files regenerate with no
diff: the built-ins' version is still `seams_gen.__version__`.

### Strict precondition checking

Before any generator runs, `seams generate` checks the preconditions of every generator
in the project that declares some. It validates the model, unioned with
`ontology/*.ttl`, against `ontology/shapes` with pyshacl once, and passes the report to
each generator's `Generator.check_preconditions(results, shapes)`. A result counts when
its `sh:sourceShape` is a precondition node shape or one of that shape's `sh:property`
shapes (matched in the same parsed shapes graph, so blank-node property shapes match).

Any such result raises `GeneratorError` whose subject is the focus node and whose
predicate is the shape IRI; the message names the generator and the shape's
`sh:resultMessage`, plus a count of further results. Results are sorted by (shape, focus
node, message), so the error is deterministic. The CLI prints it and exits 2, and nothing
is written: no outputs and no `seams.lock`.

```text
seams generate: https://example.org/expenses/broken_model: https://w3id.org/seams/shapes#ModelShape: generator 'strict-gen' requires the model to conform to this shape: Every seam:Model has exactly one seam:notation, and it is a seam:Notation.
```

`seams_gen` does not depend on pyshacl: `seams_cli` runs the validation and hands the
report over, so the check sits in `seams_gen/protocol.py`, where the shape/generator
parity inventory (`tests/test_shape_generator_parity.py`) lists it as `GENERATOR_ONLY`
(the check *is* the shapes). Results of shapes that are not preconditions are ignored
here; `seams check` still reports them.

### Lenient mode is deferred

This ADR covers strict mode only. A lenient mode, which runs a generator on a model that
fails its preconditions and flags the output for previews (backlog K3, I3), is M018/S02.

## Alternatives Considered

- **Keep `GENERATORS` and add a `plugins` key to `seams.toml` naming import paths.**
  Rejected: built-ins and third-party generators would be found two ways, and a project
  file would hold Python import paths rather than names. Entry points are the standard
  way for an installed distribution to offer plugins.
- **Declare the built-in entry points in `seams_gen/pyproject.toml`.** Not possible while
  `seams_gen` is virtual (D033): a virtual member installs no `.dist-info`, so the entry
  points would never be visible.
- **A `Generator` protocol class (`typing.Protocol`) instead of a dataclass.** Rejected:
  `discover()` needs a runtime check that an entry point loads a generator, and a frozen
  dataclass gives that with `isinstance`, plus immutability and keyword-only construction.
- **Run pyshacl inside `seams_gen`.** Rejected: it would add pyshacl to `seams_gen`'s
  dependencies for a check only the CLI needs, and validate once per generator instead of
  once per run.
- **Record `seams_gen.__version__` for every output, as before.** Rejected: a third-party
  generator's output would carry a version unrelated to the code that wrote it.

## Consequences

- A generator from another distribution is listed in `seams.toml`, run by
  `seams generate`, recorded in `seams.lock` with its own version and audited by
  `seams check` like a built-in.
- Installing two distributions that register the same name, or a broken plugin, makes
  every `seams generate` and `python -m seams_gen` call fail with a message naming the
  entry point and distribution, rather than silently picking one.
- A generator can state the shapes it relies on and get a shape-level error before
  `extract` runs, instead of the first `GeneratorError` it meets.
- `seams generate` validates with pyshacl only when some generator in the project
  declares preconditions, so projects using only the built-ins pay nothing.

## Implementation Notes

- Protocol: `seams_gen/protocol.py`. Built-ins: `seams_gen/builtin.py`. Registry:
  `seams_gen/registry.py`. Entry points: `packages/seams-cli/pyproject.toml`; after
  changing them, run `uv sync --all-packages` so the editable metadata refreshes.
- CLI: `packages/seams-cli/src/seams_cli/project.py` (names),
  `generate.py` (preconditions, `Generator.generate`, `Generator.sources`),
  `lockfile.py` (per-output version).
- Tests: `tests/test_generator_protocol.py` (built-ins equal the old functions),
  `tests/test_generator_registry.py` (discovery and each `RegistryError`, with a fake
  `.dist-info` on `sys.path`), `tests/test_seams_cli_generate.py` and
  `tests/test_seams_cli_lockfile.py` (a third-party generator through `seams generate`,
  a failing precondition, its version in the lock).
- The guide: [Register it with seams generate](../guide/write-your-own-generator.md#register-it-with-seams-generate).

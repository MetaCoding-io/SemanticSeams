# semanticseams-cli

The `seams` command line: distribution name `semanticseams-cli`, import name
`seams_cli` (D042). It is a packaged uv workspace member because uv installs no
console scripts for virtual members (D033); `uv sync --all-packages` puts
`seams` in `.venv/bin`. It is not published to PyPI.

## The project file

Each app keeps a `seams.toml` next to its model. It names the model, the
generators with their output directories, and the app's environments:

```toml
model = "expenses.trig"

[[generators]]
name = "fastapi"
out = "generated"

[[generators]]
name = "htmx"
out = "generated/templates"

[environments.dev]
```

- `model` (string, optional): the TriG file to generate from.
- `generators` (array of tables): each entry has a `name`, one of the
  `python -m seams_gen` generators (`compose`, `fastapi`, `htmx`), and an `out`
  directory.
- `gates` (array of strings, optional): SPARQL SELECT files, relative to the
  project file, that `seams check` runs over the model; each must return no
  rows.
- `coverage` (array of strings, optional): `["paths"]` makes `seams check`
  report each BPMN path no scenario runs as a `coverage` finding (D054).
- `environments` (table of tables, optional): environment names. An
  environment may carry an `endpoints` inline table, container local name to
  base URL, for `seams status`; any other key is ignored.

Relative paths resolve against the directory of the project file, so the
command gives the same result from any working directory.

## seams generate

```sh
seams generate                         # the seams.toml in the working directory
seams generate --project examples/expenses/chapter-03
seams generate --project path/to/seams.toml --model other.trig
```

It runs every generator in memory and writes the files only when all of them
succeed, so a failing generator leaves every output untouched. Each written
path is printed, relative to the working directory when it lies below it.
Files are written as UTF-8 with `\n` newlines, byte-for-byte what
`python -m seams_gen` writes.

The command also writes `seams.lock` next to `seams.toml` and prints its path
last. The lock is deterministic JSON recording, per output, the generator and its
version, the model hash, the file's sha256 and the source element IRIs (D043);
`lockfile.py` reads, builds and audits it. An output the old lock lists but no
generator writes any more is deleted (`removed <path>` on stdout) when it is a
regular file still matching its locked hash; otherwise it is kept. Hand-edited,
deleted and kept outputs are reported on stderr. Commit the lock with the
outputs. See [docs/reference/seams-cli.md](../../docs/reference/seams-cli.md#the-lockfile).

The model is, in order of precedence: `--model`, the project's `model`, then
the `SEAMS_MODEL` environment variable when it is non-empty. As with
`seams.load`, an explicit path beats the environment (D034). With none of the
three, the command fails.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | every output was written |
| 1 | a file could not be read or written |
| 2 | the project file is missing or malformed, `seams.lock` is malformed, no model was given, or a generator found a missing or ambiguous graph fact |

Errors print to stderr as `seams generate: <message>`; a project-file error
names the file and the offending key.

## seams check

```sh
seams check                            # the seams.toml in the working directory
seams check --project examples/expenses/chapter-08
```

It writes nothing (D044, `check.py`). It validates the model, unioned with
`ontology/*.ttl`, against `ontology/shapes/seam-shapes.ttl`; runs each gate
query over the same graph; and runs every generator in memory to compare the
outputs with the disk and `seams.lock`. Each finding prints to stdout as
`<kind> <detail>`, with kind one of `shacl`, `gate`, `missing`, `stale`,
`hand-edited`, `orphan`, `lock-out-of-date` and, with `coverage = ["paths"]`,
`coverage` (the process IRI and the node IRIs of an unexercised path), followed by
`seams check: N problem(s)` on stderr. It exits 0 with no findings, 1 with any,
and 2 for the errors of `seams generate` plus a missing, unparsable or
non-SELECT gate, an unknown `coverage` entry or a model that cannot be loaded. See
[docs/reference/seams-cli.md](../../docs/reference/seams-cli.md#seams-check).

## seams status

```sh
seams status                           # the seams.toml in the working directory
seams status --project examples/chat-app --env local --timeout 2
```

It GETs `<url>/healthz` for each runtime container of the model (the ones the
compose generator gives `SEAMS_MODEL_HASH`), with URLs from the chosen
environment's `endpoints` (D045, `status.py`). `--env` defaults to the only
environment that has endpoints. Each container prints as
`<container> <verdict> <reported hash or -> <detail>`, then
`current model <hash>`. The verdict is `current` (same hash), `behind` (a hash
some committed version of `seams.lock` records; the detail counts model changes
behind), `ahead` (any other hash, or every differing hash outside git) or
`unreachable` (no endpoint, connection error, timeout, non-2xx, or no
`model_hash`). It exits 0 when all are current, 1 otherwise with
`seams status: N of M not current` on stderr, and 2 for a project, environment
or model error. See
[docs/reference/seams-cli.md](../../docs/reference/seams-cli.md#seams-status).

## seams sequence

```sh
seams sequence :send_message --project examples/chat-app
seams sequence :submit_expense --project examples/expenses/chapter-08 --out build/sequences
```

It derives the as-designed Mermaid sequence diagrams of one IFML event (a CURIE,
local name or full IRI) from the project's model, one per exclusive-gateway path
(D047, `sequence.py`, `run_sequence`), and writes each as `<out>/<name>.mmd`;
`--out` defaults to `<project root>/sequences`. The model is chosen as for
`seams generate`. Each written path is printed. Each fact the deriver could not
place prints to stderr as `seams sequence: gap <name>: <detail>` and the exit
code stays 0; the diagrams are not recorded in `seams.lock`. A project error, an
unloadable model or an unknown event exits 2.

`--trace RUN` draws one recorded run as `<out>/<event>.executed.mmd` from the
worker's trace rows, on the same lifelines (backlog U4). RUN is a trace JSON
file (an instance result or a bare list of rows) or an instance id in the
runtime's SQLite store, `--db PATH`, defaulting to `SEAMS_DB`, else
`<project root>/seams.sqlite`. An instance missing from the store or a trace
file that is not JSON exits 2; `--db` without `--trace` is a usage error. See
[docs/reference/seams-cli.md](../../docs/reference/seams-cli.md#seams-sequence).

## seams diff

```sh
seams diff examples/expenses/chapter-08/expenses.trig examples/expenses/chapter-09/expenses.trig
seams diff old/ new/ --json
```

It compares the SHACL shapes and operation contracts (`seam:acceptsShape`,
`seam:returnsShape`) of two model versions, each a TriG file or a directory,
and classifies every change as compatible or breaking for stored data and for
operation contracts (D052, `diff.py`, `diff_models`). It reads no `seams.toml`.
Node shapes and operations are matched by IRI, with `new owl:sameAs old` in NEW
read as a rename; property shapes by node shape and `sh:path`. A removed shape,
property or operation, a new required property, a changed accepted or returned
shape, a changed `sh:datatype` or `sh:class` and a tighter `sh:minCount` or
`sh:maxCount` are breaking; additions of optional properties, shapes and
operations, and looser bounds, are compatible.

Each change prints as `<verdict> <kind> <subject> <detail>`, sorted, with
CURIEs where a prefix is bound; `--json` prints `to_json`'s changes (with their
`data`/`contract` scopes) and counts instead. It exits 0 with no breaking
change, 1 with any, after `seams diff: N breaking, M compatible` on stderr, and
2 when a model cannot be loaded. See
[docs/reference/seams-cli.md](../../docs/reference/seams-cli.md#seams-diff).

## seams plan

```sh
seams plan examples/expenses/chapter-08 examples/expenses/chapter-09
seams plan main:examples/expenses/expenses.trig examples/expenses/expenses.trig --output CHANGES.md
```

It writes a Markdown change plan, or release notes (D053, `plan.py`,
`render`): the breaking and then the compatible `seams diff` changes, then
`## Elements by layer` with the element IRIs each changed layer adds and
removes (`layer_changes`, matched by IRI through the `seams.Model` views), as
CURIEs. Either argument may be a git `REF:PATH` when the text before the colon
is not an existing path; `resolve` extracts it with `git archive` into a
temporary directory. The plan goes to stdout or to `--output FILE`. Exit codes
and the stderr summary are `seams diff`'s; a failing git or an unknown ref exits
2 with a message naming the ref. See
[docs/reference/seams-cli.md](../../docs/reference/seams-cli.md#seams-plan).

## seams coverage

```sh
seams coverage                         # the model of the seams.toml in the working directory
seams coverage examples/expenses/chapter-09 --json
```

It lists what the model declares that nothing exercises (D054, `coverage.py`,
`coverage_report`, over `seams.coverage`): `path <process> <node>...` for each
start-to-end BPMN path no verify:Scenario runs, `transition <lifecycle>
<transition>` for each state:Transition nothing seam:fires, and `policy <policy>
<target> <assignee>` for each odrl:permission the `tests` generator writes no
party deny test for, all as full IRIs. MODEL is a TriG file or a directory;
without it, `--project`'s model is used. `--json` prints `to_json`'s three lists
and counts instead. It exits 0 with no gap, 1 with any, after
`seams coverage: N unexercised path(s), M unfired transition(s), K permission(s)
without a deny test` on stderr, and 2 when the project or model cannot be
loaded. See
[docs/reference/seams-cli.md](../../docs/reference/seams-cli.md#seams-coverage).

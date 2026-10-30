# The seams CLI

`seams` is the command line for a Semantic Seams project. It reads a project
file, `seams.toml`, kept next to an app's model. `seams generate` runs every
generator the file names; `seams check` fails when the model, its gate queries
or the generated outputs are not in order, and writes nothing. Its distribution name is `semanticseams-cli` and its import name is
`seams_cli` ([packages/seams-cli/](../../packages/seams-cli/README.md)). Like the
[seams library](/reference/seams-library), it is a uv workspace member and is not
published to PyPI. `uv sync --all-packages` installs the `seams` console script
into `.venv/bin`:

```sh
uv sync --all-packages
source .venv/bin/activate
seams generate --project examples/chat-app
```

## The project file

```toml
model = "chat-app.trig"

[[generators]]
name = "fastapi"
out = "generated"

[[generators]]
name = "htmx"
out = "generated/templates"

[environments.prod]
```

| Key | Type | Meaning |
|---|---|---|
| `model` | string, optional | The TriG file to generate from. |
| `[[generators]]` | array of tables | One entry per generator to run, in any order. |
| `[[generators]].name` | string | A generator name from `seams_gen` (see [Generators](#generators)). |
| `[[generators]].out` | string | The directory the generator writes into. |
| `gates` | array of strings, optional | SPARQL SELECT files that [`seams check`](#seams-check) runs over the model; each must return no rows. |
| `[environments.<name>]` | table of tables, optional | The app's environment names. Only the names are read for now; the tables are a placeholder. |

Relative paths (`model`, every `out` and every gate) resolve against the directory holding
the `seams.toml`, not the working directory, so the command gives the same
result wherever it is run from.

### The model

The model is the first of:

1. `--model PATH` on the command line;
2. the project file's `model`;
3. the `SEAMS_MODEL` environment variable, when it is set and non-empty.

An explicit path always beats the environment, as with `seams.load`. With none
of the three, `seams generate` and `seams check` fail with exit code 2.

## seams generate

```sh
seams generate                                    # the seams.toml in the working directory
seams generate --project examples/expenses/chapter-03
seams generate --project path/to/seams.toml --model other.trig
```

| Option | Default | Meaning |
|---|---|---|
| `--project PATH` | `.` | A `seams.toml` file, or a directory holding one. |
| `--model PATH` | none | The model (`.trig`); overrides the project file and `SEAMS_MODEL`. |

Every generator runs in memory first. The files are written only when all of
them succeed, so a failing generator leaves every output untouched. Each output
is written as UTF-8 with `\n` newlines, byte-for-byte what
`python -m seams_gen <generator>` writes into the same directory. The command
then prints each written path on stdout, sorted, relative to the working
directory when it lies below it:

```
$ seams generate --project examples/chat-app
compose.yaml
examples/chat-app/generated/chat_api.py
examples/chat-app/generated/templates/chat_page.html
...
examples/chat-app/seams.lock
```

The last line is always the project's lockfile, written after every output.

### The lockfile

`seams generate` keeps a `seams.lock` next to the `seams.toml` and commits it
with the outputs. It is JSON with sorted keys, two-space indentation and a
trailing newline, so the same model and generators give the same bytes and a
diff shows which model hash and generator version produced each file. The top
level holds:

| Key | Meaning |
|---|---|
| `lockfile_version` | The format version, `1`. |
| `model` | The model path, relative to the project directory. |
| `model_hash` | `seams.model_hash` of the model, `sha256:<hex>`. |
| `outputs` | One entry per generated file, sorted by `path`. |

Each output entry records the generator, its version, the model hash, the
file's sha256 and the full IRIs of the model elements the file came from
(`seams_gen.sources`, see the [seams_gen README](../../seams_gen/README.md)).
The `path` is POSIX and relative to the project directory, so it may start with
`../`. An entry from
[`examples/chat-app/seams.lock`](../../examples/chat-app/seams.lock):

```json
{
  "generator": "compose",
  "generator_version": "0.1.0",
  "model_hash": "sha256:21f7f4bc15f69eb971d28ede8c003d2def8b4331c2b46468ccb17a0792fca1b6",
  "path": "../../compose.yaml",
  "sha256": "f1f50c2aeaa06ce79e7f90352db5935c3825d545434fdc7a1fec9884497c7845",
  "sources": [
    "https://example.org/chat/chat_api",
    "https://example.org/chat/chat_system",
    "https://example.org/chat/chat_ui",
    "https://example.org/chat/llm_gateway",
    "https://example.org/chat/message_db"
  ]
}
```

A project whose generators write nothing (expense chapters 1 and 2) gets a lock
with an empty `outputs` list.

Before writing, `seams generate` compares the old lock with the files on disk
and with the new outputs:

- **Orphans.** An output the old lock lists but no generator writes any more,
  for example after a generator is removed from `seams.toml`, is deleted and
  printed on stdout as `removed <path>`, but only when it is a regular file (not
  a symlink) whose sha256 still equals the locked one. Otherwise it is kept and
  reported. A lock can therefore delete only a file whose exact content it
  already records.
- **Hand edits.** A locked output whose file differs from both the locked hash
  and the new text is overwritten and reported.
- **Deleted outputs.** A locked output missing on disk is written again and
  reported.

The reports go to stderr and do not change the exit code:

```
seams generate: overwrote hand-edited examples/chat-app/generated/chat_api.py
seams generate: restored deleted examples/chat-app/generated/templates/chat_page.html
seams generate: kept hand-edited orphan examples/chat-app/generated/old.html
```

Without a lock (a first run) there is nothing to compare, so nothing is
reported or deleted. A `seams.lock` that is not valid JSON or does not match the
format exits 2 before any file is written, naming the file and the key. A
failing generator likewise leaves the old lock and every file untouched.
[`seams check`](#seams-check) uses the same comparison and fails when an output
was edited by hand.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Every output was written. |
| 1 | A file could not be read or written. |
| 2 | The project file is missing or malformed, `seams.lock` is malformed, no model was given, or a generator found a missing or ambiguous graph fact. |

Errors print to stderr as `seams generate: <message>`. A project-file error
names the file by its absolute path and the offending key, for example
``/…/examples/chat-app/seams.toml: `generators[0]` needs a string `out` ``, and
an unknown generator name lists the known ones.

## seams check

```sh
seams check                                       # the seams.toml in the working directory
seams check --project examples/expenses/chapter-08
seams check --project path/to/seams.toml --model other.trig
```

The options are those of `seams generate`. The command runs three checks,
reports every finding and writes nothing, so it is safe in CI and in a
pre-commit hook (D044):

1. **Shapes.** The model, unioned with `ontology/*.ttl`, is validated with
   pyshacl (inference off) against `ontology/shapes/seam-shapes.ttl`, the same
   check as the viewer's health panel. Each validation result is a `shacl`
   finding: focus node, path and message.
2. **Gates.** Each file the project lists under `gates` is a SPARQL SELECT
   query that runs over the same union graph. Every row it returns is a `gate`
   finding: the gate path, relative to the project, then the row's values.
   This repository's gate, `docs/queries/gates/ungoverned-writes.rq`, lists
   each UI event that can write a data shape with no policy governing it: a
   write open to any authenticated identity. The chat app and expense chapters
   7 and 8 reach it with a path that climbs out of the project into `docs/`;
   a project outside this repository keeps its gates next to its `seams.toml`,
   for example `gates = ["gates/ungoverned-writes.rq"]`.
3. **Outputs.** Every generator runs in memory and the result is compared with
   the disk and with `seams.lock`.

| Kind | Meaning |
|---|---|
| `shacl` | The model breaks a shape. |
| `gate` | A gate query returned a row. |
| `missing` | An output generate would write is absent on disk. |
| `stale` | An output on disk differs from what generate would write now, for example after a model change. |
| `hand-edited` | A stale output whose sha256 is not the locked one either: someone edited it. |
| `orphan` | `seams.lock` lists an output no generator writes any more, and it is still on disk. |
| `lock-out-of-date` | There is no `seams.lock`, or the lock generate would write differs from it. |

Findings print to stdout as `<kind> <detail>`, sorted, with paths relative to
the working directory when they lie below it. A closing count goes to stderr:

```
$ seams check --project examples/expenses/chapter-05
gate examples/expenses/chapter-05/gates/events.rq https://example.org/expenses/submit_expense
hand-edited examples/expenses/chapter-05/generated/expense_api.py
lock-out-of-date examples/expenses/chapter-05/seams.lock
shacl https://example.org/expenses/expense_data https://w3id.org/seams/seam#notation Every seam:Model has exactly one seam:notation, and it is a seam:Notation.
seams check: 4 problem(s)
```

`seams generate` fixes every output finding. A `shacl` or `gate` finding is
fixed in the model.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | No findings. |
| 1 | At least one finding, or a file could not be read. |
| 2 | The project file is missing or malformed, a gate is missing, unparsable or not a SELECT query, `seams.lock` is malformed, no model was given, the model cannot be loaded, or a generator found a missing or ambiguous graph fact. |

Errors print to stderr as `seams check: <message>`.

## Generators

The generator names are the `python -m seams_gen` subcommands. The
[seams_gen README](../../seams_gen/README.md) gives each one's rules.

| Name | Writes into `out` |
|---|---|
| `fastapi` | `<container>.py`, the route module of the serving container |
| `htmx` | the Jinja2/htmx page templates and their partials |
| `compose` | `compose.yaml`, with bind-mount sources relative to `out` |

`python -m seams_gen <generator> <model> --out <dir>` still runs a single
generator without a project file.

## Worked example: the chat app

[`examples/chat-app/seams.toml`](../../examples/chat-app/seams.toml) names all
three generators. The compose file goes to the repository root (`out = "../.."`)
because `docker compose up` runs there:

```toml
model = "chat-app.trig"

[[generators]]
name = "fastapi"
out = "generated"

[[generators]]
name = "htmx"
out = "generated/templates"

# The repository-root compose.yaml; its bind mounts are relative to the root.
[[generators]]
name = "compose"
out = "../.."

[environments.prod]
```

`seams generate --project examples/chat-app` rewrites
`examples/chat-app/generated/`, the root `compose.yaml` and
`examples/chat-app/seams.lock`. Each chapter of the
[expense tutorial](/tutorials/expenses/) has its own project file in
`examples/expenses/chapter-NN/seams.toml`. CI runs `seams generate` for the chat
app and every chapter, then fails on any `git diff` or untracked file under
`examples/` or `compose.yaml`.

## Planned

`seams status` is planned; see
[the backlog](/backlog#artifact-management-and-deployment).

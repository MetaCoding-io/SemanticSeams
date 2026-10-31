# The seams CLI

`seams` is the command line for a Semantic Seams project. It reads a project
file, `seams.toml`, kept next to an app's model. `seams generate` runs every
generator the file names; `seams check` fails when the model, its gate queries
or the generated outputs are not in order, and writes nothing; `seams sequence`
derives an event's sequence diagrams; `seams diff` classifies the shape and
operation-contract changes between two model versions as compatible or breaking. Its distribution name is `semanticseams-cli` and its import name is
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
| `[environments.<name>]` | table of tables, optional | The app's environment names. |
| `[environments.<name>].endpoints` | inline table of strings, optional | Container local name to base URL, read by [`seams status`](#seams-status). Any other key in an environment table is ignored. |

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

### In CI

The composite action
[`.github/actions/seams-check`](../../.github/actions/seams-check/README.md) runs
`seams check --project` for each line of its `projects` input (default `.`), each
in its own log group, and fails after the last project if any had a finding. The
CLI is not published, so `seams` must be on PATH before the action runs. This
repository's acceptance job does:

```yaml
- run: uv sync --locked --all-packages
- run: echo "$PWD/.venv/bin" >> "$GITHUB_PATH"
- name: Generated outputs are current
  uses: ./.github/actions/seams-check
  with:
    projects: |
      examples/chat-app
      examples/expenses/chapter-01
```

Another repository references it as
`MetaCoding-io/SemanticSeams/.github/actions/seams-check@<ref>`.

### As a pre-commit hook

The repository root's `.pre-commit-hooks.yaml` defines the `seams-check` hook. It
uses `language: system`, so `seams` must be installed and on PATH; it runs on
commits that touch a `seams.toml`, `seams.lock`, model, query, BPMN or DMN file or
anything under `generated/`. Without `args` it checks the `seams.toml` in the
repository root:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/MetaCoding-io/SemanticSeams
    rev: <commit or tag>
    hooks:
      - id: seams-check
        args: [--project, examples/chat-app]
```

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

[environments.local]
endpoints = { chat_api = "http://localhost:8080" }
```

`seams generate --project examples/chat-app` rewrites
`examples/chat-app/generated/`, the root `compose.yaml` and
`examples/chat-app/seams.lock`. Each chapter of the
[expense tutorial](/tutorials/expenses/) has its own project file in
`examples/expenses/chapter-NN/seams.toml`. CI runs `seams check` for the chat app
and every chapter through the [seams-check action](#in-ci), and fails on any
finding.

## seams status

```sh
seams status                                      # the seams.toml in the working directory
seams status --project examples/chat-app --env local
seams status --project examples/expenses/chapter-08 --timeout 2
```

| Option | Default | Meaning |
|---|---|---|
| `--project PATH` | `.` | A `seams.toml` file, or a directory holding one. |
| `--model PATH` | none | The model (`.trig`); overrides the project file and `SEAMS_MODEL`. |
| `--env NAME` | the only environment with `endpoints` | The `[environments.<name>]` whose endpoints to read. |
| `--timeout SECONDS` | `5` | How long to wait for each `/healthz`. |

`seams status` asks each running runtime container which model it is on and
compares the answer with the model in the working tree (D045). It writes
nothing.

### Endpoints

The containers come from the model: they are the runtime containers, the ones
the [compose generator](#generators) gives `SEAMS_MODEL_HASH`. Their base URLs
come from the project file, because the generated compose file only exposes a
runtime's port inside the stack and the model holds no URLs yet:

```toml
[environments.local]
endpoints = { chat_api = "http://localhost:8080" }
```

Each key is a runtime container's local name and each value a base URL;
`seams status` GETs `<url>/healthz`. In the chat app and expense chapter 8 the
UI container (Caddy) on port 8080 proxies `/healthz` to the runtime, so
`http://localhost:8080` reaches it from the host.

With no `--env`, the command uses the only environment that has `endpoints`.
No such environment, more than one, an unknown `--env`, or an endpoint naming a
container that is not a runtime container of the model is an error (exit 2).
A runtime container with no endpoint in the chosen environment is reported as
unreachable.

### Verdicts

Each container gets one verdict by comparing the `model_hash` its `/healthz`
reports with the hash of the current model (`seams.model_hash`):

| Verdict | Meaning |
|---|---|
| `current` | The same hash. |
| `behind` | A different hash that some version of the project's `seams.lock` in `HEAD`'s git history records. The detail counts the model changes behind, for example `2 model changes behind`. |
| `ahead` | A different hash that no committed `seams.lock` records: the container runs a newer or diverged model. Outside a git repository, or with no committed lock, every differing hash is ahead. |
| `unreachable` | No endpoint, a connection error, a timeout, a non-2xx response, invalid JSON, or a body with no string `model_hash`. The detail names the URL and the error. |

A hash has no order of its own. The lock already records the model hash of
every generation, so its history (`git log HEAD -- seams.lock`, then
`git show` of each version) orders the past hashes: the newest distinct hash
before the current one is 1 change behind, the next 2, and so on.

### Output

One stdout line per runtime container, sorted by name, as
`<container> <verdict> <reported hash or -> <detail>`, then the current model's
hash. Against the stack `docker compose up` starts from the repository root:

```
$ docker compose up -d --wait
$ seams status --project examples/chat-app --env local
chat_api current sha256:21f7f4bc15f69eb971d28ede8c003d2def8b4331c2b46468ccb17a0792fca1b6
current model sha256:21f7f4bc15f69eb971d28ede8c003d2def8b4331c2b46468ccb17a0792fca1b6
```

With the stack down, the container is unreachable and the count goes to stderr:

```
$ seams status --project examples/chat-app --env local
chat_api unreachable - http://localhost:8080/healthz: [Errno 111] Connection refused
current model sha256:21f7f4bc15f69eb971d28ede8c003d2def8b4331c2b46468ccb17a0792fca1b6
seams status: 1 of 1 not current
```

After a model edit and `seams generate`, a container still running the old
build reads `chat_api behind sha256:… 1 model change behind` until it is
rebuilt or restarted.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Every runtime container is current. |
| 1 | At least one is behind, ahead or unreachable. |
| 2 | The project file is missing or malformed, the environment is missing, unknown or ambiguous, an endpoint names no runtime container, no model was given, or the model cannot be loaded. |

Errors print to stderr as `seams status: <message>`.

## seams sequence

```sh
seams sequence :send_message --project examples/chat-app
seams sequence :submit_expense --project examples/expenses/chapter-08 --out build/sequences
seams sequence :send_message --project examples/chat-app --trace tests/fixtures/traces/chat_send_message.json
```

| Option | Default | Meaning |
|---|---|---|
| `EVENT` | required | The IFML event: a CURIE (`:send_message`), a local name or a full IRI. |
| `--project PATH` | `.` | A `seams.toml` file, or a directory holding one. |
| `--model PATH` | none | The model (`.trig`); overrides the project file and `SEAMS_MODEL`. |
| `--out DIR` | `<project root>/sequences` | The directory the `.mmd` files are written to. |
| `--trace RUN` | none | Draw one recorded run as `<event>.executed.mmd`: a trace JSON file, or an instance id in the `--db` store. |
| `--db PATH` | `SEAMS_DB`, else `<project root>/seams.sqlite` | The runtime's SQLite store to read an instance id from. Only valid with `--trace`. |

`seams sequence` derives the as-designed Mermaid sequence diagrams of an IFML
event (backlog U1, D047). The arrows come only from graph facts, and their order
from the sequence flows of the BPMN process the event triggers. There is one
diagram per path through the exclusive gateways, never an `alt` block: the chat
app's `:send_message` gives `send_message.mmd`, and expense chapter 8's
`:submit_expense` gives `submit_expense--auto.mmd`,
`submit_expense--manager--approved.mmd`, `submit_expense--manager--rejected.mmd`,
`submit_expense--finance--approved.mmd` and `submit_expense--finance--rejected.mmd`.
The committed goldens are under `docs/generation/sequences/`. The fact-to-arrow
rules are listed in [seams_gen/README.md](../../seams_gen/README.md#sequence-diagrams);
`python -m seams_gen.sequence <trig> <event> --out DIR` runs the same deriver
without a project file.

The diagrams are views, so they are not generator outputs: `seams generate` does
not write them and `seams.lock` does not record them.

### As executed: --trace

`--trace RUN` draws one recorded run instead of the as-designed paths (backlog
U4). The rows come from the trace the runtime's worker records, one per BPMN
element it ran. RUN is either a JSON file, holding an instance result (`{"instance":
..., "trace": [...]}`) or a bare list of rows, or an instance id. An instance id
is read from the `workflow_state` checkpoint in the runtime's SQLite store:
`--db PATH`, else `SEAMS_DB`, else `<project root>/seams.sqlite`. The diagram
is written as `<out>/<event>.executed.mmd` on the same actor, UI and API
lifelines as the as-designed diagram, and its header names the run
(`%% run: <id>`):

```
$ seams sequence :send_message --project examples/chat-app --trace 3f2a... --out build
build/send_message.executed.mmd
```

A row the model cannot place (an IRI that is not an element of the triggered
process, or an unknown container or channel) is a gap, reported as below. An
instance id missing from the store, or a trace file that is not JSON, exits 2;
`--db` without `--trace` is a usage error. The committed golden is
`docs/generation/sequences/chat-app/send_message.executed.mmd`, drawn from
`tests/fixtures/traces/chat_send_message.json`.

### Gaps

An arrow the deriver cannot place, because a fact is missing from the model, is
a gap. It is written into the diagram's header as a `%% gap:` comment and
printed to stderr. With `MessageShape seam:storedIn :message_db` removed from the
chat app:

```
$ seams sequence :send_message --project examples/chat-app --model edited.trig --out build
seams sequence: gap send_message: MessageShape written by persist_user_msg has no seam:storedIn
seams sequence: gap send_message: MessageShape written by persist_response has no seam:storedIn
build/send_message.mmd
```

Gaps are an audit of the model, not a failure, so the exit code stays 0.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | The diagrams were written, with or without gaps. |
| 1 | A file could not be read or written. |
| 2 | The project file is missing or malformed, no model was given, the model cannot be loaded, the event is unknown, the `--trace` instance is not in the store, the trace file is not JSON, or `--db` was given without `--trace`. |

Errors print to stderr as `seams sequence: <message>`.

## seams diff

```sh
seams diff examples/expenses/chapter-08/expenses.trig examples/expenses/chapter-09/expenses.trig
seams diff old/ new/ --json
```

| Option | Default | Meaning |
|---|---|---|
| `OLD` | required | The old model: a `.trig` file, or a directory whose TriG files load as one model. |
| `NEW` | required | The new model, in the same form. |
| `--json` | off | Print the changes, their scopes and the counts as JSON instead of text. |

`seams diff` says whether a model change is safe for stored data and for
operation contracts (backlog U8, D052). It reads no `seams.toml`. It compares
the SHACL shapes and the operation contracts (`seam:acceptsShape`,
`seam:returnsShape`) of two model versions and classifies each change:

| Change | Verdict |
|---|---|
| A node shape added | compatible |
| A node shape removed | breaking |
| A node shape renamed (`new owl:sameAs old`, stated in NEW) | compatible |
| A property added with no `sh:minCount`, or `sh:minCount 0` | compatible |
| A property added with `sh:minCount` above 0 | breaking |
| A property removed | breaking |
| An `sh:datatype` or `sh:class` changed or added | breaking |
| An `sh:datatype` or `sh:class` dropped | compatible |
| `sh:minCount` raised, or `sh:maxCount` lowered or added | breaking |
| `sh:minCount` lowered, or `sh:maxCount` raised or dropped | compatible |
| An operation added | compatible |
| An operation removed | breaking |
| An operation's accepted or returned shape changed | breaking |

Node shapes and operations are matched by IRI ([ADR-0002](/adr/0002-iri-identity-and-migration));
property shapes by their node shape and `sh:path`, since they are often blank
nodes. Every change is in the `data` scope when it is a shape change, and also
in the `contract` scope when an operation in either model accepts or returns
that shape; operation changes are in `contract` only.

### Output

Each change prints as `<verdict> <kind> <subject> <detail>`, sorted by subject,
with CURIEs wherever the new or old model binds a prefix. The detail is `-` for
an added or removed shape or operation, the path and the new `sh:minCount` for
an added property, and the path with `before -> after` for a changed one.
Diffing expenses chapter 9 back to chapter 8:

```
$ seams diff examples/expenses/chapter-09 examples/expenses/chapter-08
breaking shape-removed :NotificationShape -
breaking shape-removed :NotifyProblemShape -
breaking operation-removed :notify_failed -
breaking operation-removed :notify_manager_op -
seams diff: 4 breaking, 0 compatible
```

`--json` prints `{"changes": [...], "counts": {"breaking": N, "compatible": M}}`;
each change has `verdict`, `kind`, `subject` and `detail` with full IRIs, and a
sorted `scopes` list. The output is deterministic, so it can be committed or
compared.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | No change is breaking (there may be compatible ones, or none at all). |
| 1 | At least one change is breaking; `seams diff: N breaking, M compatible` goes to stderr. |
| 2 | A model is missing or cannot be loaded. |

Errors print to stderr as `seams diff: <message>`.

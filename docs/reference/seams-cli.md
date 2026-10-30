# The seams CLI

`seams` is the command line for a Semantic Seams project. It reads a project
file, `seams.toml`, kept next to an app's model, and runs every generator the
file names. Its distribution name is `semanticseams-cli` and its import name is
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
| `[environments.<name>]` | table of tables, optional | The app's environment names. Only the names are read for now; the tables are a placeholder. |

Relative paths (`model` and every `out`) resolve against the directory holding
the `seams.toml`, not the working directory, so the command gives the same
result wherever it is run from.

### The model

The model is the first of:

1. `--model PATH` on the command line;
2. the project file's `model`;
3. the `SEAMS_MODEL` environment variable, when it is set and non-empty.

An explicit path always beats the environment, as with `seams.load`. With none
of the three, `seams generate` fails with exit code 2.

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
```

A generator that stops writing a file does not delete its old copy; delete the
committed file yourself.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Every output was written. |
| 1 | A file could not be read or written. |
| 2 | The project file is missing or malformed, no model was given, or a generator found a missing or ambiguous graph fact. |

Errors print to stderr as `seams generate: <message>`. A project-file error
names the file by its absolute path and the offending key, for example
``/…/examples/chat-app/seams.toml: `generators[0]` needs a string `out` ``, and
an unknown generator name lists the known ones.

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
`examples/chat-app/generated/` and the root `compose.yaml`. Each chapter of the
[expense tutorial](/tutorials/expenses/) has its own project file in
`examples/expenses/chapter-NN/seams.toml`. CI runs `seams generate` for the chat
app and every chapter, then fails on any `git diff` or untracked file under
`examples/` or `compose.yaml`.

## Planned

`seams check` (validate the model and confirm the outputs are current),
`seams status` and a lockfile recording what was generated are planned; see
[the backlog](/backlog#artifact-management-and-deployment).

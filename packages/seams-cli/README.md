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
- `environments` (table of tables, optional): environment names. Only the
  names are read for now; the tables are a placeholder.

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

`seams check` and `seams status` are planned (M012/S03, S04).

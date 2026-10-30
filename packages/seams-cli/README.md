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
`hand-edited`, `orphan` and `lock-out-of-date`, followed by
`seams check: N problem(s)` on stderr. It exits 0 with no findings, 1 with any,
and 2 for the errors of `seams generate` plus a missing, unparsable or
non-SELECT gate or a model that cannot be loaded. See
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

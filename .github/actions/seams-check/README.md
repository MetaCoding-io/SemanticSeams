# seams-check action

A composite action that runs [`seams check`](../../../docs/reference/seams-cli.md#seams-check)
for each listed project. It validates the model against the SHACL shapes, runs the
project's `gates` queries, and fails on any stale, missing, hand-edited or orphaned
output or an out-of-date `seams.lock`. It writes nothing.

Every project runs, each in its own log group, before the step fails; it exits 1 if
any project had a finding or an error.

## Usage

The seams CLI is not published, so put `seams` on PATH before the action runs. In
this repository:

```yaml
- run: uv sync --locked --all-packages
- run: echo "$PWD/.venv/bin" >> "$GITHUB_PATH"
- uses: ./.github/actions/seams-check
  with:
    projects: |
      examples/chat-app
      examples/expenses/chapter-08
```

From another repository, reference it as
`MetaCoding-io/SemanticSeams/.github/actions/seams-check@<ref>`.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `projects` | `.` | Newline-separated project paths, each a `seams.toml` file or the directory holding one. Blank lines are ignored. |

# seams-plan action

A composite action that writes a [`seams plan`](../../../docs/reference/seams-cli.md#seams-plan)
change plan to the job summary for each listed project whose files differ from a
base git ref. Each plan lists the breaking and compatible changes `seams diff`
finds and the elements each layer adds and removes.

For each project the action:

- skips it when `git diff --quiet BASE -- PROJECT` finds no change;
- reports it as new when it does not exist at the base ref;
- otherwise runs `seams plan BASE:PROJECT PROJECT` and appends the plan to
  `$GITHUB_STEP_SUMMARY` under a heading naming the project.

A breaking change (`seams plan` exit 1) adds a warning annotation but does not fail
the step; the plan is a report for the reviewer, and `seams check` is the gate. The
step fails (exit 1) after every project has run if the base ref is unknown, `git diff`
fails, or `seams plan` cannot load a model (exit 2). When nothing changed, the summary
says so.

## Usage

The checkout needs the base ref's history, and the seams CLI is not published, so
put `seams` on PATH before the action runs. In this repository's `change-plan` job,
which runs on pull requests:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
- run: uv sync --locked --all-packages
- run: echo "$PWD/.venv/bin" >> "$GITHUB_PATH"
- uses: ./.github/actions/seams-plan
  with:
    base: origin/${{ github.base_ref }}
    projects: |
      examples/chat-app
      examples/expenses/chapter-08
```

From another repository, reference it as
`MetaCoding-io/SemanticSeams/.github/actions/seams-plan@<ref>`.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `projects` | `.` | Newline-separated project paths relative to the repository root, each a directory or the `seams.toml` file in one. Blank lines are ignored. |
| `base` | required | The git ref to compare against, such as `origin/main`. |

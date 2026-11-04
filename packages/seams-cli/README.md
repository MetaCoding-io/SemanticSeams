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

[environments.development]
```

- `model` (string, optional): the TriG file to generate from.
- `generators` (array of tables): each entry has a `name` and an `out`
  directory. The name is one registered in the `seams.generators` entry-point
  group (D056, [ADR-0016](../../docs/adr/0016-generator-protocol.md)): a
  built-in (`compose`, `dockerfile`, `fastapi`, `htmx`, `ifmledit`, `smoke`,
  `tests`, declared in this package's `pyproject.toml`) or one from any
  installed distribution. An unknown name is a project error listing the known
  ones.
- `gates` (array of strings, optional): SPARQL SELECT files, relative to the
  project file, that `seams check` runs over the model; each must return no
  rows.
- `coverage` (array of strings, optional): `["paths"]` makes `seams check`
  report each BPMN path no scenario runs as a `coverage` finding (D054).
- `propose` (table, optional): `provider`, the command `seams propose` sends
  its prompt to (D059); `--provider` overrides it.
- `environments` (table of tables, optional): environment names, the local
  names of the model's `arch:Environment`s (the compose generator writes
  `compose.<name>.yaml` for each, ADR-0015). An environment may carry an `endpoints` inline table, container local name to
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
succeed, so a failing generator leaves every output untouched. Before any
runs, a generator that declares precondition shapes has them checked (strict
mode): the model, unioned with `ontology/*.ttl`, is validated against
`ontology/shapes` once, and a result of one of those shapes fails the command
with exit 2, naming the focus node, the shape and the generator, and writes
nothing. Projects that use only the built-ins skip the validation: they declare
no preconditions.

With `--lenient` (D057) it collects faults instead of stopping: a precondition
result becomes a fault and the generator still runs, and a generator that
raises `GeneratorError` writes nothing and adds a fault, its previously locked
outputs kept rather than deleted as orphans. Each fault prints to stderr as
`seams generate: fault <generator>: <focus>: <shape>: <message>`, then
`seams generate: N fault(s); output is flagged`, and the exit code is 0. Each written
path is printed, relative to the working directory when it lies below it.
Files are written as UTF-8 with `\n` newlines, byte-for-byte what
`python -m seams_gen` writes.

The command also writes `seams.lock` next to `seams.toml` and prints its path
last. The lock is deterministic JSON recording, per output, the generator and that
generator's own `version` (`seams_gen.__version__` for the built-ins), the model hash, the file's sha256 and the source element IRIs (D043);
a generator with a `trace` hook also writes `<output>.trace.json` beside each output
(ADR-0019), locked as an output of the same generator, and both entries' sources are
the union of the trace's terms;
`lockfile.py` reads, builds and audits it. An output the old lock lists but no
generator writes any more is deleted (`removed <path>` on stdout) when it is a
regular file still matching its locked hash; otherwise it is kept. Hand-edited,
deleted and kept outputs are reported on stderr. Commit the lock with the
outputs. A lenient run with faults adds a sorted top-level `faults` list of
`{focus, generator, message, shape}` to the lock, which flags it; without faults
the key is absent and the bytes are those of a strict run (`lockfile_version`
stays 1). See [docs/reference/seams-cli.md](../../docs/reference/seams-cli.md#the-lockfile).

The model is, in order of precedence: `--model`, the project's `model`, then
the `SEAMS_MODEL` environment variable when it is non-empty. As with
`seams.load`, an explicit path beats the environment (D034). With none of the
three, the command fails.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | every output was written (with `--lenient`, also when there were faults) |
| 1 | a file could not be read or written |
| 2 | the project file is missing or malformed, `seams.lock` is malformed, no model was given, a generator found a missing or ambiguous graph fact, the model breaks a generator's precondition shape, or a `seams.generators` entry point cannot be registered |

Errors print to stderr as `seams generate: <message>`; a project-file error
names the file and the offending key.

## seams check

```sh
seams check                            # the seams.toml in the working directory
seams check --project examples/expenses/chapter-08
```

It writes nothing (D044, `check.py`). It validates the model, unioned with
`ontology/*.ttl`, against `ontology/shapes/seam-shapes.ttl`; runs each gate
query over the same graph; checks each decision statically (a DMN `typeRef`
against its input's `sh:datatype`, gateway conditions against the variables set
upstream); reviews the model (`seams.review_findings`: lifecycle state labels
copied into `sh:in`, `sh:class` pointing at a shape, a shape without
`sh:targetClass`, a `sh:path` nothing declares); and runs every generator in
memory, leniently, to compare the outputs with the disk and `seams.lock`. Each finding prints to stdout as
`<kind> <detail>`, with kind one of `shacl`, `gate`, `missing`, `stale`,
`hand-edited`, `orphan`, `lock-out-of-date`, `flagged` (the lock records
faults from `seams generate --lenient`; the lock path and `N fault(s)`), `decision` (the decision or
sequence flow IRI, the fact and a message), `review` (the shape or path IRI,
the fact and a message), `ontology-superclass` (an ontology class, `rdfs:subClassOf`
and a superclass declared neither in the ontology nor in a resolved import,
ADR-0022) and, with `coverage = ["paths"]`,
`coverage` (the process IRI and the node IRIs of an unexercised path),
`draft-stale` (a `seams propose` draft in `seams.lock` whose task's context hash
changed; the task IRI and module path) and `draft-hand-edited` (the draft file's
sha256 differs from the record, or the file is `missing`), followed by
`seams check: N problem(s)` on stderr. `review` findings are warnings
(`ADVISORY_KINDS`), and so are `ontology-superclass`, `shacl-warning` (a `sh:Warning` shape result: a
deprecated vocabulary term is used, ADR-0021) and `vocabulary-migrated` (one per
migration step `seams.load` applied: the vocabulary, the model's version and the
tool's): they print but are not counted, and when they are the only findings
stderr says `seams check: N warning(s)` and the exit code is 0.
`run_check(project, model, ontology_dir)` takes the vocabulary tree to load,
validate and migrate against (default the repository's `ontology/`).
It exits 0 with no problems, 1 with any,
and 2 for the errors of `seams generate` except a generator fault, which the
lenient outputs check turns into a finding, plus a missing, unparsable or
non-SELECT gate, an unknown `coverage` entry or a model that cannot be loaded. See
[docs/reference/seams-cli.md](../../docs/reference/seams-cli.md#seams-check).

## seams migrate

```sh
seams migrate --project examples/expenses/chapter-01
```

It writes the vocabulary migrations that `seams.load` applies in memory into
the model's TriG files (ADR-0021 section 5, `migrate.py`). It reads the files as
written (`seams_edit.text_quads`), runs `seams.check_versions` on a copy, and
applies the per-graph difference as one patch through the `seams_edit` text
writer (ADR-0017), so comments and layout outside the changed triples survive.
The manifest graph's `owl:imports` declaration is rewritten to the shipped
version, in place in the file's `<urn:seams:graph:manifest> { }` block (every
example and tutorial checkpoint has one). Each step prints as `migrated <vocabulary> <from> <to>`, then each
written file's path. A model already on the shipped vocabularies prints
`seams migrate: nothing to migrate` to stderr, writes nothing and exits 0, so
a second run is a no-op. A model newer than the tool, a missing migration step
or a patch the writer refuses (a directory model whose new declaration no file's
`<urn:seams:graph:manifest> { }` block can take) exits 2 and writes nothing.
`migrate(model, ontology_dir)` takes the vocabulary tree to migrate against
(default the repository's `ontology/`). See
[docs/reference/seams-cli.md](../../docs/reference/seams-cli.md#seams-migrate).

## seams status

```sh
seams status                           # the seams.toml in the working directory
seams status --project examples/chat-app --env development --timeout 2
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

## seams secrets

```sh
seams secrets                          # the seams.toml in the working directory
seams secrets --project examples/chat-app --env development
seams secrets --project examples/expenses/chapter-08 --write-example
```

It checks that every configuration key and secret of each arch:Environment
exists, without reading a value (backlog A8, `secrets.py`, `run_secrets`).
For each environment (by IRI, named by its local name), each container (by
IRI) and each binding of `Container.for_environment` (by key) it prints
`<env> <container> <key> <kind> <verdict> <source or ->`. The kind is `value`,
`secret-ref`, `secret-file` or `service`. The source is the deploy:secretName,
the deploy:secretFile path relative to the project root, or the service
container, and never a value. `--env NAME` limits the rows to one environment.

Value and service rows are `present` by definition. Every other row asks the
checkers in order, and the first answer that is not `unchecked` wins:
`FileChecker` (a secret file's path exists; the file is never opened),
`DotenvChecker` (the key is named in `<project root>/.env`; only the text
before each `=` is kept, so a blank value counts too) and `DockerSecretChecker` (the secret name is in
`docker secret ls`, run once with a 10 s timeout). With no docker, a failing
command (not a swarm manager, say) or a timeout, a secret-ref row is
`unchecked`, and the reason goes to stderr as `seams secrets: unchecked:
<reason>`. No checker reads a value, so no value can reach stdout, stderr or
`--json`, which prints the rows and the count of each verdict instead.

`--write-example` also writes `<project root>/.env.example` for `--env`, else
`development`, else the first environment, and prints its path. Its keys are
sorted. A plain deploy:value keeps the model's literal, each secret is blank
under `# secret: <kind> <source>`, and each service is blank under
`# service: <container>`. The file is byte-deterministic, and the chat app's and
expense chapter 8's are committed. Copy it to `.env` and fill it in. `.env` is
git-ignored and `.env.example` is not.

| Code | Meaning |
|---|---|
| 0 | No row is missing (unchecked rows do not fail). |
| 1 | At least one row is missing, after `seams secrets: N missing` on stderr, or a file could not be read or written. |
| 2 | The project file is missing or malformed, the `--env` names no arch:Environment, no model was given, or a binding has no kind or more than one. |

See [docs/reference/seams-cli.md](../../docs/reference/seams-cli.md#seams-secrets).

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

The verdicts and the `Change` record live in `classification.py`, shared with the
vocabulary gate (ADR-0021 section 7); `diff.py` still exports them. The same module
classifies vocabulary terms: an added term, a new `owl:deprecated` flag or a looser
`rdfs:domain`/`rdfs:range` (a superclass, or none) is compatible; a removed or renamed
term (linked in NEW by `owl:sameAs`, `owl:equivalentClass`/`Property`,
`dct:isReplacedBy` or `dct:replaces`) or a narrower or unrelated domain or range is
breaking. `vocabulary_gate.py` compares two directories laid out like `ontology/`:
`diff_vocabularies` gives each vocabulary's term changes and the `seams diff` changes
of the shapes that target its terms, and `gate` lists the failures: a breaking change
without a higher major, a major bump without its `migrations/<name>/<from>-to-<to>.ru`,
a version going down, a removed vocabulary, or one without an `owl:versionIRI`.
`tests/test_vocabulary_gate.py` runs it against the `ontology/` committed at HEAD.

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

## seams context

```sh
seams context send_now --project examples/expenses/chapter-09
seams context :send_now --project examples/expenses/chapter-09 --json
```

It prints the context manifest of one service task (backlog C3, `context.py`,
`run_context`, over `seams.context_for`): the model facts and native file
fragments that code written for the task depends on, each hashed, as a review
report. TASK is a BPMN id, CURIE or full IRI; the model is chosen as for
`seams generate`. The text output is `task <iri>`, then one `<kind> <ref>
<hash>` line per item in (kind, ref) order, then `context <hash>`; `--json`
prints the same as an object with sorted keys (`task`, `items`,
`context_hash`). Refs are IRIs or model-relative `path#id`, so the output holds
no absolute path, and the same model gives the same bytes. Binding values are
never read. It exits 0 on success, 1 when the task is unknown, is not a
`proc:ServiceTask` or a fact it needs is missing (`seams context: <message>` on
stderr), and 2 on a project error or a model that cannot be loaded. See
[docs/reference/seams-cli.md](../../docs/reference/seams-cli.md#seams-context).

## seams propose

```sh
seams propose send_now --project examples/expenses/chapter-09 --provider "my-llm"
```

It drafts the handler body of one service task with an LLM (backlog C4,
`propose.py`, D059, [ADR-0020](../../docs/adr/0020-llm-drafts.md)).
`build_prompt` fills the versioned template `prompts/draft-v1.txt` from the
context manifest, the stub and the acceptance tests, with model text in DATA
fences and bindings named only. The provider is the command in `[propose]
provider` or `--provider` (shlex-split, no shell, prompt on stdin, draft on
stdout). Successful responses are cached in `.seams/drafts/` keyed by
sha256(context hash, template, provider). The draft is tested with the
module's acceptance tests in a scratch copy and written to the handlers module
only on pass (an existing one only with `--force`). An accepted draft's record
(task, path, context hash, template, provider, sha256) is upserted by task into
the `drafts` list of `seams.lock` (`lockfile.with_draft`), which `seams check`
audits for `draft-stale` and `draft-hand-edited`. Exit 0 on accept, 1 on
failed tests or a failed provider, 2 on a project error. See
[docs/reference/seams-cli.md](../../docs/reference/seams-cli.md#seams-propose).

## seams new-generator

```sh
seams new-generator checklist --reference checklist.yaml            # writes ./seams-checklist
seams new-generator page --reference page.html --out ../seams-page
```

It turns a reference output, a file written by hand exactly as the generator
should emit it, into an installable generator package (M018/S04, backlog K5,
`new_generator.py`). NAME is the generator and entry-point name: lowercase
letters, digits and underscores, starting with a letter. The reference's suffix
must be one `seams_gen.testing` has a marker comment syntax for: `.py`, `.yaml`,
`.yml` or `.html`. `--out` defaults to `./seams-<name>` and must not exist or be
an empty directory. It writes, the same bytes every time:

```text
seams-<name>/
  pyproject.toml                      # seams-<name>; [project.entry-points."seams.generators"] <name> = "seams_<name>:generator"
  seams_<name>/__init__.py            # the Generator: extract -> view model dict, render (no logic), sources
  seams_<name>/templates/<reference>  # the reference, verbatim
  tests/golden/<reference>            # the reference, every non-blank line marked [fixed]
  tests/test_<name>.py                # assert_matches_golden, assert_deterministic, check_output
```

The template uses the built-ins' `[[ ]]`/`[% %]` delimiters. The golden marks
each line in a trailing `# [fixed]` (`.py`, `.yaml`, `.yml`) or `{# [fixed] #}`
(`.html`) comment. The test runs on the model `SEAMS_MODEL` names, else on
`examples/chat-app/chat-app.trig` in the checkout `seams_gen` is imported from,
and passes as written: run it with `PYTHONPATH=seams-<name> python -m pytest
seams-<name>/tests`, or after installing the package next to the CLI. Each
written path is printed.

The reference is refused when it is not UTF-8, holds no non-blank line, does not
parse as its file type (`check_output`), or has a line that already carries a
producibility marker, holds a template delimiter (`[[`, `[%`, `[#`), or ends in
whitespace (a `\r` included), which `strip_markers` would drop. A line inside a
multi-line string or YAML block scalar is marked like any other; whether a
comment belongs there is the author's call. The generator guide's "Start from a
reference output" section is the method that follows.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | the package was written |
| 1 | a file could not be written |
| 2 | a refused name, reference or `--out` (not empty, or a file); nothing is written |

Errors print to stderr as `seams new-generator: <message>`. See
[docs/reference/seams-cli.md](../../docs/reference/seams-cli.md#seams-new-generator).

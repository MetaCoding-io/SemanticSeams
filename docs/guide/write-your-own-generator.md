# Write your own generator

A generator is any program that reads a model and writes something from it: code, a
config file, a report. The generators in `seams_gen` are one set of them. This guide
writes another, small enough to read in one go: a review checklist that lists, for every
process, what starts it, its tasks in flow order with the operations they call, the
decision tables they consult and the paths out of each gateway.

The generator reads the model only through the [seams library](/reference/seams-library).
It needs nothing else: no SpiffWorkflow, no FastAPI, no `seams_runtime`. Its complete
source is [below](#the-whole-generator), and the test suite runs that exact source against
`examples/chat-app` and `examples/expenses/chapter-08` on every CI run
(`tests/test_generator_guide.py`), so what you read here is what runs.

## Load

`seams.load` takes a TriG file or a directory. A directory loads every `*.trig` directly
inside it into one graph. With no argument, it reads the path from the `SEAMS_MODEL`
environment variable:

```python
import seams

model = seams.load("examples/chat-app/chat-app.trig")  # one TriG file
model = seams.load("examples/expenses/chapter-08")     # every *.trig in the directory
model = seams.load()                                    # the path in SEAMS_MODEL
```

Loading parses the TriG and nothing else. BPMN and DMN files the model names are read
on demand, when a view asks for them.

## Walk the views

The model has one view per layer: `model.interfaces`, `model.processes`,
`model.decisions`, `model.operations` and the rest (the
[reference](/reference/seams-library#views) lists them all). A layer can have many models,
so a view answers across all of them: chapter 8 of the expenses tutorial has two BPMN
models, and `model.processes` holds both.

Every collection is a `Many`, a tuple with a few helpers. When you need exactly one,
say so with `.only()`; it raises `seams.ResolutionError` otherwise, instead of quietly
taking the first:

```python
model = seams.load("examples/expenses/chapter-08")
[p.label for p in model.processes]  # ['Expense Approval', 'Expense Payout']
model.processes.only()              # ResolutionError: expected exactly one, found [...]

seams.load("examples/chat-app/chat-app.trig").processes.only().label
# 'Send Message Process'
```

Follow the seams from element to element. Events hang off components, and components
off pages, so the events that start a process are found by walking down from the pages.
`Event.triggers` is the `Process` the event starts, or None:

```python
for page in model.interfaces.pages():
    for component in page.components():
        for event in component.events():
            if event.triggers is not None:
                print(event.label, "starts", event.triggers.label)
# Submit Expense starts Expense Approval
```

A process can also start from a message: `Process.channel_starts` pairs each message
start event with the channel it listens on.

Every hop that the model should answer but does not raises `ResolutionError`, naming the
subject and predicate that are missing. Let it propagate, or catch it at the top and
report it; the generator below does the latter.

## Join BPMN and DMN

A process's tasks and gateways live in its BPMN file, not in the graph. `Process.tasks()`
and `Process.gateways()` read the XML and return `FlowNode`s in flow order, each joined to
the graph where the model lifts it:

- `kind` and `name`: the BPMN element type (`ServiceTask`, `UserTask`, ...) and its name.
- `invokes`: the `Operation` the task calls, or None. Its `path` is a `PathTemplate`, so
  the URL is `path.template`; the method is `method`.
- `completed_on`: for a user task, the component that holds its form.
- `decided_by`: the `Decision` a business-rule task consults, or None. `decision.table`
  parses the DMN file: `hit_policy`, `inputs`, `outputs` and `rules`, each rule with its
  `inputs` and `outputs` as entry text.
- `paths`: the sequence flows out of a gateway, each with a `name` and a `condition`.

```python
process = seams.load("examples/chat-app/chat-app.trig").processes.only()
for task in process.tasks():
    if task.decided_by is not None:
        for rule in task.decided_by.table.rules:
            print(rule.id, rule.inputs, "->", rule.outputs)
# rule_long ('"user"', '> 4000') -> ('"long-context-provider"',)
# rule_default ('-', '-') -> ('"default-provider"',)
```

## Write files deterministically

Run a generator twice on the same model and it must write the same bytes, or every
regeneration shows up as a diff. Two rules cover it:

- **Sort what has no order of its own.** Views return collections in a stable order, and
  `tasks()` follows the BPMN flow, but anything you gather yourself, such as the starters
  per process below, goes through `sorted` before it is written.
- **Write nothing that depends on when or where it ran.** No timestamps, no absolute
  paths, no hostnames. The checklist names the model by `model.path.name` only. If the
  output must say which model it came from, stamp it with `model.hash`, which changes only
  when the model or its BPMN and DMN files do.

## The whole generator

It reads the model path from its first argument, falling back to `SEAMS_MODEL`, and
prints a Markdown checklist to stdout. It imports only `seams` and the standard library.

```python
# checklist.py
"""Print a Markdown review checklist for every process in a seams model."""

import sys

import seams


def checklist(model: seams.Model) -> list[str]:
    # Which page events start which process. Events hang off components.
    starters: dict[str, list[str]] = {}
    for page in model.interfaces.pages():
        for component in page.components():
            for event in component.events():
                process = event.triggers  # a Process, or None
                if process is not None:
                    starters.setdefault(str(process.iri), []).append(
                        f"{event.label} on {page.label} / {component.label}"
                    )

    lines = [f"# Review checklist: {model.path.name}"]
    for process in sorted(model.processes, key=lambda p: p.label):
        lines += ["", f"## {process.label}", ""]
        for starter in sorted(starters.get(str(process.iri), [])):
            lines.append(f"- [ ] Started by {starter}")
        for start in process.channel_starts:
            lines.append(f"- [ ] Started by a message on {start.channel.label}")

        for task in process.tasks():  # flow order, read from the BPMN XML
            line = f"- [ ] {task.kind}: {task.name}"
            operation = task.invokes
            if operation is not None and operation.path is not None:
                line += f" -> {operation.method} {operation.path.template}"
            if task.completed_on is not None:
                line += f" (form: {task.completed_on.label})"
            lines.append(line)
            decision = task.decided_by
            if decision is not None:
                table = decision.table  # parsed from the DMN file
                lines.append(f"  - [ ] {decision.label}: {table.hit_policy}, {len(table.rules)} rules")
                for rule in table.rules:
                    lines.append(f"    - [ ] {rule.id}: {' | '.join(rule.inputs)} -> {' | '.join(rule.outputs)}")

        for gateway in process.gateways():
            for path in gateway.paths:
                lines.append(f"- [ ] {gateway.name} {path.name}: {path.condition or 'default'}")
    return lines


def main() -> int:
    try:
        model = seams.load(sys.argv[1]) if len(sys.argv) > 1 else seams.load()
        lines = checklist(model)
    except (ValueError, OSError) as err:  # no path given, or nothing to read there
        print(f"usage: checklist.py MODEL (or set SEAMS_MODEL): {err}", file=sys.stderr)
        return 2
    except seams.ResolutionError as err:
        print(f"model error: {err}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

On the chat app it prints:

```text
# Review checklist: chat-app.trig

## Send Message Process

- [ ] Started by Send Message on Chat Page / Compose Message
- [ ] ServiceTask: Persist User Message -> POST /conversations/{conversation}/messages
- [ ] BusinessRuleTask: Route to Provider
  - [ ] Route to Provider: FIRST, 2 rules
    - [ ] rule_long: "user" | > 4000 -> "long-context-provider"
    - [ ] rule_default: - | - -> "default-provider"
- [ ] ServiceTask: Invoke LLM -> POST /v1/chat/completions
- [ ] ServiceTask: Persist Assistant Response
```

## Run it

Save the block above as `checklist.py` at the repository root and run it on either
example:

```sh
uv run python checklist.py examples/chat-app/chat-app.trig
uv run python checklist.py examples/expenses/chapter-08
SEAMS_MODEL=examples/expenses/chapter-08 uv run python checklist.py
```

The expenses model gives two sections, Expense Approval and Expense Payout, with the
user tasks' forms, the routing and payout decision tables and the gateway paths.

## Register it with seams generate

Run by hand, the checklist is not in `seams.lock`, so `seams check` cannot tell you when
it is stale or hand-edited. To make `seams generate` run it like a built-in, wrap it in a
`Generator` object and register that object in the `seams.generators` entry-point group
([ADR-0016](/adr/0016-generator-protocol)).

A `Generator` has a `name`, a `version`, a one-line `help` and three functions:

- `extract(trig, out)` reads the model into a view model. Every check and computation
  goes here, and a missing fact raises an error here.
- `render(view)` turns that view model into `{relative file name: text}`. It does not
  read the model.
- `sources(trig, out)` gives, for each file `render` writes, the IRIs of the model
  elements it comes from. `seams.lock` records them, unless the generator has a
  `trace` hook (below), whose terms take their place.

It can also name `preconditions`: the full IRIs of the SHACL node shapes the model must
conform to before it runs, and a `trace(view)` function giving, per file `render`
writes, a `seams_gen.trace.Trace`: the template line and model IRIs behind each line
([ADR-0019](/adr/0019-generation-trace)). A Jinja2 generator gets one from
`seams_gen.trace.trace_template`, rendering its template a second time with a
`TracingEnvironment` built with the same options; strings read off view objects with an
`iri` field supply the terms: that IRI and, if the object has an `origins` tuple, the
other model elements it was derived from. `seams generate` writes each trace beside its file as
`<file>.trace.json`, locks it as an output of the generator, and records the trace's
terms as both files' `sources`. Leave `trace` out (it defaults to `None`) and the
generator writes no trace; `sources` is what `seams.lock` records.

Read only the model and its payloads if you can. If `extract` must read another file, name
it with `inputs(trig, out)`: the absolute paths of those files, found without raising
(the built-in `dockerfile` generator names the uv workspace's `pyproject.toml` files this
way). The viewer's write-back and `seams suggest` regenerate in a scratch copy and copy
only the model and these files into it, so an undeclared file is missing there
([ADR-0016](/adr/0016-generator-protocol#inputs-beyond-the-model-amendment-m027-s02)).

Put the checklist in its own package, here
`seams_checklist/__init__.py`, and import the `checklist` function from the module
above:

```python
# seams_checklist/__init__.py
from pathlib import Path

import seams
from seams_gen.protocol import Generator

from .checklist import checklist  # the function from the generator above


def extract(trig: Path, out: Path) -> tuple[str, ...]:
    return tuple(checklist(seams.load(trig)))


def render(lines: tuple[str, ...]) -> dict[str, str]:
    return {"checklist.md": "\n".join(lines) + "\n"}


def sources(trig: Path, out: Path) -> dict[str, tuple[str, ...]]:
    model = seams.load(trig)
    return {"checklist.md": tuple(sorted(str(p.iri) for p in model.processes))}


generator = Generator(
    name="checklist",
    version="0.1.0",
    help="a Markdown review checklist of every process",
    extract=extract,
    render=render,
    sources=sources,
    preconditions=("https://w3id.org/seams/shapes#ModelShape",),  # optional
)
```

Declare the entry point in the package's `pyproject.toml`. The entry-point name must be
the generator's `name`:

```toml
[project]
name = "seams-checklist"
version = "0.1.0"
dependencies = ["semanticseams"]

[project.entry-points."seams.generators"]
checklist = "seams_checklist:generator"
```

`seams_gen` is a workspace member of this repository and is not published, so install
the package into the repository's environment: add it as a workspace member, or run
`uv pip install -e path/to/seams-checklist`. Then name it in the app's `seams.toml`, like
any built-in:

```toml
[[generators]]
name = "checklist"
out = "generated/review"
```

`seams generate --project <app>` now writes `generated/review/checklist.md`. Its entry in
`seams.lock` names generator `checklist` and generator version `0.1.0`, and `seams check`
audits the file with the rest. `python -m seams_gen checklist MODEL --out DIR` runs it
on its own.

What goes wrong is reported before anything is written:

- A model that breaks a precondition makes `seams generate` exit 2. The error names the
  focus node, the shape and the generator.
- An entry point that does not load, loads something that is not a `Generator`, or uses
  a name that differs from `Generator.name` or repeats another generator's name raises
  `RegistryError`. It names the entry point and its distribution.
- A name in `seams.toml` that no installed distribution registers is a project error. It
  lists the known generators.

## Test it

`seams_gen.testing` is the test kit the built-in generators use, and it is public, so a
generator's own tests import it. It gives four checks:

- `assert_matches_golden(text, golden_path, model_hash)` compares the output with a
  golden file byte for byte. The golden is the expected output with a producibility
  marker in a trailing comment on every non-blank line (`# [graph: ...]` for a line that
  comes from model facts, `# [fixed]` for a constant one) and `sha256:<model-hash>`
  where the model's hash goes. The markers are stripped and the placeholder filled in
  before the comparison. Comment syntax is known for `.html` (`{# ... #}`), `.py` and
  `.yaml` (`# ...`). A mismatch names the golden file and the first differing line and
  shows a unified diff.
- `assert_deterministic(generator, model_path, out)` runs `generator.generate` twice, each
  time on a freshly loaded model, and names the first output file that differs.
- `check_output(path, text)` parses the text as its file type, picked by suffix: Python,
  YAML, JSON or a Jinja2 template (`.html`). An error is `<path>:<line>: <parse error>`.
- `assert_shapes_catch(extract, dataset, subject=..., predicate=..., focus=..., path=...)`
  checks a model fault from both sides (principle 5): `extract` must raise a
  `GeneratorError` on `subject` and `predicate`, and the SHACL shapes must report a
  violation on `focus`. A fault only the generator catches is a gap in the shapes: the
  error says `no shape violation on <focus>` and lists the results that were found.
  `shape_violations(dataset, shapes, ontology)` returns those results directly.

`tests/test_generator_kit_third_party.py` tests a YAML variant of the checklist this way,
importing only `seams`, `seams_gen.protocol` and `seams_gen.testing`. Its golden is
`tests/fixtures/generator_kit/checklist.yaml`:

```yaml
model: "chat-app.trig"  # [fixed]
model_hash: "sha256:<model-hash>"  # [fixed]
processes:  # [fixed]
  - process: "Send Message Process"  # [graph: :send_message_process proc:Process rdfs:label]
    bpmn: "https://example.org/chat/chat_bpmn"  # [graph: :send_message_process seam:detailedBy :chat_bpmn]
```

and the tests are a few lines each:

```python
import seams
from rdflib import Dataset
from seams_gen.testing import assert_deterministic, assert_matches_golden, assert_shapes_catch, check_output


def test_output_matches_golden(tmp_path):
    files = checklist.generate(CHAT_TRIG, tmp_path)
    assert_matches_golden(files["checklist.yaml"], GOLDEN, seams.load(CHAT_TRIG).hash)


def test_output_is_deterministic(tmp_path):
    assert_deterministic(checklist, CHAT_TRIG, tmp_path)


def test_output_is_valid_yaml(tmp_path):
    for name, text in checklist.generate(CHAT_TRIG, tmp_path).items():
        check_output(name, text)


def test_process_without_bpmn_model_is_a_shape_violation():
    ds = Dataset(default_union=True)
    ds.parse(CHAT_TRIG, format="trig")
    for graph in ds.graphs():
        graph.remove((CHAT.send_message_process, SEAM.detailedBy, CHAT.chat_bpmn))
    assert_shapes_catch(
        extract_checklist,  # takes a loaded model, raises GeneratorError
        ds,
        subject=CHAT.send_message_process,
        predicate=SEAM.detailedBy,
        focus=CHAT.send_message_process,
        path=SEAM.detailedBy,
        model_path=CHAT_TRIG,  # so the model's relative file names still resolve
    )
```

`assert_shapes_catch` calls `extract` with the faulty model loaded as a seams model, so
give it the part of your generator that reads the model, not `Generator.extract`, which
takes a path. The shapes default to the repository's `ontology/shapes/seam-shapes.ttl`
and `ontology/*.ttl`; pass `shapes=` and `ontology=` to check your own.

## Preview a broken model with --lenient

While a model is still being written, a broken precondition stops every generator.
`seams generate --lenient` writes what it can instead and flags the result
([ADR-0016](/adr/0016-generator-protocol), D057):

- A precondition the model breaks becomes a fault, and the generator still runs.
- A generator whose `extract` or `render` raises `GeneratorError` writes nothing and adds
  a fault. The files it wrote last time are kept and stay in `seams.lock`.

Each fault goes to stderr as one line, followed by a summary, and the command exits 0:

```text
seams generate: fault <generator>: <focus>: <shape>: <message>
seams generate: N fault(s); output is flagged
```

For a raised `GeneratorError`, `<shape>` is the error's predicate and `<focus>`
its subject, so raise errors that name the model element and the fact that is missing.

`seams.lock` keeps the faults in a sorted `faults` list. While it has any, `seams check`
reports a `flagged` finding and exits 1, so flagged output cannot pass CI. Fix the model
and run `seams generate` again without `--lenient`: a clean run drops the `faults` key.

## Start from a reference output

The checklist above was written code first. The other way round is often quicker: write
by hand one file exactly as the generator should emit it for a model you know, then turn
it into a generator a line at a time, with a golden test that passes at every step. Start
with a reference output for the chat-app model, `processes.yaml`:

```yaml
title: "Process review"
processes:
  - "Send Message Process"
```

`seams new-generator` turns it into a generator package
([the seams CLI](/reference/seams-cli#seams-new-generator)):

```sh
seams new-generator processes --reference processes.yaml
```

It writes `./seams-processes` (`--out` picks another directory, which must not exist or be
empty) and prints each file it wrote:

```text
seams-processes/pyproject.toml
seams-processes/seams_processes/__init__.py
seams-processes/seams_processes/templates/processes.yaml
seams-processes/tests/golden/processes.yaml
seams-processes/tests/test_processes.py
```

- `pyproject.toml` registers `processes = "seams_processes:generator"` in the
  `seams.generators` entry-point group, so once installed `seams generate` runs it like
  [any other](#register-it-with-seams-generate).
- `seams_processes/__init__.py` is the `Generator`. `extract` loads the model and returns
  the view model, a dict that holds only `model_hash` so far. `render` substitutes the view
  model into the template with the `[[ ]]` and `[% %]` delimiters the built-ins use.
- `seams_processes/templates/processes.yaml` is the reference, verbatim.
- `tests/golden/processes.yaml` is the reference with `# [fixed]` on every non-blank line:
  every line is still a constant of the template.
- `tests/test_processes.py` runs the [test kit](#test-it) on the model `SEAMS_MODEL` names,
  else `examples/chat-app/chat-app.trig` beside `seams_gen`.

The test passes as generated. Install the package (`pip install -e seams-processes`) and run
`python -m pytest seams-processes/tests`. The scaffold refuses a reference it could not
make a passing test from: one that does not parse as its file type, or with a line that
already carries a marker, holds `[[`, `[%` or `[#`, or ends in whitespace. A line inside a
multi-line string or a YAML block scalar gets its marker comment like any other, so leave
such lines out of the reference or move the marker by hand.

Then repeat one loop until no line the model knows is still `[fixed]`:

1. Pick a literal in the template that the model holds, here `Send Message Process`.
2. Add the fact to `extract`, formatted as the template will output it.
3. Replace the literal in the template with the view-model field.
4. Change the golden line's marker from `[fixed]` to `[graph: ...]`, naming the triple
   the line comes from.
5. Run the test again.

After one pass, `extract` reads every process and quotes its label:

```python
def extract(trig: Path, out: Path) -> dict:
    """The view model: every value the template outputs, read from the model at ``trig``."""
    model = seams.load(trig)
    return {
        "model_hash": model.hash,
        "processes": [json.dumps(p.label) for p in sorted(model.processes, key=lambda p: p.label)],
    }
```

(with `import json` beside the other imports), the template loops over the prepared
values:

```yaml
title: "Process review"
processes:
[% for label in processes %]
  - [[ label ]]
[% endfor %]
```

and the golden says where the line comes from:

```yaml
title: "Process review"  # [fixed]
processes:  # [fixed]
  - "Send Message Process"  # [graph: :send_message_process proc:Process rdfs:label]
```

The golden still holds the chat-app output, and the test passes on it. Running it with
`SEAMS_MODEL=examples/expenses/chapter-08` fails with a diff that names the expenses
processes: the template no longer holds a process name. For the model hash, write
`[[ model_hash ]]` in the template and the `sha256:<model-hash>` placeholder in the golden.
Once the template reads model elements, return their IRIs from `sources` too, so
`seams.lock` records where each output came from.

Keep the template free of logic. The quoting, the sort and the choice of processes
happen in `extract`. The template only outputs prepared values and loops over them:
no filters, no string concatenation, no comparisons or compound conditions
([templates hold text, not logic](/project/principles#templates-hold-text-not-logic)).
A value computed in the template is a value the view model, and so a trace of where the
output came from, cannot see, and a literal left in it restates a model fact
([principle 1](/project/principles#_1-the-model-is-the-source-of-truth)).

## Draft it with an LLM (optional)

The loop above is mechanical enough for an LLM to draft and strict enough for the golden
test to judge. `seams draft-generator` takes the same name and reference as
`seams new-generator` and asks an LLM command for the extract step, the template and the
golden in one go ([the seams CLI](/reference/seams-cli#seams-draft-generator),
[ADR-0029](/adr/0029-llm-drafted-generators)):

```sh
seams draft-generator processes --reference processes.yaml --provider "my-llm"
```

The provider is the command `seams propose` uses (`[propose] provider` in `seams.toml`,
or `--provider`): it reads the prompt on stdin and prints one JSON object with the keys
`extract`, `template` and `golden`. The prompt holds the reference, the model's names
(each labelled IRI and its label) and the scaffolded package module, as quoted data.

The command writes `./seams-processes` only when the draft keeps the rules of this
section: the template holds no logic and restates no model label found in the
reference, and the scaffold's four tests pass in a scratch copy, run on the project's
model. Otherwise it writes nothing and names what failed: the key, the template line and
label, or the failed tests. It prints the prompt's hash, `cache hit` or `cache miss`,
and each written file. An accepted answer is cached under `.seams/generator-drafts/`,
so asking again with the same reference, model and provider calls no LLM.

What it writes is the same kind of package as `seams new-generator`'s: it runs without
an LLM and is yours from then on. Read the extract step and the golden markers as you
would a colleague's, add the IRIs the template reads to `sources`, and run the test on a
second model before you trust it.

## Where to go next

- [The seams library](/reference/seams-library): every view, property and error.
- The generators in [`seams_gen`](../../seams_gen/README.md) are larger worked examples
  of the same pattern: `seams_gen/htmx.py` writes templates from `model.interfaces`,
  and `seams_gen/_views.py` shows how they turn a `ResolutionError` into their own error.
  `seams_gen/ifmledit.py` (`python -m seams_gen ifmledit`) is a small one: it exports the
  IFML layer as IFMLEdit.org JSON and lists the terms the target format cannot hold in a
  module constant, `UNMAPPED`, instead of guessing.
- A generator that writes into owned code must never overwrite it. `seams_gen/stubs.py`
  writes a handler stub only where the file is absent and reports what it would have
  changed instead ([ADR-0012](/adr/0012-operation-implementation)'s regeneration rule).

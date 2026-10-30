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

## Where to go next

- [The seams library](/reference/seams-library): every view, property and error.
- The generators in [`seams_gen`](../../seams_gen/README.md) are larger worked examples
  of the same pattern: `seams_gen/htmx.py` writes templates from `model.interfaces`,
  and `seams_gen/_views.py` shows how they turn a `ResolutionError` into their own error.

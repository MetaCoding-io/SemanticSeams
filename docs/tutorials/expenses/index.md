# Build an expense approval app

This tutorial builds a whole application from an empty file, one layer per chapter.
Employees submit expenses, managers approve them and finance pays them out. Each
chapter adds one model to a single TriG file, `expenses.trig`, and ends with something
you can see in the viewer or run in a browser.

If you want to see the pipeline end to end first, the
[quick start](/tutorial) runs the finished chat app in about ten minutes. This tutorial
is the slower track: you write the model yourself, and by the end you know why each
triple is there.

## The chapters

| # | Chapter | You write | You see or run |
|---|---|---|---|
| 1 | [An empty file and an architecture](./01-architecture) | One system and two containers (C4) | The architecture view, with the health badge green |
| 2 | [The data](./02-data) | An `ExpenseShape` in SHACL, then a deliberate mistake | The badge turning red and naming the element, then green again |
| 3 | [The screens](./03-screens) | An IFML page with a form and a list, and the operations it calls | A generated app whose form rejects invalid input and stores valid input |
| 4 | [The process](./04-process) | A BPMN process triggered from the form, with an approval user task | The submission running through SpiffWorkflow, approved from the `/tasks` inbox |
| 5 | [The rules](./05-rules) | A DMN table that routes approvals by amount, and a gateway with one path per route | Different paths for different amounts, with no code change |
| 6 | [The lifecycle](./06-lifecycle) | A statechart: draft, submitted, approved or rejected, paid; the tasks that fire each transition; a block guarded by state | Each path ending in its state, a block shown only while submitted, an illegal transition refused |
| 7 | [People and permissions](./07-permissions) | Employee, manager and finance roles, a policy on the submit operation and on each user task, and a payment task | A 403 for the wrong role, an expense ending paid, and the viewer naming the screens an employee can use that write a payment |
| 8 | Growing up (coming) | A payout process, a finance console, a worker, `docker compose up` | The whole system |

Chapters 1 to 7 are written. Chapter 8 comes next: it makes payout asynchronous, adds a
finance console and runs the whole system with `docker compose up`.

## Prerequisites

- A clone of the repository with the Python dependencies installed, as in
  [Getting started](/guide/getting-started):

  ```sh
  pip install -r requirements-dev.txt -r viewer/requirements.txt
  ```

- A text editor. Every command runs from the repository root.
- Some familiarity with Turtle helps but is not required. Each chapter explains the
  triples it adds. [Authoring a model](/guide/authoring-a-model) is the reference for the
  conventions.

Nothing in this tutorial needs Docker, an API key or a network service until chapter 8.

## How checkpoints work

You grow one `expenses.trig` from chapter to chapter. The repository keeps a copy of the
file as it stands at the end of each chapter, under
[`examples/expenses/`](../../../examples/expenses/README.md):

```
examples/expenses/chapter-01/expenses.trig
examples/expenses/chapter-02/expenses.trig
examples/expenses/chapter-03/expenses.trig
examples/expenses/chapter-04/expenses.trig
examples/expenses/chapter-05/expenses.trig
examples/expenses/chapter-06/expenses.trig
examples/expenses/chapter-07/expenses.trig
```

Each checkpoint is the previous one plus that chapter's additions, so a `diff` between
two checkpoints shows exactly what a chapter adds:

```sh
diff examples/expenses/chapter-01/expenses.trig examples/expenses/chapter-02/expenses.trig
```

If your file stops working, compare it with the checkpoint for the chapter you are on,
or copy the checkpoint and carry on from there.

The checkpoints cannot drift from the tutorial. CI parses each one, validates it against
the [seam shapes](/reference/shapes) and opens it in the viewer
(`tests/test_expense_checkpoints.py`). It also runs chapter 3's generated app
(`tests/test_expense_chapter3_app.py`) and the process chapters' generated apps from
chapter 4 on (`tests/test_expense_process_app.py`), checks chapter 6's lifecycle guard
(`tests/test_expense_lifecycle.py`) and chapter 7's roles (`tests/test_expense_roles.py`), and checks that every model excerpt on these pages
appears verbatim in its chapter's checkpoint (`tests/test_expense_tutorial_doc.py`).

Start with [chapter 1](./01-architecture).

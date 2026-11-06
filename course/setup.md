# Before the first lesson

The labs run from a clone of the repository. Set it up once, before lesson 1, so the
first lab is a walk through a running viewer rather than an install.

## Install

Follow [Getting started](../docs/guide/getting-started.md) in the docs. In short: install
[uv](https://docs.astral.sh/uv/), clone the repository, sync the workspace from the
committed lock file and run the test suite once.

```sh
git clone https://github.com/MetaCoding-io/SemanticSeams.git
cd SemanticSeams
uv sync --all-packages
source .venv/bin/activate
pytest -q
```

A green suite means every Turtle and TriG file parses, every example passes the SHACL
shapes, and every canned query returns the rows it should. If something fails here, fix
it before the course: the labs assume this baseline.

## Start the viewer

```sh
python3 -m uvicorn viewer.app:app --port 8000
```

Open <http://localhost:8000>. You should see the chat app's architecture view with a green
health badge. Lesson 1's lab starts here.

## What each module needs

| Module | Needs | Notes |
|---|---|---|
| A (lessons 1 to 4) | The clone, the viewer | Lesson 3 regenerates the chat app with `seams generate`; nothing is run in Docker. |
| B (lessons 5 to 8) | A text editor | Chapters 1 to 7 of the expense tutorial run in process. No Docker, no network service. |
| C (lessons 9 to 11) | Docker from lesson 11 | Chapter 8 starts the stack with `docker compose`. Lesson 9's language-model step is optional and needs a provider command; the hand-written path needs nothing. |
| D (lesson 12, capstone) | Depends on the capstone you choose | The generator capstone needs only Python. The domain capstone ends in `docker compose up`. |

## Keep a working file

The expense tutorial grows one file, `expenses.trig`, over ten chapters, and the course's
labs follow it. Keep your copy outside `examples/` (for example `work/expenses.trig`) so
that `git status` stays clean and you can diff your file against the chapter checkpoints in
[`examples/expenses/`](../examples/expenses/). [How checkpoints
work](../docs/tutorials/expenses/index.md#how-checkpoints-work) explains the diff.

## If you are teaching this

The [instructor page](instructor.md) has timings, which labs need Docker or a network,
and what to do when a lab and the repository disagree.

# Expense approval tutorial checkpoints

This directory holds the model at the end of each chapter of the build-along
expense approval tutorial ([docs/tutorials/expenses/](../../docs/tutorials/expenses/)).
If you get lost, copy the checkpoint for the chapter you are on and carry on
from there.

## Layout

Each chapter has its own directory with one file of the same name:

```
examples/expenses/
  chapter-01/expenses.trig   architecture: the system and its two containers (C4)
  chapter-02/expenses.trig   data: chapter 1 plus the ExpenseShape shape graph
```

Every checkpoint is a cumulative copy of the one before it, so the diff between
two chapters is exactly what that chapter adds:

```
diff examples/expenses/chapter-01/expenses.trig examples/expenses/chapter-02/expenses.trig
```

To browse a checkpoint, point the viewer at it with `SEAMS_MODEL`:

```
SEAMS_MODEL=examples/expenses/chapter-02/expenses.trig python3 -m uvicorn viewer.app:app --port 8000
```

## Tested in CI

`tests/test_expense_checkpoints.py` checks every `chapter-*/expenses.trig` it
finds: the file parses, conforms to `ontology/shapes/seam-shapes.ttl`, keeps
seam predicates in the seams graph, keeps every named graph of the previous
chapter, and opens in the viewer at its C4 model with no SHACL violations. It
also replays chapter 2's deliberate mistake (deleting
`:expense_data seam:notation seam:ShapeGraph .`) and checks the validator names
`:expense_data`. A new chapter directory is picked up without editing the test.

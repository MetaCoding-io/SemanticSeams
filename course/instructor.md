# For instructors

Timings, prerequisites and the rules of the road for running this course as a two-day
workshop or a six-session evening course. The course is also designed to be taken alone;
nothing here is needed for that.

## Timings

Each lesson is planned at 60 to 90 minutes: reading or lecture, a short look at the named
repository files, then the lab. The labs are the project's tutorial chapters, and the
checkpoint files mean a participant who falls behind can start the next lab from the
previous chapter's checkpoint rather than their own file.

| Lesson | Story | Lab | Lab needs | Notes |
|---|---|---|---|---|
| 1 Drawing software | 35 min | 25 min | The viewer | Nothing is written. Good opener. |
| 2 Saying what, not how | 35 min | 30 min | The clone, pytest | Three short reading exercises. |
| 3 The program that writes the program | 35 min | 35 min | `seams generate` | The `hand-edited` moment lands well live. |
| 4 Why it kept stalling | 45 min | 30 min | Pen and paper | Discussion lesson. Collect the written exercises; they return in lesson 12. |
| 5 One graph, many views | 25 min | 50 min | Text editor | Chapters 1 and 2. The first TriG anyone writes; budget for syntax errors. |
| 6 Shapes before generation | 25 min | 50 min | In-process run | Chapter 3. |
| 7 Interpret behaviour, generate structure | 25 min | 90 min | In-process run | Chapters 4 to 7. The long one; split across a break, or assign 6 and 7 as homework. |
| 8 Questions no single tool can answer | 25 min | 50 min | pytest, the docs build | Writing a question takes longer than it looks; have a candidate ready. |
| 9 Code the templates cannot write | 30 min | 45 min | Optional: a provider command | Chapter 9. The LLM step is optional; the hand-written path is the lesson. |
| 10 Getting changes back into the model | 30 min | 45 min | The viewer in edit mode | Chat app, not the expense file. Refusals are the teaching moments. |
| 11 Same model, same bytes | 30 min | 60 min | Docker | Chapters 8 and 10. Pull the images before the session. |
| 12 What is still open | 30 min | 45 min | Pen and paper | Pair the exercise with lesson 4's. |

Two-day format: lessons 1 to 6 on day one, 7 to 12 on day two, with chapters 6 and 7 as
overnight homework. Six-evening format: two lessons per evening, in order.

## Prerequisites by lesson

- **A laptop set up as in [Before the first lesson](setup.md)** for everyone, before
  lesson 1. Ask participants to confirm `pytest -q` is green and the viewer opens. An
  install problem discovered in lesson 5 costs the room half a lab.
- **Docker** from lesson 11. Have participants pull the images the chapter 8 compose file
  names before the session; a room on one network pulling at once is slow.
- **A language-model provider command** is optional and only for lessons 9 and 10. The
  project's `seams propose`, `seams suggest` and `seams draft-generator` take any command
  that reads a prompt on standard input and writes a draft to standard output, so a local
  model works. The chat app's own runtime does not need a key: its gateway falls back to a
  deterministic stub when none is set.
- **No prior knowledge of RDF, BPMN or SHACL** is assumed. Participants who know them will
  move faster in module B and should be pointed at the capstone early.

## Rules of the road

**The repository is right.** The course is written against the project at a point in time
and the project moves. When a lab and the repository disagree, the repository wins, and the
lesson needs a pull request; the [backlog](../docs/backlog.md) records what changed. Check
the tutorial chapters against your checkout before each session: their excerpts are tested
against the checkpoint files, so if the chapter builds, the lab works.

**The scorecard is marked with evidence, not with enthusiasm.** A row is closed when a
participant can point at a file, a decision record or a test. Push back on "it feels
solved". The project's own research notes model the tone.

**Refusals are the lesson.** In lessons 6, 9 and 10 the most instructive moments are when
the tool says no: a 422 that names a path, an acceptance test that names a drift, a write-back
refused with three candidates. Slow down there.

**Do not hand-edit generated files to make a lab work.** Continuous integration will catch
it, and the point of lesson 3 is that it does.

## Materials

Everything is in the repository. The course pages are in `course/`, the tutorial chapters
in `docs/tutorials/expenses/`, the checkpoints in `examples/expenses/`, and the viewer's
screenshots, which make good slides, in `docs/guide/img/` and `site/img/`. The site builds
with `npm run build` in `course/`; a link to a repository file that does not exist fails the
build, so a renamed file is caught before a session.

## Feedback

Course corrections go through pull requests against `course/`. Project gaps found during
a lab go to the backlog in its format. Both are welcome.

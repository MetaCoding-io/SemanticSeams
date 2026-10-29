# Research note: managing and deploying generated artifacts

*Status: proposal, 2026-10-29. Its proposed steps are backlog items A1 to A9 in the
[backlog](../backlog.md) ("Artifact management and deployment"), not yet scheduled. Companion
to a separately discussed SDK for generation; this note covers everything around the SDK
rather than the SDK itself. Written against `main` at `dd56985`.*

## The question

Generation works for the chat app: three generators write the htmx templates, the
FastAPI route module and the compose file, and `docker compose up` runs the result. What
does a builder need, besides a library for generating, to manage those files over time
and to get them deployed?

## Short answer

**The generators exist; the workflow around them does not.** A builder can generate
files, but has no record of what was generated, no reusable check that the files are
current, no way to describe more than one environment, no real images to deploy, and no
way to confirm that what runs matches the model.

**The foundation is better than it looks.** The repository already has an end-to-end
provenance chain for the model. Every generated file is stamped with the model hash, the
compose file passes that hash to the container, the runtime refuses to start against a
different model, and `/healthz` reports the hash it loaded. Most of the proposals below
extend that chain rather than invent something new.

## 1. What the repository shows is missing

| Gap | Evidence today |
|---|---|
| No record of what was generated | Users regenerate with three hand-typed commands. The generated-code README says "if a generator stops writing a file, delete the committed copy", by hand |
| The freshness check only works here | The CI job that regenerates and fails on `git diff` names `examples/chat-app/` paths directly. A user gets nothing reusable |
| Only production is modelled | The chat-app model has one `arch:Environment`, `:prod`. Everything a laptop run needs lives in the hand-written `compose.override.yaml` |
| The images do not exist | The generated compose file points at `ghcr.io/example/chat-api` and friends. The override builds local images instead, and `docker/runtime.Dockerfile` copies chat-app paths |
| Only the model is versioned | The hash covers the model files. Neither `seams_gen` nor `seams_runtime` has a version, so nothing records which generator wrote a file or which runtime is running it |
| The model and the running app disagree | The model declares a Postgres message store that the runtime never uses ([U9](2026-10-29-runtime-storage.md)), and three replicas where only one can work |

## 2. Proposals

Ordered by value to the solo-operator persona. The first three make the generators
usable outside this repository; the next three make deployment work end to end.

### 2.1 A project file and a CLI

One file per project names the model, the generators to run, their output paths and the
environments. `seams generate` runs every generator from it, and `seams check` validates
the model against the shapes and confirms the outputs are current. It replaces the three
hand-typed commands, and it covers backlog item E2 (configurable model path), which today
is spread across the runtime, the compose file, the Dockerfile and the viewer.

### 2.2 A lockfile of generated files

For every output, record the model hash, the generator and its version, the file's own
hash, and the model elements the file was generated from. That gives:

- **orphan cleanup:** a file the lockfile lists but no generator writes any more is
  deleted automatically;
- **hand-edit detection:** a generated file whose hash no longer matches was edited, and
  CI can refuse it;
- **provenance in the viewer:** clicking a model element can list the files it produced.

The lockfile is also where a runtime version belongs, once `seams_runtime` is published
as a versioned package that generated apps pin, like any framework.

### 2.3 A reusable CI action and pre-commit hook

Package the checks this repository already runs, so a user gets them in one line:
validate the model against the shapes, regenerate and fail on any difference, and run
canned queries as gates. A gate is a query that must return no rows, for example "a
screen that writes personal data without a policy". The tutorial end-to-end job is a
second, slower template users could adopt.

### 2.4 Environments from the model

Model development and production as `arch:Environment`s, with the facts that differ
between them (build from source or pull an image, a development user, seed data, one
replica) attached to the environment. The compose generator then writes one file per
environment, and the hand-written override disappears. The override is the clearest
evidence of the gap: everything in it is a fact the model could state.

### 2.5 Image build and publish

Generate the image builds and a publish workflow for each container that runs generated
code, tagged with the model hash or a release version. The `deploy:Artifact` references
in the model then point at images that exist. The runtime Dockerfile's hard-coded
chat-app paths become generator output.

### 2.6 A deploy check: `seams status`

For each container in an environment, read `/healthz` and compare the model hash it
reports with the current model, then report what is behind, ahead or unreachable. This is
the cheapest useful step toward the drift detection the outline plans, and it needs no
new infrastructure: the runtime already reports the hash.

### 2.7 Change plans and release notes from model diffs

Turn a model change into the change a person cares about: "adds a screen, makes a field
on Expense required, breaks the response contract of one operation". The same output
serves pull request review, a generated changelog and a pre-deploy plan. It reuses the
shape diff proposed as U8 in the [UML coverage note](2026-10-29-uml-coverage-and-gaps.md).

### 2.8 A secrets and configuration checklist

List every `deploy:secretRef`, `deploy:secretName` and configuration key each environment
needs, check that each exists in the target platform without reading its value, and
generate an example `.env` file for local runs. The model already holds every reference;
only the tooling is missing.

### 2.9 Post-deploy smoke tests

Generate smoke tests from the model: every operation answers on its declared path, and
every response validates against its `seam:returnsShape`. Run them after a deploy and in
the tutorial end-to-end job.

### 2.10 Later

- **Drift detection:** record what is actually deployed as an as-deployed named graph and
  diff it against the model with SPARQL, as the outline plans. `seams status` (2.6) is its
  first slice.
- **More targets:** Kubernetes manifests and Ansible inventories, both named in the
  outline, from the same `deploy:` facts.
- **Data operations:** backups for every `deploy:Volume`, managed seed data, and
  migrations once U8 can classify a shape change.
- **Preview environments:** one per pull request, with the viewer link and the model diff
  posted on the pull request.
- **Live viewer overlay:** which model version runs where, and whether it is healthy. This
  is the "living map" the product brief promises.

## 3. Proposed next steps

Tracked as A1 to A9 in the backlog, not yet scheduled. Sizes use the backlog's scale.

| # | Item | Size | Depends on | Earns |
|---|---|---|---|---|
| A1 | **Project file and `seams` CLI** with `generate` and `check` | M | E2 | Generation outside this repository |
| A2 | **Lockfile of generated files**, with orphan cleanup and hand-edit detection | S | A1 | A record of what came from where |
| A3 | **Reusable CI action and pre-commit hook** | S | A1 | The repository's own checks, for users |
| A4 | **Environments from the model**, one compose file per environment | M | an ADR on environment-specific facts | No hand-written override |
| A5 | **Image build and publish** for containers that run generated code | M | A4 | Image references that exist |
| A6 | **`seams status`**: compare running model hashes with the model | S | A1 | The first slice of drift detection |
| A7 | **Change plans and release notes** from model diffs | M | U8 | Reviewable model changes |
| A8 | **Secrets and configuration checklist** | S | A4 | No deploy failing on a missing secret |
| A9 | **Generated smoke tests** from operations and their shapes | S | none | A deploy that checks itself |

A1 to A3 belong together. A4 to A6 make deployment work end to end. U9 should land before
A4, because environment-specific storage is one of the facts A4 has to model.

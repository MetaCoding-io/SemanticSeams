# ADR-0015: Environments — Development and Production Are Facts in the Model

**Status:** Accepted

**Date:** 2026-10-31

**Source:** milestone M016/S01; backlog A4 (and A5, A8, A10); research:
[managing and deploying generated artifacts](../research/2026-10-29-artifact-management.md)
sections 2.4, 2.5 and 2.8

## Context

The compose generator (`seams_gen/compose.py`) writes one prod-shaped file per model:
images are pulled from `ghcr.io/example/...`, secrets are external swarm secrets, and the
chat app's `:chat_api` runs `deploy:replicas 3`. Nothing in that file runs on a laptop,
so three hand-written overrides fill the gap:

- `compose.override.yaml` at the repository root, for the chat app;
- `examples/expenses/chapter-08/compose.override.yaml` and
  `examples/expenses/chapter-09/compose.override.yaml`, for the expenses tutorial. The
  two differ only in the chapter number in comments and in `SEAMS_APP_DIR`.

Each override is a list of facts the model does not state. That breaks principle 1 (the
model is the source of truth) and principle 8 (generated and owned code never mix: the
override is owned code that patches generated output). The model already has the class
it needs: `arch:Environment`. The chat app declares one, `:prod`, which `arch:contains`
the deployment nodes `web01`, `app01` and `db01`, and a placement policy names it with
`deploy:targetEnvironment`. There is no development environment, and no way to say that a
fact holds in one environment only.

[ADR-0011](./0011-storage-resolution) resolves storage from three facts: `seam:storedIn`,
`deploy:storeKind` and a `deploy:connectsTo` binding. It left replicas out of scope
(backlog A10). Both questions come back here: the store a binding reaches must not change
per environment, but how the binding gets its value does, and the replica count the model
declares is one that cannot work yet.

### Inventory of the overrides

Every line group in the three override files, and where it goes. "Fact" means a model
fact (shared, or environment-scoped through the override rule below). "Generator" means a
rule in `seams_gen/compose.py` that derives the line from facts the model already states.
"Correction" means a shared fact the model gets wrong today in every environment.

| Override lines | Files | Goes to | How |
|---|---|---|---|
| `image: seams/...:local`, `build: {context, dockerfile}`, `pull_policy: build` | all three | **Fact**, development | The development override replaces `deploy:artifact` with an artifact that has a `deploy:build` (`deploy:context`, `deploy:dockerfile`). The generator renders an artifact with a build as `build:` plus `pull_policy: build`, and one without as a pulled `image:` |
| `build.args`: `SEAMS_APP_DIR`, `SEAMS_ROUTES_FILE` | all three | **Generator** | For the serving container only: the app directory is the model file's directory relative to the build context, and the routes file is the module the fastapi generator writes for that container. Both are already known to the generator. S03 may remove them by generating the build file |
| `SEAMS_DEV_USER: builder` | root | **Fact**, development | A development `deploy:binding` with `deploy:key "SEAMS_DEV_USER"` and `deploy:value "builder"`. Production has no such binding, so it falls back to the header authenticator. The expenses chapters have none: their caller sends the headers |
| `SEAMS_SEED: /app/seed.json` | root | **Fact**, development | A development `deploy:binding` with `deploy:key "SEAMS_SEED"`. Seed data is a development fact; production starts empty |
| `deploy.replicas: 1` | all three | **Generator** (replica caveat) | The shared `deploy:replicas` stays the design intent. The generator caps the serving container at one replica until A10, in every environment, and says so in a comment |
| `depends_on: !override` with `condition: service_healthy` | all three | **Generator** | A `deploy:dependsOn` target that has a `deploy:healthcheck` renders `condition: service_healthy`; otherwise `service_started` |
| `depends_on` adds `llm_gateway` to `chat_api` | root | **Correction**, shared | `:chat_api` gains `deploy:dependsOn :llm_gateway`; `arch:dependsOn` already says it |
| `healthcheck` on the serving container (`/healthz`, python probe) | all three | **Generator** | The runtime always serves `/healthz` (ADR-0011's observability contract), so the serving container's probe is a runtime rule, not a model fact |
| `healthcheck` on `llm_gateway` and `employee_portal`; `timeout`, `retries`, `start_period` | all three | **Correction**, shared, and **Generator** | Each container gets a shared `deploy:healthcheck` with its `deploy:probe`. The `5s`/`12`/`5s` timings become fixed generator defaults beside the modelled `deploy:interval` |
| `chat_ui` / `employee_portal`: `image: caddy:2-alpine`, `command: caddy reverse-proxy ...` | all three | **Correction**, shared, and **Generator** | The front-end containers have no image of their own in any environment: the serving container serves the pages. The shared artifact becomes `caddy` `2-alpine`, and a new `deploy:proxies` fact names the container proxied. The generator renders the command from that container's local name and its single `deploy:port`, as it does for `deploy:serviceOf` URLs |
| `secrets: <key>: !override file: ...` (external in production, a file locally) | all three | **Fact**, development | The development override restates the binding with the same `deploy:key` and a `deploy:secretFile` path instead of `deploy:secretRef`/`deploy:secretName`. The generator renders `file: ${<KEY>_FILE:-<path>}`, so a host can point elsewhere, as `LLM_API_KEY_FILE` does today |
| `llm_api_key` secret and `LLM_API_KEY_FILE` on `llm_gateway` | root | **Correction**, shared | The runtime never reads `LLM_API_KEY`; the gateway does. The `LLM_API_KEY` binding moves from `:chat_api` to `:llm_gateway` |
| `POSTGRES_PASSWORD: seams-dev` | all three | **Fact**, development; **Correction**, production | A development `deploy:value` binding. Production gains a shared `POSTGRES_PASSWORD` secret binding, which the generator already renders as `POSTGRES_PASSWORD_FILE` (honoured by the `postgres` image) |
| `POSTGRES_DB: chat` / `expenses` | all three | **Nothing** | Already a shared binding; the override only repeated it |
| `LLM_GATEWAY_STUB`, `LLM_MODEL_OVERRIDE` (host knobs, empty default) | root | **Fact**, development | Development bindings with an empty `deploy:value` |
| `UPSTREAM_BASE_URL: ${UPSTREAM_BASE_URL:-https://...}` | root | **Generator** | Already a shared `deploy:value`. In development the generator renders every `deploy:value` binding as `${KEY:-value}`, so a host can override it; production renders the literal |
| `name: seams-expenses` | chapters | **Generator** | The compose project name is the `arch:System`'s local name, lower-cased, so two apps never share volumes |
| Placement constraints ("swarm-only and ignored here") | all three (comments) | **Generator** | A `seam:deployedTo` node renders a placement constraint only in the environment that `arch:contains` that node. Development contains no nodes, so it gets none |

Nothing in the three files is left without a home.

## Decision

### Two environments

Each architecture model declares its environments as `arch:Environment` instances in its
model graph. Applications in this repository declare two: `:development` and
`:production`. The chat app's `:prod` is renamed `:production` (its `arch:contains` and
the `deploy:targetEnvironment` that names it move with it). No new class is needed.

### Environment-scoped facts are qualified relations

A container states a fact for one environment through a qualified relation: an
**`deploy:override`** to a `deploy:Override` node that names its environment with
**`deploy:environment`** and carries the replacement facts, using the same `deploy:`
predicates a container uses. The node lives in the architecture model graph, next to the
container it qualifies.

```turtle
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix :       <https://example.org/chat/> .

:development a arch:Environment ; rdfs:label "Development" ;
    seam:inModel :chat_architecture .

:production a arch:Environment ; rdfs:label "Production" ;
    arch:contains :web01 , :app01 , :db01 ;
    seam:inModel :chat_architecture .

# Shared facts: what every environment gets unless it overrides them.
:chat_api a arch:Container ; rdfs:label "Chat API" ;
    deploy:artifact [ a deploy:Artifact ;
                      deploy:reference "ghcr.io/example/chat-api" ;
                      deploy:version "0.3.1" ] ;
    deploy:configuration [ a deploy:Configuration ;
        deploy:binding [ deploy:key "DB_URL" ;
                         deploy:secretRef <https://secrets.example.org/chat/prod/db-url> ;
                         deploy:secretName "chat-prod-db-url" ;
                         deploy:connectsTo :message_db ] ] ;
    deploy:replicas 3 ;

    # Development: build from this checkout, a static user, seed data, and the
    # connection string from a file. Same store, same key; only the source differs.
    deploy:override [ a deploy:Override ;
        deploy:environment :development ;
        deploy:artifact [ a deploy:Artifact ;
                          deploy:reference "seams/chat-api" ;
                          deploy:version "local" ;
                          deploy:build [ a deploy:Build ;
                                         deploy:context "../.." ;
                                         deploy:dockerfile "docker/runtime.Dockerfile" ] ] ;
        deploy:configuration [ a deploy:Configuration ;
            deploy:binding [ deploy:key "DB_URL" ;
                             deploy:secretFile "../../docker/local-secrets/db_url" ;
                             deploy:connectsTo :message_db ] ;
            deploy:binding [ deploy:key "SEAMS_DEV_USER" ; deploy:value "builder" ] ;
            deploy:binding [ deploy:key "SEAMS_SEED" ; deploy:value "/app/seed.json" ] ] ] .
```

`deploy:context` and `deploy:secretFile` paths are relative to the model file's
directory, like `seam:renderPayload` paths, and `deploy:dockerfile` is relative to the
context, as in Docker. The generator rewrites them relative to the directory it writes
to (principle 6: no absolute paths).

### The override rule

For a container `C` and an environment `E`, the facts the generator uses are:

1. every shared fact of `C` (a triple with subject `C`), **except**
2. those whose predicate a `deploy:Override` of `C` for `E` also states: the override's
   values **replace** the shared values of that predicate on that subject, whole. An
   override `deploy:artifact` replaces the shared artifact; it is not merged with it.
3. `deploy:configuration` is the one exception, because bindings are blank nodes with an
   identity of their own: the `deploy:key`. An override binding replaces the shared
   binding with the same `deploy:key`, adds one when no shared binding has that key, and
   leaves every other shared binding in place.
4. When no override names `E`, or it states no fact for a predicate, the shared fact
   applies. Absent means shared, never "unset". An environment cannot remove a shared
   fact in v1; when one needs to, that is a new ADR.

In v1 an override may carry `deploy:artifact`, `deploy:configuration` and
`deploy:replicas`. Any other predicate on a `deploy:Override`, two overrides of one
container for one environment, or an override whose `deploy:environment` is not an
`arch:Environment` of the model is a SHACL violation and a `GeneratorError` naming the
container and the predicate (principle 5).

The production files in this repository need no overrides: the shared facts are already
prod-shaped. An override for `:production` is allowed, for a model whose shared facts are
development-shaped.

### Storage binding per environment

The store is the same in every environment. `seam:storedIn`, the store container and its
`deploy:storeKind` are shared facts and cannot be overridden. What an environment changes
is how the executing container's `deploy:connectsTo` binding gets its value: an external
secret (`deploy:secretRef`, `deploy:secretName`) in production, a file
(`deploy:secretFile`) in development. The override binding keeps the same `deploy:key`
and restates `deploy:connectsTo` with the same store; a binding that connects elsewhere is
a violation. ADR-0011's resolution at `Runtime.load` is therefore the same in both
environments, and the runtime still reads `<KEY>_FILE`. A development run on SQLite stays
`SEAMS_STORE_OVERRIDE=sqlite` (ADR-0011's development override), not a model fact.

### The replica caveat

Process instances and the live-update stream are held in the serving process (backlog
A10), so only one replica of the serving container works. Until A10 lands, the generator
renders the serving container with `replicas: 1` in every environment, whatever
`deploy:replicas` says, and writes a comment naming A10 and the declared count. The model
keeps `deploy:replicas 3` as the production intent; it is not rewritten to match a
limitation of the runtime. Model health reports the cap as a warning, so the gap is
visible rather than silent. Containers that hold no process state (the gateway, the
proxy) are not capped.

### One file per environment

The compose generator writes one file per `arch:Environment` of the model, named
`compose.<local name>.yaml`: **`compose.development.yaml`** and
**`compose.production.yaml`**. Environments are processed sorted by IRI (principle 6),
and each file's header names its environment as well as the model hash. The single
`compose.yaml` and every `compose.override.yaml` are removed. A local run becomes
`docker compose -f compose.development.yaml up`.

### New vocabulary

Proposed here, added with SHACL in S02 (principle 4: each answers a line in the
inventory above):

| Term | Domain → range | Answers |
|---|---|---|
| `deploy:Override` | class | An environment-scoped set of facts |
| `deploy:override` | `arch:Container` → `deploy:Override` | Which overrides a container has |
| `deploy:environment` | `deploy:Override` → `arch:Environment` | Which environment the override is for |
| `deploy:Build`, `deploy:build` | `deploy:Artifact` → `deploy:Build` | Build from source instead of pulling |
| `deploy:context`, `deploy:dockerfile` | `deploy:Build` → string | The build context and Dockerfile |
| `deploy:secretFile` | binding → string | A secret read from a file, not a platform secret |
| `deploy:proxies` | `arch:Container` → `arch:Container` | A code-free reverse proxy and its target |

`deploy:replicas`, `deploy:artifact` and `deploy:configuration` declare
`rdfs:domain arch:Container`. A second `rdfs:domain` would mean "both", so S02 drops the
`rdfs:domain` of the three overridable predicates and states the allowed subjects
(`arch:Container` or `deploy:Override`) in SHACL instead.

## Alternatives Considered

- **A named graph per environment** (`<urn:seams:graph:env:development>` holding
  `:chat_api deploy:replicas 1`). Rejected. It reuses predicates with no domain change,
  which is its appeal, but:
  - ADR-0001 makes a graph the unit of a model: renderer scoping, `seam:inModel`, and the
    view a generator reads. An environment graph holds facts about containers of a model
    from outside that model's graph, so every view and the viewer would need a second,
    environment-aware graph lookup.
  - ADR-0001 already reserves graphs for the lifecycle axis: as-designed versus
    as-deployed (`<urn:seams:graph:deployed>`) for drift detection. Environments are a
    second axis. Encoding both as graphs needs a graph per pair, and "as-deployed in
    production" has no single graph to diff against.
  - Bindings are blank nodes. A blank node in another graph is a different node, so the
    override rule for bindings could only match by `deploy:key` anyway, which the
    qualified relation does without a second graph.
  - The one write path (principle 10) would have to decide which graph each edit lands
    in, from the environment the user is looking at.
- **A container per environment** (`:chat_api_dev`, `:chat_api_prod`). Rejected: every
  seam edge (`seam:executes`, `seam:exposes`, `seam:storedIn` targets) would be stated
  twice, which is the duplication principle 1 forbids.
- **Keep a hand-written override, generated or not.** Rejected: it is the gap A4 exists
  to close; a generated override is two files where one will do.
- **Model the development identity, seed and knobs as runtime settings outside the
  model.** Rejected: they are what differs between environments, and A8's checklist
  needs them in the model to list per environment.
- **Write the capped replica count into the model.** Rejected: the model states the
  intended shape. The cap is a runtime limitation with a backlog item (A10), and lives in
  the generator with a visible warning until A10 removes it.

## Consequences

- **S02** adds the vocabulary above and its SHACL to `ontology/deploy.ttl` and the shapes;
  declares `:development` and `:production` (renaming `:prod`) in
  `examples/chat-app/chat-app.trig` and expenses chapter 8 (and the later chapters, so
  every checkpoint conforms); states the development overrides and the shared
  corrections from the inventory; changes `seams_gen/compose.py` to apply the override
  rule per environment and write `compose.development.yaml` and
  `compose.production.yaml`; deletes `compose.override.yaml` at the root and in chapters
  8 and 9; and moves the tutorial end-to-end run to the generated development file.
  Every generator rule in the inventory is implemented there, with goldens.
- **S03** generates the build file for the serving container, which can replace the
  development `deploy:dockerfile` fact and the `SEAMS_APP_DIR`/`SEAMS_ROUTES_FILE` build
  args, and publishes images tagged with the model hash so production's shared
  `deploy:artifact` references exist.
- **S04** lists secrets and configuration keys per environment by applying the same
  override rule: production's `deploy:secretName`s, development's `deploy:secretFile`s,
  and every `deploy:key`. It checks that each exists without reading it.
- **A10** removes the replica cap; nothing else in this ADR changes when it does.
- Readers of the model can now ask what differs between environments with one query over
  `deploy:override`, and `impact-of-node.rq` stays correct because nodes stay in the
  environment that contains them.

## Implementation Notes

Recorded when S02 landed (M016/S02). They describe how the decision was implemented and
change nothing above.

- The `seams.toml` environment names equal the model's `arch:Environment` local names
  (`development`, `production`), so `seams status --env development` and
  `compose.development.yaml` name the same environment.
- The development-only `${KEY:-value}` rule keys on the environment whose local name is
  `development`.
- Generated relative paths keep a leading `../` rather than `./../`. The expenses compose
  project name is the generated `expense_system`, which replaced the hand-written
  `seams-expenses`.
- Every `compose*.yaml` at a compose target counts as generated, so a leftover
  `compose.yaml` or `compose.override.yaml` fails `tests/test_generated_outputs_current.py`.

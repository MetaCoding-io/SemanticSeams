# Tutorial: from the chat-app model to a running chat

This tutorial takes you from a clean checkout to a chat page that talks to an LLM.
Everything the app does comes from one model: the IFML interaction model, the BPMN process,
the DMN routing table and the SHACL shapes in `examples/chat-app/`. You regenerate the code
from it, start the stack with Docker Compose, and chat.

This is the quick-start track: a finished model, the pipeline end to end, in about ten
minutes. To write a model yourself, one layer per chapter, follow the other track,
[Build an expense approval app](tutorials/expenses/index.md).

The regeneration and Docker commands below are the ones CI runs: the `acceptance` job
runs the generators and fails on any diff, and the `tutorial-e2e` job brings the same stack
up in stub mode and chats with it (`tests/test_tutorial_e2e.py`).

## 1. Prerequisites

- **Docker** with **Compose 2.24 or later** (`docker compose version`). The local override
  uses Compose's `!override` merge tag, which older versions reject.
- **[uv](https://docs.astral.sh/uv/)**, only if you want to regenerate the code. It installs
  Python 3.12 from `.python-version` if needed. Running the app needs only Docker.

## 2. Clone and look at the model

```
git clone https://github.com/MetaCoding-io/SemanticSeams.git
cd SemanticSeams
```

The model is in `examples/chat-app/`:

- `chat-app.trig`: the whole application as one RDF graph, one named graph per model:
  the C4-style architecture, the IFML chat page (`:chat_page`, its conversation list,
  message thread and compose form), the SHACL shapes (`:MessageShape`,
  `:ConversationShape`), the message lifecycle, the API operations and SSE channel, and
  the deployment (`deploy:`) facts. The seams join them: the compose form's `:send_message`
  event `seam:triggers` the send-message process, which is `seam:governedBy` a policy.
- `chat_process.bpmn`: the send-message process, executed as-is by SpiffWorkflow.
- `routing.dmn`: the decision table that picks the model provider for a message.

Optionally, browse the same graph in the read-only viewer (see "v1: the viewer" in the
[README](../README.md)): click from the architecture into the chat page, from the compose
form's event into the BPMN process, and from its business-rule task into the DMN table.

## 3. Regenerate the code

The generated code is committed, so this step is optional. It shows that the
code follows from the model. Set up Python once with uv, which installs the versions
pinned in `uv.lock`:

```
uv sync --all-packages
source .venv/bin/activate
```

Then regenerate everything the chat app's project file names:

```
seams generate --project examples/chat-app
```

It reads [`examples/chat-app/seams.toml`](../examples/chat-app/seams.toml), which names the
three generators and their outputs: the FastAPI route module
(`examples/chat-app/generated/chat_api.py`), the htmx page and partials
(`examples/chat-app/generated/templates/`) and the prod-shaped root `compose.yaml`. The
[seams CLI reference](/reference/seams-cli) describes the file. To run a single generator,
`python -m seams_gen <generator>` still works. It also rewrites
[`examples/chat-app/seams.lock`](../examples/chat-app/seams.lock), which records the model
hash, generator version, file hash and source elements of every output. On an unchanged
model the command produces no diff:

```
git diff --exit-code -- examples/chat-app/generated examples/chat-app/seams.lock compose.yaml
```

CI runs exactly this command, and the same for each expenses chapter, and fails if anything changed.

## 4. Choose an LLM

The `llm_gateway` service reads its key from `.secrets/llm_api_key` (git-ignored). You have
two options.

**Stub (no key).** An empty key file makes the gateway stream a deterministic reply,
`Stub reply to: <your message>`:

```
mkdir -p .secrets && : > .secrets/llm_api_key
```

**OpenAI.** Write your key to the file instead. Never commit it:

```
mkdir -p .secrets && printf '%s' "$OPENAI_API_KEY" > .secrets/llm_api_key
```

**Ollama and other OpenAI-compatible servers.** The gateway proxies to
`UPSTREAM_BASE_URL` (default `https://api.openai.com/v1`). Set it in your shell before
step 5 to point at another server, e.g. Ollama's `http://<host>:11434/v1`. Set
`LLM_MODEL_OVERRIDE` to the model name the server knows, e.g. `llama3.1:8b`. Ollama
ignores the key, but the file must not be empty, or the gateway falls back to the stub.
`LLM_GATEWAY_STUB=1` forces the stub even when a key is present. These knobs are
documented at the top of `compose.override.yaml`.

## 5. Start the stack

```
docker compose up --build
```

Compose merges the generated `compose.yaml` with the hand-written `compose.override.yaml`,
builds the runtime and gateway images from this checkout, and starts four services:
`chat_api` (the runtime serving the generated route module), `llm_gateway`, `chat_ui`
(a reverse proxy on port 8080) and `message_db`. The first build takes a minute or two.

The runtime image bakes in one app's generated route module, templates and seed data,
chosen by the `SEAMS_APP_DIR` and `SEAMS_ROUTES_FILE` build args (default
`examples/chat-app` and `chat_api.py`). It does not bake in the model: `compose.yaml`
bind-mounts the TriG and its payloads at `/model`, and `SEAMS_MODEL` names the TriG the
runtime loads (see [seams_runtime/README.md](https://github.com/MetaCoding-io/SemanticSeams/blob/main/seams_runtime/README.md)).

## 6. Open http://localhost:8080 and chat

The page lists the seeded conversations ("Welcome", "Scratch pad") and opens the first one
by id. Type a message and press **Send Message**:

1. htmx posts the form to `POST /conversations/<id>/messages`. The route validates it
   against `:MessageShape`, starts a `chat_process` instance and returns the message item.
   An empty message is rejected with a 422 that names the violated shape constraint.
2. The worker runs the BPMN process: the DMN table picks the provider, the service task
   calls the gateway, and each token is published on the conversation's SSE channel
   (`/conversations/<id>/stream`, event `token`), which the page appends.
3. The reply is stored as an assistant message; reload the page to see the whole thread.

### See where it landed

The model says `:MessageShape seam:storedIn :message_db`, and `:message_db` is a
`deploy:PostgreSQL` store that `chat_api` `deploy:connectsTo` with key `DB_URL`. So your
message is a row in the `message_db` container's `chat` database. Send a message with
"hello" in it, then ask PostgreSQL for the shape of every stored entity that mentions it:

```
docker compose exec -T message_db psql -U postgres -d chat -tAc "SELECT shape FROM entities WHERE data::text LIKE '%hello%'"
```

It prints `https://example.org/chat/MessageShape`, one line per stored message that
mentions "hello". The runtime reports its store too:

```
curl localhost:8080/healthz
```

The `store` object says `"kind": "postgresql"`, `"declared": "PostgreSQL"`, the
`:message_db` container IRI and `"override": false`. The end-to-end test
(`tests/test_tutorial_e2e.py`) runs both checks.

Stacks started before M011 kept their data in a SQLite file on a `/data` volume. That
volume is no longer used and nothing migrates it; `docker compose down -v` deletes it
along with the rest of the stack's data.

When you are done, stop the stack and delete its data:

```
docker compose down -v
```

## 7. Change the model

Edit the model and watch the app follow. For example, change the chat page's title in
`examples/chat-app/chat-app.trig`:

```
        ifml:title "Chat"@en ;
```

to `"My chat"@en`, then rerun the three generators from step 3 and restart with
`docker compose up --build`. The browser tab title changes.

If you skip regenerating, the app refuses to start. Every generated file records the
model's content hash (`MODEL_HASH` in `chat_api.py`, `SEAMS_MODEL_HASH` in `compose.yaml`),
and `Runtime.load` compares it with the model that is mounted at `/model`. A mismatch
raises `ModelHashMismatch` and the `chat_api` container exits instead of serving code
generated from a different model (ADR-0007 rule 2).

## 8. What runs where

[ADR-0007](adr/0007-execution-strategy.md) splits the app into three parts.

| Part | Files | Edited by hand? |
|---|---|---|
| **Generated** from the model | `examples/chat-app/generated/chat_api.py`, `examples/chat-app/generated/templates/*.html`, `compose.yaml` | Never. Regenerate them; CI fails if they drift from the model. |
| **Runtime**, generic and model-agnostic | `packages/seams/` (reads the model), `seams_runtime/` (SpiffWorkflow for BPMN/DMN, pySHACL contracts, lifecycle guard, policy hook, SSE bus, host), `seams_gateway/` | Yes. It names no chat-app term; it reads the model at runtime. |
| **Local override** | `compose.override.yaml`, `docker/*.Dockerfile`, `examples/chat-app/seed.json` | Yes. This is what a laptop run needs and production does not: local image builds, file secrets, a dev Postgres database (`chat`, password and `DB_URL` the runtime connects with), a single replica, the reverse proxy and the seed data. |

The generated code holds no business logic. The workflow order lives in the BPMN, the
routing rules in the DMN, and the validation in the SHACL shapes, and the runtime executes
all of them from the same graph the viewer shows. The UI, the API routes and the deployment
are generated, because no engine interprets those from a graph.

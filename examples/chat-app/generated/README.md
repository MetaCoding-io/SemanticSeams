# Generated chat-app code

Every file here except this README is generated from
[`../chat-app.trig`](../chat-app.trig) by [`seams_gen`](../../../seams_gen/README.md),
and so are the repository-root `compose.development.yaml` and `compose.production.yaml`,
one per `arch:Environment` the model declares (ADR-0015). Do not edit them: change the model
and regenerate. Each file carries the model hash it was generated from.

| File | Generator |
|---|---|
| `chat_api.py` | `fastapi`: the route module of the container that executes the process |
| `templates/chat_page.html` | `htmx`: the landmark page |
| `templates/conversation_list.html`, `templates/message_thread.html`, `templates/message_thread_item.html` | `htmx`: the fragment partials the routes render |
| `../../../compose.development.yaml`, `../../../compose.production.yaml` | `compose`: one docker compose file per environment, paths relative to the repository root; `docker compose -f compose.development.yaml up --build` runs the local stack |
| `exports/structurizr/workspace.dsl` | `structurizr`: a Structurizr DSL workspace of the model's people, systems, containers and relationships, with what the model lacks as comment lines (ADR-0044) |
| `exports/likec4/model.c4` | `likec4`: the same C4 extract as a LikeC4 model (ADR-0044) |
| `exports/plantuml/sequence/send_message.puml`, `exports/plantuml/storm/send_message_process.puml` | `plantuml`: the derived sequence and storm views as PlantUML, beside the Mermaid ones, with gaps as `' gap:` comment lines (ADR-0044) |

Regenerate from the repository root:

```
seams generate --project examples/chat-app
```

It runs the generators [`../seams.toml`](../seams.toml) names, writing each output
above (reference: [docs/reference/seams-cli.md](../../../docs/reference/seams-cli.md)).
`seams generate` records every output in [`../seams.lock`](../seams.lock) (model
hash, generator version, file hash and source elements), deletes a file no
generator writes any more, and reports a file edited by hand.
`tests/test_generated_outputs_current.py` fails when a committed file differs from
what the generators produce, and CI runs `seams check --project examples/chat-app`,
which fails on any missing, stale, hand-edited or orphaned output here or an
out-of-date `seams.lock`.

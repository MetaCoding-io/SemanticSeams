# Generated chat-app code

Every file here except this README is generated from
[`../chat-app.trig`](../chat-app.trig) by [`seams_gen`](../../../seams_gen/README.md),
and so is the repository-root `compose.yaml`. Do not edit them: change the model
and regenerate. Each file carries the model hash it was generated from.

| File | Generator |
|---|---|
| `chat_api.py` | `fastapi`: the route module of the container that executes the process |
| `templates/chat_page.html` | `htmx`: the landmark page |
| `templates/conversation_list.html`, `templates/message_thread.html`, `templates/message_thread_item.html` | `htmx`: the fragment partials the routes render |
| `../../../compose.yaml` | `compose`: the docker compose file, bind mounts relative to the repository root |

Regenerate from the repository root:

```
seams generate --project examples/chat-app
```

It runs the three generators [`../seams.toml`](../seams.toml) names, writing each output
above (reference: [docs/reference/seams-cli.md](../../../docs/reference/seams-cli.md)).
`seams generate` records every output in [`../seams.lock`](../seams.lock) (model
hash, generator version, file hash and source elements), deletes a file no
generator writes any more, and reports a file edited by hand.
`tests/test_generated_outputs_current.py` fails when a committed file differs from
what the generators produce, and CI reruns the command above and fails on any
`git diff` or untracked file under these paths.

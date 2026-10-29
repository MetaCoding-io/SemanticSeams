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
python -m seams_gen fastapi examples/chat-app/chat-app.trig --out examples/chat-app/generated
python -m seams_gen htmx examples/chat-app/chat-app.trig --out examples/chat-app/generated/templates
python -m seams_gen compose examples/chat-app/chat-app.trig --out .
```

If a generator stops writing a file, delete the committed copy.
`tests/test_generated_outputs_current.py` fails when a committed file differs from
what the generators produce, and CI reruns the commands above and fails on any
`git diff` or untracked file under these paths.

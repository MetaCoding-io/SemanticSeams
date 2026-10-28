# Golden-output gap table

Every `[gap: GAP-NN]` marker in a golden artifact under this directory points
at one row here. Each row is something the chat-app graph
(`examples/chat-app/chat-app.trig`) cannot say today, with the vocabulary
addition that would let a generator produce the line. The table is the input
to M004's vocabulary slice; see [README.md](README.md) for the marking
convention. IDs are sequential and never reused.

| ID | Artifact | What the graph cannot say | Proposed vocabulary addition | Layer |
|----|----------|---------------------------|------------------------------|-------|
| GAP-01 | compose.yaml | Images for `:chat_ui`, `:llm_gateway` and `:message_db`: only `:chat_api` carries a `deploy:artifact`; the others have just free-text `arch:technology` ("PostgreSQL"), which is not an image reference. | Model a `deploy:artifact [ deploy:reference ; deploy:version ]` on every container, or a `deploy:baseImage` for off-the-shelf services such as Postgres. | deploy |
| GAP-02 | compose.yaml | Ports: which port each container listens on, and which ports are published to the host (`ports`) versus internal only (`expose`). | `deploy:port` on the container (container port, protocol) plus a `deploy:publishedPort` or `deploy:exposure` (public/internal) per environment. | deploy |
| GAP-03 | compose.yaml | Persistent storage: `:message_db` needs a named volume for the Postgres data directory; the graph has no notion of state that outlives a container. | `deploy:volume [ deploy:mountPath ; deploy:persistence ]` on the container, with the named volume as a `deploy:Volume` resource. | deploy |
| GAP-04 | compose.yaml | The compose meaning of placement: `seam:deployedTo :web01/:app01/:db01` and `deploy:placement [ deploy:targetEnvironment :prod ]` name nodes, but not how a node maps to a compose/swarm constraint (hostname, node label) or whether placement applies to single-host compose at all. | A `deploy:nodeSelector` (label key/value) on `arch:DeploymentNode`, or a rule that `seam:deployedTo` renders as a fixed node-label constraint; a flag on `arch:Environment` saying whether placement is honoured. | deploy / arch |
| GAP-05 | compose.yaml | How a `deploy:secretRef` IRI (e.g. `https://secrets.example.org/chat/prod/db-url`) resolves to a compose secret source: external secret name, file, or environment, and which secret store owns the IRI. | `deploy:secretStore` on the environment with a resolution scheme (IRI → external secret name), or `deploy:secretName` on the binding. Values stay out of the graph. | deploy |
| GAP-06 | compose.yaml | Non-secret configuration: only `:chat_api` has a `deploy:configuration`, and it holds only secret bindings. Plain values (the LLM gateway URL `:chat_api` uses to reach `:llm_gateway`, the gateway's upstream URL, Postgres database name) have no home. | `deploy:binding [ deploy:key ; deploy:value ]` for literal config, and a derived binding from `arch:dependsOn` to the target's service URL. | deploy |
| GAP-07 | compose.yaml | Startup ordering and readiness: `arch:dependsOn` (`:chat_ui` → `:chat_api`, `:chat_api` → `:llm_gateway`) is logical, not a startup order, and nothing says when a dependency is ready (the healthcheck a `condition: service_healthy` needs). | Either a rule that `arch:dependsOn` implies `depends_on`, or explicit `deploy:dependsOn` everywhere, plus `deploy:healthcheck [ deploy:probe ; deploy:interval ]` on containers. | deploy / arch |

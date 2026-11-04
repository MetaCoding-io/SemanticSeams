# 10. Expenses in SemPKM

At the end of this chapter the expenses no longer live in a table. They live in SemPKM,
a semantic knowledge store. Each expense becomes a SemPKM object typed by the class chapter 9's ontology gave it,
`:Expense`, under an IRI SemPKM mints. People can browse, link and annotate expenses
there, while the approval process goes on running exactly as before. Approvals, payments,
notifications and the process state stay in PostgreSQL.

[ADR-0025](/adr/0025-sempkm-store) makes SemPKM a third store kind, beside SQLite and
PostgreSQL, for domain data only. The runtime still owns what it needs to run a process.
Moving a shape there takes three things in the model: a store container of kind
`deploy:SemPKM`, two bindings on the API that reach it, and a `seam:storedIn` edge. No
generated code changes, and no line of Python changes either.

## The store and its triplestore

SemPKM is two services: its API, and the RDF4J triplestore that holds its data. Declare
both in the architecture graph and add them to `:expense_system`'s `arch:contains`. The
API container's `deploy:storeKind` is what makes it a store:

```trig
    :expense_pkm a arch:Container ; rdfs:label "Expense Knowledge Store" ;
        arch:technology "SemPKM" ;
        deploy:storeKind deploy:SemPKM ;
        arch:dependsOn :expense_triplestore ;
        deploy:artifact [ a deploy:Artifact ;
                          deploy:reference "ghcr.io/metacoding-io/sempkm-api" ;
                          deploy:version "1.0.0" ] ;
        deploy:configuration [ a deploy:Configuration ;
                               deploy:binding [ deploy:key "TRIPLESTORE_URL" ;
                                                deploy:value "http://expense_triplestore:8080/rdf4j-server" ] ;
                               deploy:binding [ deploy:key "REPOSITORY_ID" ;
                                                deploy:value "expenses" ] ;
                               deploy:binding [ deploy:key "BASE_NAMESPACE" ;
                                                deploy:value "https://example.org/expenses/data/" ] ] ;
        deploy:port [ a deploy:Port ; deploy:containerPort 8000 ] ;
        deploy:volume [ a deploy:Volume ;
                        deploy:volumeName "expense_pkm_data" ;
                        deploy:mountPath "/app/data" ] ;
        deploy:dependsOn :expense_triplestore ;
        deploy:healthcheck [ a deploy:Healthcheck ;
                             deploy:probe "curl -f http://localhost:8000/api/health" ;
                             deploy:interval "10s" ] ;
        seam:inModel :expense_architecture .
```

```trig
    :expense_triplestore a arch:Container ; rdfs:label "Expense Triplestore" ;
        arch:technology "RDF4J" ;
        deploy:artifact [ a deploy:Artifact ;
                          deploy:reference "eclipse/rdf4j-workbench" ;
                          deploy:version "5.0.1" ] ;
        deploy:port [ a deploy:Port ; deploy:containerPort 8080 ] ;
        deploy:volume [ a deploy:Volume ;
                        deploy:volumeName "expense_triplestore_data" ;
                        deploy:mountPath "/var/rdf4j" ] ;
        deploy:healthcheck [ a deploy:Healthcheck ;
                             deploy:probe "curl -f http://localhost:8080/rdf4j-server/protocol" ;
                             deploy:interval "10s" ] ;
        seam:inModel :expense_architecture .
```

SemPKM keeps the key it signs sessions with on its data volume, so it needs no secret of
its own. If your registry holds SemPKM's API image under another name, change
`deploy:reference` and regenerate. Nothing else names it.

## Two bindings on the API

The runtime reaches SemPKM the way it reaches PostgreSQL: through a binding that
`deploy:connectsTo` the store. SemPKM also wants a service token, so a second binding
`deploy:authenticatesTo` it. The token is a credential, and the shapes refuse a token
binding that carries a plain `deploy:value`. Add both to `:expense_api`'s configuration:

```trig
                               # SemPKM (ADR-0025): its URL, and the service
                               # token that deploy:authenticatesTo it, a secret.
                               deploy:binding [ deploy:key "SEMPKM_URL" ;
                                                deploy:value "http://expense_pkm:8000" ;
                                                deploy:connectsTo :expense_pkm ] ;
                               deploy:binding [ deploy:key "SEMPKM_TOKEN" ;
                                                deploy:secretRef <https://secrets.example.org/expenses/prod/sempkm-token> ;
                                                deploy:secretName "expenses-prod-sempkm-token" ;
                                                deploy:authenticatesTo :expense_pkm ] ] ;
```

In development the token comes from a file, as the connection string does:

```trig
                deploy:binding [ deploy:key "SEMPKM_TOKEN" ;
                                 deploy:secretFile "../../../docker/local-secrets/expense_sempkm_token" ;
                                 deploy:authenticatesTo :expense_pkm ] ] ] ;
```

Also add `:expense_pkm` to the API's `arch:dependsOn` and `deploy:dependsOn`, so the API
starts after SemPKM is healthy.

## Move the expenses

In the seams graph, point `:ExpenseShape` at the new store. The other shapes stay where
they are:

```trig
    # Chapter 10: expenses live in SemPKM; the rest stays in PostgreSQL.
    :ExpenseShape seam:storedIn :expense_pkm .
    :ApprovalShape seam:storedIn :expense_db .
    :PaymentShape seam:storedIn :expense_db .
    :NotificationShape seam:storedIn :expense_db .
```

That is all the model needs. The runtime resolves it when it loads. Each SemPKM-stored
shape must have a `sh:targetClass`, because SemPKM types every object it stores, and
`:ExpenseShape` has had one since chapter 9. The model must also import gistCore 14.0.0,
which this one does. If a fact is missing, the runtime refuses to start and names it:
a token binding that is absent, duplicated or not a secret, a shape with no target
class, or a second SemPKM store.

## Generate and check

```sh
seams generate --project examples/expenses/chapter-10
seams check --project examples/expenses/chapter-10
```

The route module and templates are chapter 9's, apart from the model hash. The compose
files gain two services, `expense_pkm` and `expense_triplestore`, built from their own
facts: images, ports, volumes and healthchecks. The API's `SEMPKM_URL` becomes an
environment entry. `SEMPKM_TOKEN` becomes a secret mounted as `SEMPKM_TOKEN_FILE`, an
external secret in production and the local file in development. The generator knows
nothing about SemPKM. It writes what the model says.

## Teach SemPKM the expense

SemPKM now stores each expense, but knows nothing about it: no form, no table, no type
in its navigation. SemPKM learns a kind of data from a **Mental Model**, a directory it
installs. The project file runs one more generator,
[ADR-0026](../../adr/0026-mental-model.md)'s `mentalmodel`:

```toml
[[generators]]
name = "mentalmodel"
out = "generated/mental-model"
```

It writes the Mental Model of the ontology chapter 9 added, so the ontology needs one
more fact, the version SemPKM's manifest carries, as three numbers:

```trig
    :expense_ontology a seam:Model , owl:Ontology ;
        rdfs:label "Expense Ontology" ;
        # The package version SemPKM's manifest carries (ADR-0026): three numbers.
        owl:versionInfo "1.0.0" ;
```

`seams generate` then writes four files under `generated/mental-model`:

- `manifest.yaml`. Its `modelId` (`expense-ontology`) comes from the ontology's IRI,
  `version` from `owl:versionInfo` and `name` from `rdfs:label`. If a fact is missing,
  the generator fails and names the ontology and the predicate.
- `ontology/expense-ontology.jsonld`: the ontology node, importing gistCore 14.0.0.
- `shapes/expense-ontology.jsonld`: every shape with a target class, so SemPKM's forms
  ask for and check what the generated app does.
- `views/expense-ontology.jsonld`: one table for each IFML list or details view that
  reads a shape, with a column for each of the shape's fields.

SemPKM accepts no subject outside its own namespace, so the package's own nodes are
named `urn:sempkm:model:expense-ontology:…`, each derived from a model term. The classes
and properties keep the model's IRIs, because they are the types and properties of the
expenses the runtime writes.

To install it, copy the directory where SemPKM can read it and, as SemPKM's owner, call
`POST /api/models/install` with its path:

```sh
docker compose -f examples/expenses/chapter-10/compose.development.yaml \
  cp examples/expenses/chapter-10/generated/mental-model expense_pkm:/tmp/mental-model
```

```json
{"path": "/tmp/mental-model"}
```

SemPKM warns that the package ships no documentation, and installs it. **Expense** then
appears among its types, with a form and the views.

## Run it

You need a SemPKM and a PostgreSQL. To run the whole stack, start it from the
generated compose file:

```sh
docker compose -f examples/expenses/chapter-10/compose.development.yaml up --build
```

The API reads its SemPKM token from `docker/local-secrets/expense_sempkm_token`, which the
repository does not hold: a token belongs to one SemPKM. Save a key from that SemPKM
there before the API starts, or set `SEMPKM_TOKEN_FILE` to another file.

To run the host in process instead, start SemPKM from its own checkout
(`docker compose up` there serves its API on `http://localhost:8001`). In SemPKM's
**Settings**, under **API Keys**, generate a key and save it to a file. The runtime
needs the scopes `commands:execute` (to write) and `sparql:read` (to read). Then point
the host at SemPKM and at a PostgreSQL:

```sh
SEAMS_MODEL=examples/expenses/chapter-10/expenses.trig \
SEAMS_TEMPLATES=examples/expenses/chapter-10/generated/templates \
SEAMS_DB= \
DATABASE_URL=postgresql://postgres:seams-dev@localhost:5432/expenses \
SEMPKM_URL=http://localhost:8001 \
SEMPKM_TOKEN_FILE=/tmp/sempkm-token \
python -m seams_runtime.host --routes examples/expenses/chapter-10/generated/expense_api.py --port 8002
```

Submit an expense as in chapter 9:

```sh
curl -X POST http://localhost:8002/expenses/hotel -d "description=Hotel" -d amount=250.00 -d date=2026-10-02 \
  -H "X-Forwarded-User: alice" -H "X-Forwarded-Groups: employee"
```

The runtime validates the form against `:ExpenseShape` first. An invalid expense is a
422, and nothing is sent to SemPKM. A valid one goes to SemPKM as a single
`POST /api/commands` request: an `object.create` of type `:Expense` with one property per
field, the status as its category member `:s_submitted`. SemPKM commits the request in one
transaction and returns the IRI it minted, which becomes the expense's id. Open SemPKM
and the expense is there. Every read, such as `GET /expenses/hotel` or the list, is a
SPARQL query scoped to `:Expense` and the shape's paths. When the manager approves, the
runtime patches the expense's status in SemPKM to `:s_approved`, and the approval itself is
stored in PostgreSQL.

`/healthz` reports the store:

```sh
curl localhost:8002/healthz
```

```json
"sempkm": {"kind": "SemPKM", "container": "https://example.org/expenses/expense_pkm", "reachable": true, "override": false}
```

If SemPKM is down, a write or a read answers 503 with an `application/problem+json`
body naming `:expense_pkm`, and the runtime keeps nothing. If the token is wrong or
lacks a scope, the answer is also 503, and the log names the store and the missing scope.
The token itself is never logged. If SemPKM answers without an IRI, the answer is 502.

To work without SemPKM, set `SEAMS_STORE_OVERRIDE=sqlite`. The expenses then stay in
embedded SQLite with everything else, and the runtime logs a warning naming the SemPKM
store it skipped. The test harness runs every chapter this way.

## Checkpoint

Your file should now match
[`examples/expenses/chapter-10/expenses.trig`](../../../examples/expenses/chapter-10/expenses.trig).
The payload files and the handler are unchanged from chapter 9. To see only what this
chapter added:

```sh
diff examples/expenses/chapter-09/expenses.trig examples/expenses/chapter-10/expenses.trig
```

`tests/test_expense_sempkm.py` checks this chapter. It runs `seams check`, resolves the
store plan (expenses in `:expense_pkm`, everything else in `:expense_db`), and checks the
SemPKM services in both compose files. It checks that the committed Mental Model is a fresh
render of the model and, with `SEAMS_E2E=1`, installs it into the chapter's SemPKM. It also serves the committed route module against
a fake SemPKM that applies commands and answers SPARQL the way SemPKM does. In that run,
a submitted expense is stored and read back under its minted IRI, approving it patches
its status, an invalid expense sends nothing, and a SemPKM outage is a 503 naming the
store.

# ADR-0041: Stored-Data Migrations From the Shape Diff — `seams plan` Writes SQL Over `entities.data` per Relational Store Kind for a Removed Field or a Defaulted Required Field, and Refuses Every Other Breaking Stored Change, and Every SemPKM One, Naming the Shape, the Path and the Reason

**Status:** Accepted

**Date:** 2026-11-15

**Source:** milestone M031/S03; backlog X5; research note
[UML coverage and gaps](../research/2026-10-29-uml-coverage-and-gaps.md) section 3.4;
builds on [ADR-0002](./0002-iri-identity-and-migration.md),
[ADR-0011](./0011-storage-resolution.md),
[ADR-0021](./0021-vocabulary-versions.md),
[ADR-0023](./0023-shapes-target-classes.md),
[ADR-0025](./0025-sempkm-store.md),
[ADR-0036](./0036-cross-aggregate-invariants.md) and
[ADR-0040](./0040-external-systems-and-webhooks.md); decisions D052 (`seams diff`) and D053
(`seams plan`)

## Context

`seams diff` (U8, D052) classifies every shape change between two model versions as
`compatible` or `breaking`, and marks each shape change with the `data` scope: stored
instances of the shape may no longer conform. `seams plan` (U9, D053) writes the same
changes as a Markdown change plan and exits 1 when any is breaking; the CI job turns
that exit code into a warning on the pull request.

Neither says what to do with the rows already stored. The UML note's section 3.4 found
that a breaking stored change is announced and then left to the operator, who has to
work out from the diff's detail which JSON key of which rows to rewrite. Backlog X5 asks
for the next step: generate the migration where one is mechanical, and refuse the
deploy where it is not.

What the runtime stores, which this ADR rewrites:

- **One `entities` table per relational store** (`seams_runtime/store.py`), with the
  columns `id, shape, correlation_key, instance_id, data, status, created`.
- **`shape` is the node shape's full IRI**, as `put_entity` writes `str(shape)`.
- **`data` is the entity's payload as JSON**, keyed by field name: the `Field.name` of
  the shape's typed view (ADR-0023), which is the property's `sh:name`, else its path's
  local name. It is never keyed by the path IRI. The worker adds a `status` key for a
  lifecycle shape.
- **SQLite** (`SQLiteStore`) keeps `data` as TEXT holding `json.dumps(data,
  sort_keys=True)`. **PostgreSQL** (`PostgresStore`) keeps it as `jsonb`; its schema is
  the connection's `search_path`.
- **SemPKM** (`deploy:SemPKM`, ADR-0025) keeps the data of the shapes `seam:storedIn` it
  as RDF in SemPKM. The relational `entities` row of such an entity is an index row
  whose `data` is `{}`.

## Decision

### 1. Input: the breaking changes in the data scope, of the shapes OLD stores

`seams_cli.migrations.migrations(old, new, changes)` reads the `Change` rows that
`seams_cli.diff.diff_loaded(old, new)` returns, and only those that:

- have the verdict `breaking`;
- carry the `data` scope (a change only in the `contract` scope, such as
  `operation-removed`, touches no stored row);
- have as subject a **stored shape of OLD**: a `sh:NodeShape` that OLD `seam:storedIn` a
  container (ADR-0036's "stored shape"), or that some element of OLD `seam:writes`. A
  model that declares no store keeps embedded SQLite (ADR-0011), so a written shape has
  rows even without `seam:storedIn`. A shape OLD neither stores nor writes has no rows:
  its breaking changes stay in the plan's change list and get neither a migration nor a
  refusal.

The function returns `Migration` and `Refusal` records, sorted by (shape, path, kind).
Compatible changes produce nothing: a looser constraint keeps every stored row valid.

### 2. The records

- **`Migration(kind, shape, path, sql)`**: `kind` is the store kind the SQL is for
  (`sqlite` or `postgresql`), `shape` the shape IRI the rows carry in `entities.shape`,
  `path` the property's `sh:path` as the diff spells it, and `sql` one statement.
- **`Refusal(kind, shape, path, reason)`**: `kind` is the change kind
  (`property-added`, `shape-removed`, …), `shape` and `path` as above (`path` is `-` for
  a whole shape), and `reason` a sentence naming the fact that is missing or the store
  that cannot be rewritten.

The JSON key a migration rewrites is the field name: for a removed field, its
`Field.name` in OLD's typed view; for an added field, its `Field.name` in NEW's.

### 3. Mapping per change kind

| Change kind (breaking) | Result |
|---|---|
| `property-removed` | a migration per relational kind that drops the field's JSON key from every row of the shape |
| `property-added` with `sh:minCount` > 0, the new property shape stating one `sh:defaultValue` | a migration per relational kind that sets the key to the default on every row of the shape that lacks the key; a row that has it keeps its value |
| `property-added` with `sh:minCount` > 0 and no `sh:defaultValue` | refused: "no sh:defaultValue to fill the rows that lack it" |
| `shape-removed` | refused: the rows of a removed shape have no shape to conform to, and deleting them is not mechanical |
| `datatype-changed`, `class-changed`, `min-count-changed`, `max-count-changed` (the tightening ones) | refused: converting or trimming a stored value needs a rule the model does not state |

The default is read from NEW's shapes: the `sh:defaultValue` on the property shape of
the added field. Its JSON value is the one the runtime's boundary stores for a payload
that omits the field (`seams_runtime.contracts`, which fills `sh:defaultValue` before
validation): a JSON boolean for `xsd:boolean`, a JSON number for `xsd:integer` and
`xsd:double`, and a JSON string holding the lexical form for every other datatype,
`xsd:decimal` included. `seams_cli` does not import `seams_runtime`, so a test pins the
two together by storing a default through the runtime and comparing the row with the
migrated one. A default that is not a literal, or more than one, is refused naming
`sh:defaultValue`.

### 4. SQL per store kind

Every statement names the table `entities` unqualified and matches rows by `shape =` the
shape IRI. String literals have each `'` doubled.

- **SQLite** (`data` is TEXT JSON): the JSON path is `$."<key>"`.
  - drop: `UPDATE entities SET data = json_remove(data, '$."key"') WHERE shape = '<iri>';`
  - default: `UPDATE entities SET data = json_set(data, '$."key"', json('<value>')) WHERE
    shape = '<iri>' AND json_type(data, '$."key"') IS NULL;`
- **PostgreSQL** (`data` is `jsonb`):
  - drop: `UPDATE entities SET data = data - '<key>' WHERE shape = '<iri>';`
  - default: `UPDATE entities SET data = jsonb_set(data, ARRAY['<key>'],
    '<value>'::jsonb) WHERE shape = '<iri>' AND NOT (data ? '<key>');`
  - The statements run with the deploy's `search_path`, which is how `PostgresStore`
    picks its schema.
- **SemPKM**: refused. When the shape is `seam:storedIn` a `deploy:SemPKM` store in OLD
  or in NEW, every breaking change of it is refused with the reason "stored in the
  SemPKM store `<store>`; SemPKM data is not rewritten by SQL". Its relational index row
  holds no data to rewrite, and SemPKM's own data is the owner's (ADR-0025, ADR-0040).

A shape stored in a relational store gets the SQL for **both** relational kinds, whatever
kind its store declares: `SEAMS_STORE_OVERRIDE=sqlite` (ADR-0011) runs a PostgreSQL model
on SQLite, so either kind can hold its rows. The JSON value in the SQL is the default
encoded with `json.dumps(value, sort_keys=True)`, the same encoding `put_entity` uses.

A field name containing `"` or `\` cannot be written as a SQLite JSON path member
without escaping rules that differ between the two kinds, so it is refused naming the
field.

### 5. Output: the `seams plan` Markdown, and exit 1 as the deploy refusal

- **The plan gains a section, "Stored-data migrations"**, after the breaking and
  compatible changes: one fenced `sql` block per store kind and shape, its statements in
  the sorted order, then a list of the refusals, each naming the shape and path as
  CURIEs and the reason.
- **Each refusal is also printed on stderr** as `seams plan: refused <shape> <path>
  (<kind>): <reason>`, after the summary line.
- **The exit code is 1 when there is any refusal.** A refusal is a breaking change, so
  the exit code `seams plan` already gives breaking changes does not change; what a
  refusal adds is the named stderr line, which is the deploy refusal. A deploy that
  reads the plan must not proceed while a refusal line is present.
- **Nothing runs the SQL.** `seams plan` writes it and the runtime never migrates on
  start. The operator stops the old runtime, runs the block for the deployed store kind
  in one transaction, and starts the new one. Same model pair, same bytes: the plan
  holds no timestamp, no path and no store URL.

### 6. Out of scope

- **The C4 LLM draft path.** The LLM note suggested drafting migrations for the
  refused cases with the C4 draft generator. Drafts are not deterministic and need
  review; they are left to C4.
- **Running migrations**, either from the runtime or from a deploy tool (section 5).

## Alternatives considered

- **A distinct exit code for refusals** (say 3). Rejected for now: `seams plan` and
  `seams diff` share their exit codes (D053), 2 already means a model that cannot be
  loaded, and the CI job reads 1 as "warn". The refusal is told apart by its stderr
  lines and its plan section.
- **Only the SQL of the store kind the shape's store declares.** Rejected: the
  development override can run the same model on SQLite (section 4), and a plan that
  omits the SQL for the store in use would be wrong for that deploy.
- **Running the migration from the runtime on start.** Rejected: a runtime that rewrites
  data before anyone has read the plan turns a reviewable change into an implicit one,
  and two runtimes starting together would race.
- **Deleting the rows of a removed shape.** Rejected: losing every instance of a shape
  is not a mechanical consequence of removing it; the operator decides (section 3).
- **Filling a required field with a type's zero value** when no `sh:defaultValue` is
  stated. Rejected: the value would be a domain fact the model does not state
  (principle 1).

## Consequences

- `packages/seams-cli` gains `seams_cli.migrations` (S03/T02), tested with inline TriG
  and a real `SQLiteStore` file.
- `seams plan` gains the "Stored-data migrations" section and the refusal lines
  (S03/T03); its existing sections and summary line stay as they are.
- A model author who adds a required field to a stored shape adds a `sh:defaultValue`
  for the rows already stored, or takes the refusal to the operator. The guide says so
  (S03/T04).

## Open questions

- **A renamed field.** The diff matches fields by name, so a field whose `sh:name`
  changes on the same path is one `property-removed` and one `property-added`. The
  migration drops the old key, and the new one is filled with the default or refused;
  moving the value to the new key is not decided here.
- **A renamed shape.** `shape-renamed` is compatible, but the rows keep the old IRI in
  `entities.shape`, and the runtime queries by the new one. Rewriting the `shape` column
  on a rename is left to a later slice.
- **A tightened `sh:minCount` with a default.** Raising `sh:minCount` from 0 on a
  property that states `sh:defaultValue` could be filled as an added field is (section
  3); it is refused until a model needs it.
- **Process state.** Instance state in `workflow_state` (`workflow.data["seams"]`) keeps
  copies of current entities; this ADR rewrites `entities` only.

## Revision notes

None yet.

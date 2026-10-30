# semanticseams

The `seams` library: import name `seams`, distribution name `semanticseams`.

It reads Semantic Seams models without executing them. Its only dependencies
are rdflib and lxml; importing it never pulls in SpiffWorkflow, FastAPI or
`seams_runtime`. The package is strictly type-checked (`uv run pyright`).

## API

```python
import seams

model = seams.load("examples/chat-app/chat-app.trig")
model.hash        # "sha256:..."
model.payloads()  # [("chat_process.bpmn", Path(...)), ("routing.dmn", Path(...))]
```

- `seams.load(path=None) -> Model` loads a model.
  - A **file** is parsed as TriG; payloads resolve against its directory.
  - A **directory** loads every `*.trig` directly inside it (not recursive,
    sorted by file name) into one Dataset; payloads resolve against the
    directory. A directory with no `*.trig` raises `FileNotFoundError`.
  - Without a path, the `SEAMS_MODEL` environment variable names the model.
    An explicit path always wins; an unset or empty variable raises
    `ValueError`.
- `Model` exposes `path`, `base_dir`, `files` (the TriG files loaded), `ds`
  (the merged rdflib `Dataset`, `default_union=True`), `subject`, `curie(term)`,
  `label(iri)`, `payload_path(model_iri)` and:
  - `hash`: computed once per instance.
  - `payloads()`: `(relative posix path, absolute path)` for every
    `seam:renderPayload`, sorted by relative path. A missing payload raises
    `ResolutionError`.
- `seams.model_hash(path)` and `seams.payload_path(payload_iri, base_dir)` are
  module-level helpers.
- Errors: `SeamsError` (base; `http_status`, `to_dict()`) and
  `ResolutionError(subject, predicate, detail="")`, also a `LookupError`,
  raised when a graph hop is missing.
- Namespaces: `SEAM`, `COMM`, `DEC`, `PROC`, `STATE`, `HYDRA`, `ODRL`,
  `DEPLOY`, `IFML`, plus `local_name(iri)`.

## The model hash

`"sha256:<hex>"`, where each payload is framed as relative path, NUL, decimal
length, bytes, sorted by relative path:

- **File:** the TriG bytes, then the framed payloads. This is byte-identical
  to the hash embedded in generated code (`model-hash:` headers).
- **Directory:** each TriG file framed the same way (its name, sorted by
  name), then the framed payloads.

Editing or renaming the model or any payload changes the hash.

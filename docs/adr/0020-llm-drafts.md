# ADR-0020: LLM Drafts — `seams propose` Calls a Provider Command and Keeps a Draft Only When Its Acceptance Tests Pass

**Status:** Accepted

**Date:** 2026-11-03

**Source:** milestone M022/S04; backlog C4; decision D059; research note
[An LLM generator for the code templates cannot write](../research/2026-10-31-llm-generator.md)
sections 3.3 and 3.6; builds on [ADR-0012](./0012-operation-implementation.md) (the
handlers package) and [ADR-0019](./0019-generation-trace.md)

## Context

Templates cannot write a service task's body. C3 assembles the facts the body depends
on with a context hash, C1 writes a typed stub, and C2 generates acceptance tests that
check a body against the model. C4 asks an LLM for the body. The research note left open
whether drafts should pin a provider and model, cache the response, or allow any
provider, and its section 3.6 sets safety rules: model text only as quoted data, binding
names but never values, never run in CI, nothing accepted without passing tests and
review.

## Decision

1. **The provider is a command.** `seams propose TASK` runs the command named by
   `[propose] provider` in `seams.toml`, or by `--provider`, split with `shlex` and run
   without a shell. The prompt goes to its stdin and the draft comes from its stdout;
   one fenced code block, if present, is stripped. No provider SDK, API key or network
   code is in the repository, so any LLM (or a person, or a fake in tests) can answer.
   A non-zero exit, empty output or a timeout is a provider failure.
2. **The prompt is deterministic and versioned.** `seams_cli.propose.build_prompt`
   fills `prompts/draft-v1.txt` (the version is in the file name) from the C3 manifest,
   the C1 stub and the C2 tests. Every piece of model text, labels, comments and native
   BPMN and DMN fragments, sits in a fenced DATA block the prompt says is data, not
   instructions. Bindings appear by name only; no secret value is read.
3. **Responses are cached, providers are not pinned** (the model is now named; see the amendment below). A successful response is stored
   in `.seams/drafts/<sha256(context hash, template, provider)>.py` (gitignored). The
   same context, template and provider re-run free and give the same draft; a changed
   fact changes the context hash and misses the cache. Failed calls are not cached.
4. **A draft is kept only when it passes.** The project is copied to a scratch
   directory, the draft is written at the handlers module's path there, and the
   module's acceptance tests run with pytest. Only on pass is the draft written to the
   handlers package (ADR-0012), and only there: a target outside the handlers directory
   is refused, and an existing module is replaced only with `--force`. On failure
   nothing is written and each failing test is named.
5. **Accept once, then own.** An accepted draft is an ordinary hand-owned file.
   `seams generate` never touches it. Recording its context hash, template, provider and
   file hash in `seams.lock`, and reporting staleness, is C5.
6. **Never in CI.** CI runs the acceptance tests against committed handlers; it calls no
   provider. The tests of `seams propose` use fake provider scripts.

## Lock record and staleness

C5 (M022/S05) records each accepted draft in `seams.lock` under a top-level `drafts`
list, sorted by task: the task IRI, the module path relative to the project root, the
task's context hash, the template, the provider command and the hex sha256 of the
written file. Only an accepted draft is recorded; a rejection leaves the lock alone,
and `seams generate` carries the records forward. `seams check` recomputes each
task's context hash with `seams.context_for`, as `build_prompt` does, and reports
`draft-stale` when it differs or the task no longer resolves, so a draft is reviewed
again whenever a fact it was written from changes. It reports `draft-hand-edited`
when the file's sha256 differs from the record or the file is missing. Both are
problems, not warnings; accepting a new draft (`--force`) refreshes the record.

## Amendment: the model is pinned by name (M027/S05, D063, backlog X11)

Rule 3 said providers are not pinned. The provider command is still the pinned
provider, but a command such as `my-llm` does not say which model answered. So a
project may now name the model:

- **By name only.** `[propose] model` in seams.toml, or `--llm-model` (which wins),
  is a non-empty string; anything else is a ProjectError naming `propose.model`.
  `seams` checks nothing else about it and adds no SDK or network code: the
  provider gets it as the environment variable `SEAMS_LLM_MODEL` and decides what to
  do with it. Without a name the variable is removed from the provider's
  environment, so an inherited value cannot change the answer without changing the
  key. The flag and the variable are not `--model` and `SEAMS_MODEL`, because those
  already name the TriG model (D034).
- **In the cache key.** The key is sha256(context hash, template, provider, model).
  The model is added only when one is named, so keys made before this amendment
  still hit, and asking for another model misses the cache.
- **In the lock.** An accepted draft's record gets `model` when one was named. Without
  one the key is absent, so existing locks keep their bytes. The command prints an
  `llm-model <name>` line after `provider`.
- **No SemPKM copilot connection.** `seams` does not reuse SemPKM's copilot
  connection or its credentials; the provider command stays the only way to reach a
  model.
- **The same for suggest and draft-generator.** `seams suggest` (ADR-0028) and
  `seams draft-generator` (ADR-0029) take the same `[propose] model` and
  `--llm-model`, pass the same variable, add the name to their own cache keys only
  when one is named, and print the same `llm-model <name>` line after `provider`.
  A stored suggestion records it as `llm_model` in its `suggestion.json`. Neither
  writes a lock record, so the lock field is propose's alone.
- **Still never in CI** (rule 6): the tests use fake provider scripts that echo the
  model name they get.

## Consequences

- The command prints `task`, `context`, `template`, `provider`, `cache hit|miss` and
  `draft <sha256>`, then `tests passed` and `wrote <module>` (exit 0) or one
  `failed <test>` line per failure (exit 1). A provider failure exits 1; a project
  error exits 2.
- Changing the prompt text means a new template file (`draft-v2.txt`), which also
  invalidates cached drafts.
- Passing tests is the machine half of acceptance; reviewing the written file before
  committing it stays the person's half.

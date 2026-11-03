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
3. **Responses are cached, providers are not pinned.** A successful response is stored
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

## Consequences

- The command prints `task`, `context`, `template`, `provider`, `cache hit|miss` and
  `draft <sha256>`, then `tests passed` and `wrote <module>` (exit 0) or one
  `failed <test>` line per failure (exit 1). A provider failure exits 1; a project
  error exits 2.
- Changing the prompt text means a new template file (`draft-v2.txt`), which also
  invalidates cached drafts.
- Passing tests is the machine half of acceptance; reviewing the written file before
  committing it stays the person's half.

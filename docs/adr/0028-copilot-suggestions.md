# ADR-0028: Copilot Suggestions — `seams suggest` Asks a Provider Command for a Model Change and Applies It Only on Accept

**Status:** Accepted

**Date:** 2026-11-04

**Source:** milestone M025/S01; backlog R2; decision D061; research note
[A data-centric model, SemPKM as its store, and a model copilot](../research/2026-10-31-data-centric-model-and-copilot.md)
section 5; builds on [ADR-0020](./0020-llm-drafts.md) (the provider command) and
[ADR-0017](./0017-write-path-and-editor.md) (the one write path)

## Context

R2 asks an LLM to propose improvements to the model itself, not to code: move logic
into DMN, merge shapes into a class, anchor classes in gist. Each proposal must be
validated, regenerated and reviewed before it changes the model. C4 (ADR-0020) already
calls an LLM through a provider command and keeps a draft only when its acceptance tests
pass. The research note left open whether the model copilot should reuse that
connection or SemPKM's AI copilot, which talks to OpenAI-compatible endpoints.

A model change is riskier than a handler draft: it touches the TriG seams graph and the
native BPMN and DMN payloads, which every generator reads. An LLM writing those bytes
directly could break IRIs (ADR-0002), the seams graph (ADR-0001) or a modeler's XML
layout, and its output would not be repeatable.

## Decision

1. **The provider is ADR-0020's command (D061).** `seams suggest` runs the command named
   by `[propose] provider` in `seams.toml`, or by `--provider`, through the same helper
   as `seams propose`: prompt on stdin, answer on stdout, no shell, no SDK, no key, no
   network code in the repository. SemPKM's copilot connection is not used; it would
   make a model-authoring tool depend on a running SemPKM. A non-zero exit, empty output
   or a timeout is a provider failure. The LLM model can be named too, with
   `[propose] model` or `--llm-model`; it joins the cache key when named
   ([ADR-0020](0020-llm-drafts.md)'s amendment, M027/S05, backlog X11).
2. **The answer is a structured suggestion, from a versioned prompt.**
   `prompts/suggest-v1.txt` (the version is in the file name) is filled
   deterministically from the model. Model text, labels, conditions and native BPMN and
   DMN fragments sit in fenced DATA blocks the prompt says are data, not instructions,
   as in `draft-v1.txt`. The prompt ends with the JSON answer schema, and the answer
   must be one JSON object of a named kind. Anything else, or a suggestion naming a
   gateway, flow, field or decision the model does not have, is rejected with a
   `GeneratorError` or `ResolutionError` that names the fact.
3. **The first kind is `condition-to-dmn`.** A gateway whose outgoing conditions compute
   over names no upstream decision sets (form fields a user task writes, for example
   `amount > 100`) is an inline rule. The suggestion names the gateway's BPMN id, a
   decision id and name, its input field names, its output variable, its rules (input
   tests mapped to output values) and the new condition for each outgoing flow. Applied,
   it gives:
   - a DMN decision added to the process's existing DMN payload;
   - a `businessRuleTask` inserted before the gateway in the BPMN payload, with its
     `seam:decidedBy` and the other seam links the model's existing business-rule tasks
     carry;
   - `dec:Decision` facts (inputs with `dec:variable` and `dec:fromPath`, the output's
     `dec:processVariable`, `seam:reads`, `dec:payloadElement`) shaped like the
     decisions already in the model;
   - each flow's condition rewritten over the decision's output variable.
4. **Deterministic code builds the change.** The LLM only proposes. `build_change`
   turns a parsed suggestion into a `seams_edit` `Patch` for the TriG facts and new
   payload texts for the BPMN and DMN files, editing the XML with lxml and keeping the
   modeler's layout as `seams_edit.xml` does. Every name comes from the model or the
   suggestion; none is hard-coded. The same model and the same answer give the same
   bytes.
5. **Checked in a scratch copy.** The project is copied to a temporary directory and the
   change is written there through `seams_edit` (`files.apply`, `xml.save_payload`).
   The copy must pass the seam shapes and `seams.decisions_check.decision_findings`,
   and must generate. A failure is reported with the subject and predicate of each
   finding, and nothing is stored.
6. **A passing suggestion is pending, not applied.** It is stored under
   `.seams/suggestions/<id>/` (gitignored, like `.seams/drafts/`): `suggestion.json`
   and one unified diff per changed file. The id is the sha256 of the model hash, the
   template, the provider command and the response. The provider response is cached by
   (model hash, template, provider), so a re-run on the same model is free; a changed
   model misses the cache. Failed calls are not cached.
7. **A person accepts.** `seams suggest --accept ID` re-checks the suggestion against the
   current model hash and applies it through `seams_edit`, the one write path. A stale
   id (the model changed since the suggestion was made) is refused; asking again makes a
   fresh one. `--list` shows pending suggestions. After accept the change is ordinary
   model text the modeler owns and commits after review.
8. **Never in CI.** CI calls no provider. The tests of `seams suggest` use fake provider
   scripts, and the change builder is tested with suggestions built test-side.

## Later kinds

The same loop (prompt, JSON suggestion, deterministic patch, scratch check, pending,
accept) carries the other two R2 kinds, each with its own template version and builder:

- **`merge-shapes`**: shapes with the same properties become one target-classed shape
  (ADR-0023) on an ontology class, with the forms and decisions that read them
  repointed.
- **`gist-anchor`**: an ontology class without a gist superclass gets a proposed
  `rdfs:subClassOf` a gist class (ADR-0022), for a person to confirm.

Neither is built in M025/S01.

## Consequences

- The command prints the suggestion id, the files changed, the validation and
  regeneration verdicts and `cache hit|miss`, and exits 0 when a suggestion is stored or
  applied. A rejection names the subject and predicate and exits 1; a provider failure
  exits 1; a project error exits 2.
- Changing the prompt text means a new template file (`suggest-v2.txt`), which also
  invalidates cached answers and suggestion ids.
- Passing the shapes, the decision checks and generation is the machine half of
  acceptance; reading the diff before `--accept` and before committing stays the
  person's half.
- Applying through `seams_edit` keeps TriG layout, payload layout and undo as the editor
  has them; no new write path is added.

# ADR-0029: LLM-Drafted Generators — `seams draft-generator` Asks a Provider Command for a Template and Extract Step and Keeps Them Only When the Golden Test Passes

**Status:** Accepted

**Date:** 2026-11-04

**Source:** milestone M025/S02; backlog R3; decision D062; research note
[A data-centric model, SemPKM as its store, and a model copilot](../research/2026-10-31-data-centric-model-and-copilot.md);
builds on [ADR-0020](./0020-llm-drafts.md) (the provider command),
[ADR-0028](./0028-copilot-suggestions.md) (the structured answer and scratch check) and
`seams new-generator` (backlog K5, the reference-first scaffold)

## Context

`seams new-generator NAME --reference FILE` turns a hand-written reference output into a
generator package whose golden test passes as written: the template is the reference
verbatim, every golden line is `[fixed]`, and `extract` returns only the model hash.
The author then repeats one loop ([Write your own generator](../guide/write-your-own-generator.md#start-from-a-reference-output)):
pick a literal the model holds, read it in `extract`, replace it in the template with a
view-model field, and change the golden marker to `[graph: ...]`. That loop is
mechanical enough for an LLM to draft and strict enough for a test to judge.

R3 asks for exactly that: an LLM drafts the template and the `extract` step from a
reference output, accepted when the golden test passes. C4 (ADR-0020) and R2
(ADR-0028) already settle how an LLM is called and how its answer is checked before
anything is written. What is left to decide is the command, what the prompt holds, the
shape of the answer and what "passes" means for a generator.

## Decision

### 1. The command

```sh
seams draft-generator NAME --reference FILE [--provider CMD] [--out DIR] [--force] [--project DIR]
```

`NAME` and `FILE` follow `seams new-generator`: the same name rule, the same suffixes,
the same refusals of a reference the scaffold could not make a passing test from. `DIR`
defaults to `seams-<name>`. It must not exist or be empty, unless `--force` is given,
which lets the package's files replace files of the same path in `DIR`. The model is the
project's (`seams.toml`, found from `--project` or the working directory), and the
cache lives below that project.

### 2. The provider is ADR-0020's command

The provider is the command named by `[propose] provider` in `seams.toml`, or by
`--provider`, run through `seams_cli.propose.call_provider`: split with `shlex`, no
shell, prompt on stdin, answer on stdout. No SDK, key or network code is added. A
non-zero exit, empty output or a timeout is a provider failure. The LLM model can be
named too, with `[propose] model` or `--llm-model`; it joins the cache key when named
([ADR-0020](0020-llm-drafts.md)'s amendment, M027/S05, backlog X11).

### 3. The prompt is deterministic and versioned

`prompts/draft-generator-v1.txt` (the version is in the file name) is filled by
`seams_cli.draft_generator.build_prompt` from three things, each in a fenced DATA block
the prompt says is data, not instructions (`propose.quote`):

- the reference file, verbatim, with its file name;
- the model's names: one `IRI<TAB>label` line for every labelled subject of the loaded
  model, sorted by IRI;
- the scaffold's package module, so the answer knows the imports, the `render`
  environment and the `[[ ]]` / `[% %]` delimiters it fills in.

The same reference and the same model give the same prompt bytes; the command prints
the prompt's sha256. Nothing else of the project, and no secret, goes into the prompt.

### 4. The answer is one JSON object

The provider answers with one JSON object, with exactly these string keys:

| Key | Holds |
|---|---|
| `extract` | Python source of the extract step: the imports it needs and `def extract(trig: Path, out: Path) -> dict`, returning the view model. It replaces the scaffold's `extract`; `render`, `sources` and `generator` stay the scaffold's. |
| `template` | The template text, written to `<package>/templates/<reference name>`. |
| `golden` | The golden text, written to `tests/golden/<reference name>`, with a `[fixed]` or `[graph: ...]` marker on every non-blank line. |

One fenced code block around the object is stripped, as in ADR-0020. Anything else (not
JSON, not an object, a missing or extra key, a non-string value) is a
`DraftGeneratorError` that names the key.

### 5. Acceptance

A draft is accepted only when all three hold:

1. **The golden test passes.** `new_generator.scaffold(NAME, FILE)` is assembled with the
   answer's extract step, template and golden in place of its own and written to a
   scratch directory. There `python -m pytest -q -p no:cacheprovider tests` runs with
   the scratch package on `PYTHONPATH` and `SEAMS_MODEL` set to the project's model. The
   scaffold's four tests (golden match, determinism, output parses, sources name the
   files) must exit 0. A failure names each failed test, with scratch paths scrubbed.
2. **The template restates no model fact.** No label from the prompt's model names that
   occurs in the reference may occur in the template: such a value has to come from
   `extract` ([principle 1](../project/principles.md#_1-the-model-is-the-source-of-truth)).
   The error names the template line and the label.
3. **The template holds no logic.** Only `[[ name ]]` or `[[ name.attr ]]`,
   `[% for x in xs %]` and `[% endfor %]` are allowed. `[% if`, `[% set`, filters (`|`),
   calls, operators and `[#` comments are refused, naming the line
   ([templates hold text, not logic](../project/principles.md#templates-hold-text-not-logic)).

### 6. The cache

A response that was accepted is stored in
`.seams/generator-drafts/<key>.json` (gitignored, like `.seams/drafts/`), where `key` is
the sha256 of the reference's sha256, the model hash, the template name and the
provider command. A re-run with the same reference, model and provider is free and gives the same
package; a changed reference or model misses the cache. Rejected answers and failed
calls are not cached. The command prints `cache hit` or `cache miss`.

### 7. Write nothing on failure

Every check runs before the output directory is touched; the package is written with
`new_generator.write` only after acceptance. Any error, from the arguments, the
provider, the answer or the scratch tests, leaves `DIR` and the cache as they were.

### 8. Accept once, then own

The written package is an ordinary hand-owned generator that runs without an LLM, as
`seams new-generator`'s does. Reviewing it, installing it and adding `sources` for the
elements it reads stay the author's work.

### 9. Never in CI

CI calls no provider. The tests of `seams draft-generator` use fake provider scripts
under `tests/fixtures/draft_generator/`, and a cache-hit test uses a provider that fails
if it runs.

## Alternatives

- **Let the LLM write the whole package.** Rejected: the pyproject, `render`, the tests
  and the delimiters are already right in the scaffold, and letting the answer change
  them would let it weaken the test that judges it.
- **Accept on the golden test alone.** Rejected: a template that copies the reference
  passes the golden test on the model it was drawn from, which is the scaffold, not a
  draft. The restated-label and no-logic checks are what make the draft a generator.
- **Ask for a unified diff against the scaffold.** Rejected: diffs from an LLM apply
  badly, and three whole texts are simpler to check and cache.

## Consequences

- On success the command prints the prompt hash, `cache hit|miss`, `tests passed` and
  each written path, and exits 0. Any error prints `seams draft-generator: <error>` on
  stderr, with one line per failed test for a golden failure, and exits 1.
- Changing the prompt text means a new template file (`draft-generator-v2.txt`), which
  also invalidates cached answers.
- `seams new-generator` keeps its output byte for byte: the scaffold's package module
  takes the extract step as a parameter, and its default is the current one.
- Passing the tests is the machine half of acceptance; reading the drafted template,
  `extract` and golden before committing stays the person's half.

"""Command line: ``seams generate|check|migrate|status|sequence|secrets|context [--project PATH] [--model PATH]``, ``seams diff|plan OLD NEW``,
``seams generate|check|migrate|status|secrets PATH`` (PATH: a project or a model, see ``_fold_path``),
``seams propose TASK [--provider CMD] [--force]``,
``seams suggest [--provider CMD] [--list | --accept ID]``,
``seams coverage [MODEL | --project PATH]``, ``seams new-generator NAME --reference FILE [--out DIR]``.

``--project`` is a seams.toml file or a directory holding one (default: the
working directory); ``--model`` overrides the project's model. Each written
path is printed, relative to the working directory when it lies below it.

The project's seams.lock (D043) records every output; generate rewrites it
last and prints its path. An output the old lock lists but no generator writes
any more is deleted and printed as ``removed <path>`` when it is a regular file
still matching its locked hash; otherwise it is kept and reported on stderr as
``kept hand-edited orphan``. A locked output edited by hand is reported as
``overwrote hand-edited``, a deleted one as ``restored deleted``; both are
rewritten and the exit code stays 0. A malformed seams.lock exits 2 before
anything is written.
A ProjectError or GeneratorError prints ``seams generate: <message>`` to
stderr and exits 2; a file that cannot be read or written exits 1.
``seams generate --lenient`` (D057) does not stop on a violated generator
precondition or a GeneratorError: it writes what the generators produced,
records the faults in seams.lock, prints each to stderr as
``seams generate: fault <generator>: <focus>: <shape>: <message>``, then
``seams generate: N fault(s); output is flagged``, and exits 0.
A sh:Warning result of the precondition check (a deprecated vocabulary term,
ADR-0021) prints as ``seams generate: warning <focus> <path> <message>`` and
changes neither the outputs nor the exit code.

``seams check`` (D044) writes nothing. It validates the model against the
SHACL shapes, runs the project's gate queries and compares the outputs
generate would write with the disk and seams.lock. Each finding prints to
stdout as ``<kind> <detail>``; with any finding that is not advisory
(``review``, ``shacl-warning`` and ``vocabulary-migrated`` are,
ADVISORY_KINDS), ``seams check: N problem(s)`` counting only those goes to
stderr and the exit code is 1. With advisory findings only,
``seams check: N warning(s)`` goes to stderr and the exit code is 0. A model that cannot be loaded, a bad
gate or a malformed seams.lock exits 2. With ``coverage = ["paths"]`` in the
project file, each BPMN path no scenario runs is a ``coverage`` finding too.
A seams.lock that records faults is a ``flagged`` finding, a problem; check
runs the generators leniently, so a generator fault is never an exit 2 here.

``seams status [--env NAME] [--timeout SECONDS]`` (D045) GETs /healthz from
each runtime container of the model at the base URL that
``[environments.<name>].endpoints`` gives it, and prints
``<container> <verdict> <reported hash or -> <detail>`` per container, sorted,
then ``current model <hash>``. A verdict is current, behind (the hash is in
seams.lock's git history), ahead (it is not) or unreachable. With any container
not current, ``seams status: N of M not current`` goes to stderr and the exit
code is 1. ``--env`` defaults to the only environment with endpoints; a missing
or unknown environment, or an endpoint that is not a runtime container, exits 2.

``seams sequence <event> [--out DIR]`` (D047) derives the as-designed Mermaid
sequence diagrams of an IFML event (a CURIE, local name or IRI), one per
gateway path, writes each as ``<DIR>/<name>.mmd`` (default
``<project root>/sequences``) and prints each path. Each fact the deriver
could not place prints to stderr as ``seams sequence: gap <name>: <detail>``;
gaps are an audit, and the exit code stays 0. An unknown event exits 2.
``--trace RUN`` draws one recorded run as ``<DIR>/<event>.executed.mmd`` from
the worker's trace rows: RUN is a trace JSON file or an instance id in the
runtime's SQLite store (``--db PATH``, default SEAMS_DB, else
``<project root>/seams.sqlite``). A missing instance exits 2; ``--db``
without ``--trace`` is a usage error.

``seams diff OLD NEW [--json]`` (D052) compares two model versions, each a
TriG file or a directory, and classifies every SHACL shape and operation
contract (seam:acceptsShape, seam:returnsShape) change as compatible or
breaking. Each change prints as ``<verdict> <kind> <subject> <detail>``,
sorted, with CURIEs where a prefix is bound; ``--json`` prints the changes,
their data/contract scopes and the counts instead. With any breaking change,
``seams diff: N breaking, M compatible`` goes to stderr and the exit code is 1.
A model that cannot be loaded exits 2. It reads no seams.toml.

``seams plan OLD NEW [--output FILE]`` (D053) writes a Markdown change plan:
the breaking and compatible changes ``seams diff`` finds, then the elements
each layer adds and removes, as CURIEs. OLD and NEW are model paths or git
``REF:PATH`` specs, extracted with ``git archive``. The plan goes to stdout,
or to FILE, whose path is then printed. Exit codes and the stderr summary
(``seams plan: N breaking, M compatible``) are diff's; an unknown ref or a
failing git exits 2.

``seams coverage [MODEL | --project PATH] [--json]`` (D054) lists what the
model declares that nothing exercises: each BPMN path no verify:Scenario runs
(``path <process> <node>...``), each state:Transition nothing seam:fires
(``transition <lifecycle> <transition>``) and each odrl:permission with no
party deny test (``policy <policy> <target> <assignee>``), with full IRIs.
MODEL is a TriG file or a directory; without it the project's model is used.
``--json`` prints the three lists and their counts instead. With any gap, a
count of each goes to stderr as ``seams coverage: ...`` and the exit code is
1; a model that cannot be loaded exits 2.

``seams migrate [--project PATH] [--model PATH]`` (ADR-0021) writes the
vocabulary migrations ``seams.load`` would apply in memory into the model's
TriG files, as one patch through the seams_edit text writer (ADR-0017), so
comments and layout survive. Each step prints as
``migrated <vocabulary> <from> <to>``, then each written file's path. A model
already on the shipped vocabularies prints ``seams migrate: nothing to
migrate`` to stderr, writes nothing and exits 0. A newer model, a missing
step or a patch the writer refuses exits 2 and writes nothing.

``seams secrets [--env NAME] [--write-example] [--json]`` (M016/S04) lists
every configuration key of each arch:Environment's containers, as
``Container.for_environment`` merges them, and prints
``<env> <container> <key> <kind> <verdict> <source or ->`` per binding. A kind
is value, secret-ref, secret-file or service; a source is a secret name, a
secret file path relative to the project root or a service container, never
a value. Values and services are present; a secret file is present when its
path exists (it is never opened); a key named in ``<project root>/.env`` is
present (only key names are read); a secret-ref name is checked against
``docker secret ls``, and is unchecked, with the reason on stderr, when docker
is missing or fails. ``--json`` prints the rows and counts instead. With any
missing row, ``seams secrets: N missing`` goes to stderr and the exit code is 1.
``--write-example`` writes ``<project root>/.env.example`` for ``--env``, else
development, else the first environment: keys sorted, plain values with their
model literal, secrets blank under a ``# secret: <kind> <source>`` comment. An
unknown environment or a model fault (ResolutionError) exits 2.

``seams context TASK [--json]`` (M022/S01, backlog C3) prints the context
manifest of a service task (a BPMN id, CURIE or IRI): ``task <iri>``, one
``<kind> <ref> <hash>`` line per model fact or native file fragment its code
depends on, sorted by (kind, ref), then ``context <hash>``. ``--json`` prints
the same with sorted keys. Refs are IRIs or model-relative ``path#id``. An
unknown task, one that is not a service task, or a missing hop prints
``seams context: <message>`` to stderr and exits 1; a model that cannot be
loaded exits 2. It writes nothing.

``seams propose TASK [--provider CMD] [--force]`` (M022/S04, backlog C4, D059)
sends the task's draft prompt to the provider command, runs the handlers
module's acceptance tests against the draft in a scratch copy and prints
``task``, ``context``, ``template``, ``provider``, ``cache hit|miss`` and
``draft <sha256>`` lines. On pass it prints ``tests passed`` and ``wrote
<handlers module>`` and exits 0; on failure one ``failed <test>`` line per
failing test, the pytest output on stderr, writes nothing and exits 1. A
failed provider exits 1; no provider, an unknown task or an existing module
without ``--force`` exits 2.

``seams suggest [--provider CMD]`` (M025/S01, backlog R2, ADR-0028) sends the
suggest-v1 prompt, built from every gateway whose conditions read a name no
upstream decision outputs, to the provider command, and reads one
``condition-to-dmn`` JSON answer. It builds the change, checks it in a scratch
copy and prints ``template``, ``provider``, ``model``, ``cache hit|miss``,
``suggestion <id>``, ``gateway <iri>``, one ``changed <file>`` per file and
``validated pass|fail`` and ``generated pass|fail (N outputs)``. A passing
suggestion is stored pending under ``.seams/suggestions/<id>/``
(suggestion.json and one ``<file>.diff`` each), printed as ``stored <dir>``,
and the command exits 0; the model is not touched. A rejected answer prints
``rejected <kind> <subject> <predicate> <detail>`` per finding, stores and
caches nothing and exits 1, as does a failed provider. A model with no such
gateway prints ``seams suggest: nothing to suggest: ...`` to stderr, calls no
provider and exits 0. ``--list`` prints ``<id> <kind> <gateway> current|stale``
per pending suggestion. ``--accept ID`` (an id or a unique prefix) refuses a
suggestion made for another model hash (exit 1), rebuilds and re-checks the
change, writes it through seams_edit, prints ``accepted <id>`` and each
written file, and removes the pending directory. An unknown ID or no provider
exits 2.

``seams new-generator NAME --reference FILE [--out DIR]`` (M018/S04, backlog
K5) writes a generator package for the reference output FILE into DIR
(default ``./seams-<NAME>``): pyproject.toml with its ``seams.generators``
entry point, ``seams_<NAME>/__init__.py``, the reference verbatim as the
template, a golden marking every non-blank line ``[fixed]`` and a golden test
that passes as written (new_generator.py). Each written path is printed. A
refused name, reference or DIR (not empty) prints ``seams new-generator:
<message>`` to stderr, exits 2 and writes nothing. It reads no seams.toml.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import seams

from seams_edit import PatchError
from seams_gen import GeneratorError

from .check import ADVISORY_KINDS, FILE_KINDS, run_check
from .context import render as render_context
from .context import run_context
from .context import to_json as context_json
from .coverage import coverage_report, summary
from .coverage import to_json as coverage_json
from .diff import BREAKING, COMPATIBLE, diff_loaded, load_model, shorten, to_json
from .generate import apply, generate_project
from .lockfile import locate
from .migrate import migrate
from .new_generator import NewGeneratorError, new_generator
from .plan import render, resolve
from .project import PROJECT_FILE, ProjectError, load_project, resolve_model
from .propose import ProposeError, propose
from .secrets import EXAMPLE, example_environment, render_example, run_secrets
from .sequence import run_sequence
from .status import run_status
from .suggest import ChangeFinding, NothingToSuggest, StaleSuggestion, Verdicts, accept, pending, suggest

EXIT_PROJECT_ERROR = 2
EXIT_IO_ERROR = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seams", description="Work with a Semantic Seams project (seams.toml).")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")
    gen = sub.add_parser(
        "generate",
        help="rewrite every generated output the project file names",
        description="Run every generator of the project file and write its outputs.",
    )
    _project_arguments(gen, path=True)
    gen.add_argument(
        "--lenient",
        action="store_true",
        help="record precondition and generator faults in seams.lock instead of failing; the output is flagged",
    )
    gen.set_defaults(run=_generate)
    check = sub.add_parser(
        "check",
        help="fail on SHACL violations, gate rows and stale outputs; writes nothing",
        description="Validate the model, run the project's gate queries and compare the outputs with the disk.",
    )
    _project_arguments(check, path=True)
    check.set_defaults(run=_check)
    mig = sub.add_parser(
        "migrate",
        help="write the vocabulary migrations a model needs into its TriG files, keeping comments",
        description="Migrate the model's files to the shipped vocabulary versions through the one write path.",
    )
    _project_arguments(mig, path=True)
    mig.set_defaults(run=_migrate)
    status = sub.add_parser(
        "status",
        help="report whether each running runtime container is on the current model",
        description="Read each runtime container's /healthz in an environment and compare its model hash.",
    )
    _project_arguments(status, path=True)
    status.add_argument("--env", help="the [environments.<name>] to read (default: the only one with endpoints)")
    status.add_argument("--timeout", type=float, default=5.0, help="seconds to wait for each /healthz (default: 5)")
    status.set_defaults(run=_status)
    secrets = sub.add_parser(
        "secrets",
        help="check that each environment's configuration keys and secrets exist, without reading values",
        description="List every configuration binding per environment and check that its secret exists.",
    )
    _project_arguments(secrets, path=True)
    secrets.add_argument("--env", help="the arch:Environment to check, by local name (default: all)")
    secrets.add_argument(
        "--write-example",
        action="store_true",
        help="write <project>/.env.example for --env (default: development, else the first environment)",
    )
    secrets.add_argument("--json", action="store_true", help="print the rows and verdict counts as JSON")
    secrets.set_defaults(run=_secrets)
    sequence = sub.add_parser(
        "sequence",
        help="derive the Mermaid sequence diagrams of an IFML event, one per gateway path",
        description="Derive as-designed sequence diagrams from the model's graph facts and BPMN step order.",
    )
    sequence.add_argument("event", help="the IFML event: a CURIE (:send_message), local name or full IRI")
    _project_arguments(sequence)
    sequence.add_argument("--out", type=Path, help="the directory for the .mmd files (default: <project>/sequences)")
    sequence.add_argument(
        "--trace",
        metavar="RUN",
        help="draw one recorded run as <event>.executed.mmd: a trace JSON file or an instance id in the --db store",
    )
    sequence.add_argument(
        "--db", type=Path, help="the runtime's SQLite store (default: SEAMS_DB, else <project>/seams.sqlite)"
    )
    sequence.set_defaults(run=_sequence)
    diff = sub.add_parser(
        "diff",
        help="classify shape and operation-contract changes between two models as compatible or breaking",
        description="Compare the SHACL shapes and operation contracts of two model versions.",
    )
    diff.add_argument("old", type=Path, help="the old model: a .trig file or a directory")
    diff.add_argument("new", type=Path, help="the new model: a .trig file or a directory")
    diff.add_argument("--json", action="store_true", help="print the changes, scopes and counts as JSON")
    diff.set_defaults(run=_diff)
    plan = sub.add_parser(
        "plan",
        help="write a Markdown change plan (release notes) between two models or git REF:PATH specs",
        description="Write the breaking and compatible changes and the elements each layer adds and removes.",
    )
    plan.add_argument("old", help="the old model: a .trig file, a directory or a git REF:PATH")
    plan.add_argument("new", help="the new model, in the same forms")
    plan.add_argument("--output", type=Path, help="write the plan to this file instead of stdout")
    plan.set_defaults(run=_plan)
    coverage = sub.add_parser(
        "coverage",
        help="list the BPMN paths, transitions and policies no scenario or test exercises",
        description="Report unexercised BPMN paths, unfired transitions and permissions without a deny test.",
    )
    coverage.add_argument(
        "model", type=Path, nargs="?", help="the model: a .trig file or a directory (default: the project's model)"
    )
    coverage.add_argument(
        "--project", type=Path, default=Path("."), help="seams.toml or a directory holding one (default: .)"
    )
    coverage.add_argument("--json", action="store_true", help="print the three lists and their counts as JSON")
    coverage.set_defaults(run=_coverage)
    context = sub.add_parser(
        "context",
        help="list the model facts and file fragments a service task's code depends on, each hashed",
        description="Print the context manifest of a service task: per-item hashes and a context hash.",
    )
    context.add_argument("task", help="the service task: a BPMN id (send_now), CURIE or full IRI")
    _project_arguments(context)
    context.add_argument("--json", action="store_true", help="print the manifest as JSON")
    context.set_defaults(run=_context)
    prop = sub.add_parser(
        "propose",
        help="draft a service task's handler body with an LLM command; keep it only if its acceptance tests pass",
        description="Send the task's draft prompt to the provider command, test the draft and write it on pass.",
    )
    prop.add_argument("task", help="the service task: a BPMN id (send_now), CURIE or full IRI")
    _project_arguments(prop)
    prop.add_argument(
        "--provider", help="the provider command (prompt on stdin, draft on stdout); overrides seams.toml"
    )
    prop.add_argument("--force", action="store_true", help="replace an existing handlers module")
    prop.set_defaults(run=_propose)
    sug = sub.add_parser(
        "suggest",
        help="ask an LLM command for a model change (an inline gateway rule into DMN); keep it pending for review",
        description=(
            "Send the suggest prompt to the provider command, build and check the change in a scratch copy, "
            "and store it under .seams/suggestions/ until --accept applies it."
        ),
    )
    _project_arguments(sug)
    sug.add_argument(
        "--provider", help="the provider command (prompt on stdin, JSON answer on stdout); overrides seams.toml"
    )
    action = sug.add_mutually_exclusive_group()
    action.add_argument("--list", action="store_true", help="list the pending suggestions, current or stale")
    action.add_argument("--accept", metavar="ID", help="apply the pending suggestion ID (or a unique prefix)")
    sug.set_defaults(run=_suggest)
    new = sub.add_parser(
        "new-generator",
        help="scaffold a generator package, with a passing golden test, from a reference output file",
        description="Write a generator package whose template is the reference output and whose golden test passes.",
    )
    new.add_argument("name", help="the generator and entry-point name: lowercase letters, digits and underscores")
    new.add_argument(
        "--reference", type=Path, required=True, help="the reference output: a .py, .yaml, .yml or .html file"
    )
    new.add_argument("--out", type=Path, help="the package directory, absent or empty (default: ./seams-<name>)")
    new.set_defaults(run=_new_generator)
    return parser


def _project_arguments(parser: argparse.ArgumentParser, *, path: bool = False) -> None:
    if path:
        parser.add_argument(
            "path",
            nargs="?",
            type=Path,
            metavar="PATH",
            help="seams.toml, a directory holding one, or the model (.trig): --project or --model by position",
        )
    parser.add_argument(
        "--project",
        type=Path,
        default=None if path else Path("."),
        help="seams.toml or a directory holding one (default: .)",
    )
    parser.add_argument("--model", type=Path, help="the model (.trig); overrides the project file and SEAMS_MODEL")


def _fold_path(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Fold the PATH positional into ``--project`` or ``--model``.

    A directory, a seams.toml or a path without a suffix is the project. Any
    other file is the model; its project is the seams.toml beside it, else
    ``--project`` (default: the working directory). Giving PATH and the flag it
    stands for is a usage error.
    """
    path: Path | None = args.path
    if path is not None and (path.is_dir() or path.name == PROJECT_FILE or not path.suffix):
        if args.project is not None:
            parser.error(f"{args.command}: give PATH or --project, not both")
        args.project = path
    elif path is not None:
        if args.model is not None:
            parser.error(f"{args.command}: give PATH or --model, not both")
        args.model = path
        if args.project is None and (path.parent / PROJECT_FILE).is_file():
            args.project = path.parent
    if args.project is None:
        args.project = Path(".")


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _generate(args: argparse.Namespace) -> int:
    project = load_project(args.project)
    model = resolve_model(project, args.model)
    generated = generate_project(project, model, lenient=args.lenient)
    applied = apply(project, model, generated)
    for fault in generated.faults:
        print(
            f"seams generate: fault {fault.generator}: {fault.focus}: {fault.shape}: {fault.message}", file=sys.stderr
        )
    for warning in generated.warnings:
        print(f"seams generate: warning {warning}", file=sys.stderr)
    report = applied.audit
    for kind, paths in (("overwrote hand-edited", report.edited), ("restored deleted", report.missing)):
        for rel in paths:
            print(f"seams generate: {kind} {_display(locate(project, rel))}", file=sys.stderr)
    for path in applied.kept:
        print(f"seams generate: kept hand-edited orphan {_display(path)}", file=sys.stderr)
    for path in sorted(generated.files):
        print(_display(path))
    for path in applied.removed:
        print(f"removed {_display(path)}")
    print(_display(applied.lock))
    if generated.faults:
        print(f"seams generate: {len(generated.faults)} fault(s); output is flagged", file=sys.stderr)
    return 0


def _check(args: argparse.Namespace) -> int:
    project = load_project(args.project)
    findings = run_check(project, resolve_model(project, args.model))
    for finding in findings:
        detail = _display(Path(finding.detail)) if finding.kind in FILE_KINDS else finding.detail
        print(f"{finding.kind} {detail}")
    problems = sum(finding.kind not in ADVISORY_KINDS for finding in findings)
    if problems:
        print(f"seams check: {problems} problem(s)", file=sys.stderr)
        return 1
    if findings:
        print(f"seams check: {len(findings)} warning(s)", file=sys.stderr)
    return 0


def _migrate(args: argparse.Namespace) -> int:
    project = load_project(args.project)
    result = migrate(resolve_model(project, args.model))
    for step in result.steps:
        print(f"migrated {step.vocabulary} {step.source} {step.target}")
    for path in result.files:
        print(_display(path))
    if not result.steps:
        print("seams migrate: nothing to migrate", file=sys.stderr)
    return 0


def _status(args: argparse.Namespace) -> int:
    project = load_project(args.project)
    model = resolve_model(project, args.model)
    statuses = run_status(project, model, args.env, args.timeout)
    for s in statuses:
        print(" ".join(part for part in (s.container, s.verdict, s.reported or "-", s.detail) if part))
    print(f"current model {seams.model_hash(model)}")
    behind = sum(s.verdict != "current" for s in statuses)
    if behind:
        print(f"seams status: {behind} of {len(statuses)} not current", file=sys.stderr)
        return 1
    return 0


def _secrets(args: argparse.Namespace) -> int:
    project = load_project(args.project)
    model, rows, problems = run_secrets(project, resolve_model(project, args.model), args.env)
    if args.json:
        counts = {v: sum(r.verdict == v for r in rows) for v in ("present", "missing", "unchecked")}
        print(json.dumps({"rows": [r.to_json() for r in rows], "counts": counts}, indent=2))
    else:
        for r in rows:
            print(f"{r.environment} {r.container} {r.key} {r.kind} {r.verdict} {r.source or '-'}")
    for problem in problems:
        print(f"seams secrets: unchecked: {problem}", file=sys.stderr)
    if args.write_example:
        target = project.root / EXAMPLE
        target.write_text(render_example(rows, example_environment(model, args.env)), encoding="utf-8")
        print(_display(target.resolve()))
    missing = sum(r.verdict == "missing" for r in rows)
    if missing:
        print(f"seams secrets: {missing} missing", file=sys.stderr)
        return 1
    return 0


def _sequence(args: argparse.Namespace) -> int:
    project = load_project(args.project)
    paths, gaps = run_sequence(project, args.model, args.event, args.out, args.trace, args.db)
    for name, gap in gaps:
        print(f"seams sequence: gap {name}: {gap}", file=sys.stderr)
    for path in paths:
        print(_display(path.resolve()))
    return 0


def _diff(args: argparse.Namespace) -> int:
    old, new = load_model(args.old), load_model(args.new)
    changes = diff_loaded(old, new)
    report = to_json(changes)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for c in changes:
            print(shorten(f"{c.verdict} {c.kind} {c.subject} {c.detail}", new, old))
    breaking, compatible = report["counts"][BREAKING], report["counts"][COMPATIBLE]
    if breaking:
        print(f"seams diff: {breaking} breaking, {compatible} compatible", file=sys.stderr)
        return 1
    return 0


def _plan(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="seams-plan-") as tmp:
        old = load_model(resolve(args.old, Path(tmp) / "old"))
        new = load_model(resolve(args.new, Path(tmp) / "new"))
    changes = diff_loaded(old, new)
    text = render(old, new, changes)
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
        print(_display(args.output.resolve()))
    counts = to_json(changes)["counts"]
    if counts[BREAKING]:
        print(f"seams plan: {counts[BREAKING]} breaking, {counts[COMPATIBLE]} compatible", file=sys.stderr)
        return 1
    return 0


def _coverage(args: argparse.Namespace) -> int:
    path = args.model if args.model is not None else resolve_model(load_project(args.project))
    gaps = coverage_report(load_model(path))
    if args.json:
        print(json.dumps(coverage_json(gaps), indent=2))
    else:
        for gap in gaps:
            print(" ".join((gap.kind, *gap.iris)))
    if gaps:
        print(f"seams coverage: {summary(gaps)}", file=sys.stderr)
        return 1
    return 0


def _context(args: argparse.Namespace) -> int:
    project = load_project(args.project)
    try:
        manifest = run_context(project, args.model, args.task)
    except seams.ResolutionError as err:
        print(f"seams context: {err}", file=sys.stderr)
        return EXIT_IO_ERROR
    if args.json:
        print(json.dumps(context_json(manifest), indent=2, sort_keys=True))
    else:
        sys.stdout.write(render_context(manifest))
    return 0


def _propose(args: argparse.Namespace) -> int:
    project = load_project(args.project)
    try:
        result = propose(project, args.model, args.task, args.provider, args.force)
    except ProposeError as err:
        print(f"seams propose: {err}", file=sys.stderr)
        return EXIT_IO_ERROR
    print(f"task {result.task}")
    print(f"context {result.context_hash}")
    print(f"template {result.template}")
    print(f"provider {result.provider}")
    print(f"cache {'hit' if result.cache_hit else 'miss'}")
    print(f"draft {result.sha256}")
    if not result.passed:
        for name in result.failures:
            print(f"failed {name}")
        sys.stderr.write(result.output)
        print(f"seams propose: {len(result.failures)} acceptance test(s) failed; nothing written", file=sys.stderr)
        return EXIT_IO_ERROR
    print("tests passed")
    print(f"wrote {result.written}")
    return 0


def _suggest(args: argparse.Namespace) -> int:
    project = load_project(args.project)
    if args.list:
        found = pending(project, args.model)
        for p in found:
            print(f"{p.id} {p.kind} {p.gateway} {'current' if p.current else 'stale'}")
        if not found:
            print("seams suggest: no pending suggestions", file=sys.stderr)
        return 0
    if args.accept is not None:
        try:
            accepted = accept(project, args.model, args.accept)
        except StaleSuggestion as err:
            print(f"seams suggest: {err}", file=sys.stderr)
            return EXIT_IO_ERROR
        return _print_verdicts("accepted", accepted.id, accepted.verdicts, accepted.files)
    try:
        result = suggest(project, args.model, args.provider)
    except NothingToSuggest as err:
        print(f"seams suggest: nothing to suggest: {err}", file=sys.stderr)
        return 0
    except ProposeError as err:
        print(f"seams suggest: {err}", file=sys.stderr)
        return EXIT_IO_ERROR
    print(f"template {result.template}")
    print(f"provider {result.provider}")
    print(f"model {result.model_hash}")
    print(f"cache {'hit' if result.cache_hit else 'miss'}")
    print(f"suggestion {result.id}")
    if result.gateway is not None:
        print(f"gateway {result.gateway}")
    for rel in result.files:
        print(f"changed {rel}")
    if result.verdicts is None:
        _print_findings(result.findings)
        return EXIT_IO_ERROR
    return _print_verdicts("stored", result.stored, result.verdicts, ())


def _print_findings(findings: tuple[ChangeFinding, ...]) -> None:
    for f in findings:
        print(f"rejected {f.kind} {f.subject} {f.predicate} {f.detail}")
    print(f"seams suggest: {len(findings)} finding(s); nothing stored or written", file=sys.stderr)


def _print_verdicts(verb: str, what: str | None, verdicts: Verdicts, files: tuple[str, ...]) -> int:
    print(f"validated {'pass' if verdicts.validated else 'fail'}")
    print(f"generated {'pass' if verdicts.generated else 'fail'} ({verdicts.outputs} outputs)")
    if not verdicts.passed or what is None:
        _print_findings(verdicts.findings)
        return EXIT_IO_ERROR
    print(f"{verb} {what}")
    for rel in files:
        print(f"wrote {rel}")
    return 0


def _new_generator(args: argparse.Namespace) -> int:
    for path in new_generator(args.name, args.reference, args.out):
        print(_display(path.resolve()))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "path"):
        _fold_path(parser, args)
    if args.command == "sequence" and args.db is not None and args.trace is None:
        parser.error("sequence: --db needs --trace")
    try:
        return args.run(args)
    except (ProjectError, GeneratorError, seams.ResolutionError, NewGeneratorError, PatchError) as err:
        print(f"seams {args.command}: {err}", file=sys.stderr)
        return EXIT_PROJECT_ERROR
    except OSError as err:
        print(f"seams {args.command}: {err}", file=sys.stderr)
        return EXIT_IO_ERROR


if __name__ == "__main__":
    sys.exit(main())

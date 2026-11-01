"""Command line: ``seams generate|check|status|sequence|secrets [--project PATH] [--model PATH]``, ``seams diff|plan OLD NEW``,
``seams coverage [MODEL | --project PATH]``.

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

``seams check`` (D044) writes nothing. It validates the model against the
SHACL shapes, runs the project's gate queries and compares the outputs
generate would write with the disk and seams.lock. Each finding prints to
stdout as ``<kind> <detail>``; with any finding that is not advisory (a
``review`` finding is, ADVISORY_KINDS), ``seams check: N problem(s)`` counting
only those goes to stderr and the exit code is 1. With review findings only,
``seams check: N review warning(s)`` goes to stderr and the exit code is 0. A model that cannot be loaded, a bad
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
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import seams

from seams_gen import GeneratorError

from .check import ADVISORY_KINDS, FILE_KINDS, run_check
from .coverage import coverage_report, summary
from .coverage import to_json as coverage_json
from .diff import BREAKING, COMPATIBLE, diff_loaded, load_model, shorten, to_json
from .generate import apply, generate_project
from .lockfile import locate
from .plan import render, resolve
from .project import ProjectError, load_project, resolve_model
from .secrets import EXAMPLE, example_environment, render_example, run_secrets
from .sequence import run_sequence
from .status import run_status

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
    _project_arguments(gen)
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
    _project_arguments(check)
    check.set_defaults(run=_check)
    status = sub.add_parser(
        "status",
        help="report whether each running runtime container is on the current model",
        description="Read each runtime container's /healthz in an environment and compare its model hash.",
    )
    _project_arguments(status)
    status.add_argument("--env", help="the [environments.<name>] to read (default: the only one with endpoints)")
    status.add_argument("--timeout", type=float, default=5.0, help="seconds to wait for each /healthz (default: 5)")
    status.set_defaults(run=_status)
    secrets = sub.add_parser(
        "secrets",
        help="check that each environment's configuration keys and secrets exist, without reading values",
        description="List every configuration binding per environment and check that its secret exists.",
    )
    _project_arguments(secrets)
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
    return parser


def _project_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project", type=Path, default=Path("."), help="seams.toml or a directory holding one (default: .)"
    )
    parser.add_argument("--model", type=Path, help="the model (.trig); overrides the project file and SEAMS_MODEL")


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
        print(f"seams check: {len(findings)} review warning(s)", file=sys.stderr)
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "sequence" and args.db is not None and args.trace is None:
        parser.error("sequence: --db needs --trace")
    try:
        return args.run(args)
    except (ProjectError, GeneratorError, seams.ResolutionError) as err:
        print(f"seams {args.command}: {err}", file=sys.stderr)
        return EXIT_PROJECT_ERROR
    except OSError as err:
        print(f"seams {args.command}: {err}", file=sys.stderr)
        return EXIT_IO_ERROR


if __name__ == "__main__":
    sys.exit(main())

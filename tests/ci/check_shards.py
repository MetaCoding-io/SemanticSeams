"""Check that the CI pytest-split shards cover the serial collection exactly.

Collects the suite once plainly and once per ``--splits N --group i`` shard,
then reports every node ID missing from the shards, collected by more than one
shard, or collected by a shard but not by the plain run. Exits non-zero on any
of these, or when the plain collection is empty.

Run from the repository root: ``uv run python tests/ci/check_shards.py``.
"""

from __future__ import annotations

import subprocess
import sys
from collections import Counter

SPLITS = 4


def compare(full: list[str], shards: list[list[str]]) -> list[str]:
    """Return one error line per coverage defect; an empty list means exact cover."""
    if not full:
        return ["serial collection is empty: no node IDs to compare"]
    errors: list[str] = []
    full_set = set(full)
    counts: Counter[str] = Counter()
    for shard in shards:
        counts.update(set(shard))
    errors.extend(f"missing from every shard: {n}" for n in sorted(full_set - set(counts)))
    errors.extend(f"collected by {c} shards: {n}" for n, c in sorted(counts.items()) if c > 1)
    errors.extend(f"in a shard but not the serial collection: {n}" for n in sorted(set(counts) - full_set))
    return errors


def parse_node_ids(output: str) -> list[str]:
    """Node IDs from ``pytest --collect-only -q`` output (lines containing ``::``)."""
    return [line.strip() for line in output.splitlines() if "::" in line and not line.startswith(" ")]


def collect(extra: list[str]) -> list[str]:
    cmd = ["uv", "run", "pytest", "--collect-only", "-q", *extra]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        raise SystemExit(f"collection failed ({result.returncode}): {' '.join(cmd)}")
    return parse_node_ids(result.stdout)


def main() -> int:
    full = collect([])
    shards = [collect(["--splits", str(SPLITS), "--group", str(i)]) for i in range(1, SPLITS + 1)]
    errors = compare(full, shards)
    for line in errors:
        print(line)
    sizes = ", ".join(str(len(s)) for s in shards)
    if errors:
        print(f"shard guard FAILED: {len(errors)} defect(s); serial {len(full)}, shards [{sizes}]")
        return 1
    print(f"shard guard ok: serial {len(full)} node IDs = union of {SPLITS} shards [{sizes}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())

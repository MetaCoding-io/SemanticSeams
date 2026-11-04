"""A fake ``seams draft-generator`` provider: reads the prompt on stdin and
answers with a generator for processes.yaml whose extract step reads each
process's IRI and label from the model and whose template loops over them.
With a path argument it counts its calls there and fails on the second, so a
cache hit is visible."""

import json
import sys
from pathlib import Path

from answers import GOOD

prompt = sys.stdin.read()
assert "DATA reference processes.yaml" in prompt and "DATA names" in prompt, "no draft-generator prompt on stdin"
if len(sys.argv) > 1:
    calls = Path(sys.argv[1])
    count = int(calls.read_text()) if calls.exists() else 0
    calls.write_text(str(count + 1))
    if count:
        sys.exit("called again: the answer should have come from the cache")
sys.stdout.write(json.dumps(GOOD, indent=2) + "\n")

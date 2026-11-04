"""A fake ``seams suggest`` provider: reads the prompt on stdin and answers with
the ``condition-to-dmn`` suggestion that moves ``decision_gateway``'s inline
amount rule into a DMN decision. With a path argument it counts its calls there
and fails on the second, so a cache hit is visible."""

import json
import sys
from pathlib import Path

prompt = sys.stdin.read()
assert "DATA gateway" in prompt and "gateway: decision_gateway" in prompt, "no suggest prompt on stdin"
if len(sys.argv) > 1:
    calls = Path(sys.argv[1])
    count = int(calls.read_text()) if calls.exists() else 0
    calls.write_text(str(count + 1))
    if count:
        sys.exit("called again: the response should have come from the cache")
answer = {
    "kind": "condition-to-dmn",
    "gateway": "decision_gateway",
    "decision_id": "approval_outcome",
    "decision_name": "Approval Outcome",
    "inputs": ["amount"],
    "output": "outcome",
    "rules": [{"when": {"amount": "<= 2000"}, "then": '"approved"'}, {"then": '"rejected"'}],
    "conditions": {"flow_approved": 'outcome == "approved"', "flow_rejected": 'outcome == "rejected"'},
}
sys.stdout.write(json.dumps(answer, indent=2) + "\n")

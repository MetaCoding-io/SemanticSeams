"""A fake ``seams suggest`` provider whose answer names a gateway the model does
not have, so the suggestion is rejected. With ``--exit N`` it fails instead."""

import json
import sys

sys.stdin.read()
if sys.argv[1:2] == ["--exit"]:
    sys.stderr.write("quota exceeded\n")
    sys.exit(int(sys.argv[2]))
answer = {
    "kind": "condition-to-dmn",
    "gateway": "no_such_gateway",
    "decision_id": "approval_outcome",
    "decision_name": "Approval Outcome",
    "inputs": ["amount"],
    "output": "outcome",
    "rules": [{"then": '"approved"'}],
    "conditions": {"flow_approved": 'outcome == "approved"'},
}
sys.stdout.write(json.dumps(answer) + "\n")

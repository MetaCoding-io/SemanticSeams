"""A fake ``seams draft-generator`` provider whose answer is refused, one way
per variant (argv[1]): ``golden`` (the golden names another label, so the
golden test fails), ``logic`` (a filter in the template), ``restates`` (the
template holds a model label), ``missing`` (no golden key) and ``malformed``
(not JSON)."""

import json
import sys

from answers import GOOD

sys.stdin.read()
variant = sys.argv[1]
answer = dict(GOOD)
if variant == "golden":
    answer["golden"] = GOOD["golden"].replace('"Send Message Process"', '"Send A Message"')
elif variant == "logic":
    answer["template"] = GOOD["template"].replace("[[ process.label ]]", "[[ process.label | upper ]]")
elif variant == "restates":
    answer["template"] = GOOD["template"].replace("[[ process.label ]]", '"Send Message Process"')
elif variant == "missing":
    del answer["golden"]
elif variant == "malformed":
    sys.stdout.write("Here is the generator you asked for: {extract: ...}\n")
    sys.exit(0)
else:
    sys.exit(f"unknown variant {variant!r}")
sys.stdout.write(json.dumps(answer, indent=2) + "\n")

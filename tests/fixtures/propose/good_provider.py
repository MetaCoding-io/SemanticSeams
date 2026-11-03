"""A fake ``seams propose`` provider: reads the prompt on stdin and answers with
chapter 9's handlers/notify.py in a fenced block. With a path argument it
counts its calls there and fails on the second, so a cache hit is visible."""

import sys
from pathlib import Path

prompt = sys.stdin.read()
assert "DATA" in prompt, "no prompt on stdin"
if len(sys.argv) > 1:
    calls = Path(sys.argv[1])
    count = int(calls.read_text()) if calls.exists() else 0
    calls.write_text(str(count + 1))
    if count:
        sys.exit("called again: the response should have come from the cache")
body = (Path(__file__).resolve().parents[3] / "examples/expenses/chapter-09/handlers/notify.py").read_text()
sys.stdout.write("```python\n" + body + "```\n")

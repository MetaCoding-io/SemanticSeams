"""A fake ``seams propose`` provider whose draft returns the wrong shape:
no ``message``, so the acceptance tests fail. With ``--exit N`` it fails instead."""

import sys

sys.stdin.read()
if sys.argv[1:2] == ["--exit"]:
    sys.stderr.write("quota exceeded\n")
    sys.exit(int(sys.argv[2]))
sys.stdout.write('def notify_manager(entity: dict) -> dict:\n    return {"recipient": "manager"}\n')

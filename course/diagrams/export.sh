#!/usr/bin/env sh
# Regenerates the course diagrams: the HTML sources from build.py, then one standalone SVG
# per source with the diagram-design exporter, with the IBM Plex font import the
# SemanticSeams profile uses in place of the exporter's default fonts.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
SKILL=${DIAGRAM_DESIGN_SKILL:-$HOME/.claude/plugins/cache/diagram-design/diagram-design/2.6.142/skills/diagram-design}
cd "$HERE"
python3 build.py
python3 "$SKILL/scripts/self_check.py" src/*.html
for f in src/*.html; do
  n=$(basename "$f" .html)
  python3 "$SKILL/scripts/export_svg.py" "$f" "$n.svg"
  python3 - "$n.svg" <<'PY'
import re, sys
f = sys.argv[1]; s = open(f).read()
plex = ("@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;1,400"
        "&amp;family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&amp;display=swap');")
s, n = re.subn(r"@import url\('https://fonts\.googleapis\.com/css2\?family=Instrument\+Serif[^']*'\);", plex, s)
assert n == 1, f
open(f, "w").write(s)
PY
done

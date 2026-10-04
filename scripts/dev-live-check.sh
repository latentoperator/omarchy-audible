#!/usr/bin/env bash
# Live-shell check for the plugin scaffold (task A0 acceptance step).
# Links this repo into the Omarchy plugins dir, rescans, and confirms the
# shell discovers it. Does NOT enable it (no bar change). Undo: make dev-unlink
set -euo pipefail
cd "$(dirname "$0")/.."
ID=latentoperator.audible

make dev-link
omarchy-shell shell rescanPlugins
sleep 2
echo "--- shell lists the plugin?"
if omarchy-shell shell listPlugins | grep -q "$ID"; then
  omarchy-shell shell listPlugins | python3 -c "
import json,sys
for p in json.load(sys.stdin):
    if p.get('id')=='$ID': print(json.dumps(p,indent=2)[:1200])
" || true
  echo "PASS: shell discovered $ID"
else
  echo "FAIL: $ID not listed by the shell" >&2
  exit 1
fi
echo
echo "Next (optional, adds the book icon to your bar): omarchy plugin enable $ID"
echo "Undo: make dev-unlink && omarchy-shell shell rescanPlugins"

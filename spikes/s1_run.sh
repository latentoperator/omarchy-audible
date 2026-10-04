#!/usr/bin/env bash
# S1 interactive run, meant to be opened in a terminal on the laptop's own screen.
# Pauses Omarchy's clipboard-history watchers while the redirect URL is on the
# clipboard, opens the sign-in page in an incognito window (no browser history),
# reads the paste through a hidden prompt, then clears the clipboard and lets the
# shell restart the watchers. Results (no secrets) go to $XDG_RUNTIME_DIR.
set -uo pipefail
umask 077

HERE=$(cd "$(dirname "$0")" && pwd)
PY=${OA_PY:-$HOME/.local/share/uv/tools/audible-cli/bin/python}
OUT=${1:-$HOME/.config/omarchy-audible-s1-fresh}
RUN=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/omarchy-audible-s1
WATCH='wl-paste .*--watch .*/shell/plugins/clipboard/capture\.sh'
mkdir -p -m 700 "$RUN"

resume_clip() {
  wl-copy --clear 2>/dev/null
  pkill -KILL -f "$WATCH" 2>/dev/null  # shell's watchRestartTimer starts fresh ones
}
trap resume_clip EXIT

URL=$("$PY" "$HERE/s1_login.py" start) || { echo "start failed"; read -r; exit 1; }
pkill -STOP -f "$WATCH"

cat <<'EOF'

  Audible sign-in test (S1)
  -------------------------
  1. A private (incognito) Chrome window is opening on Amazon's sign-in page.
     Sign in normally. Note whether you get a captcha or a 2FA code.
  2. You will end on a "Looking for something?" / page-not-found screen.
     That's expected. Click the address bar, select all, copy (Ctrl+C).
  3. Come back here, paste with Ctrl+Shift+V (nothing will show), press Enter.

  Clipboard history is paused until this finishes.

EOF
setsid -f google-chrome-stable --incognito "$URL" >/dev/null 2>&1

"$PY" "$HERE/s1_login.py" finish "$OUT" 2>&1 | tee "$RUN/result.json"
resume_clip
trap - EXIT
echo
echo "Done. You can close the private window and this terminal (press Enter)."
read -r _

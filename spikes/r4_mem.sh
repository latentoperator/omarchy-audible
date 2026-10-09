#!/bin/bash
# R4 memory: a fresh shell's RSS/PSS with and without our bar entry, and with the
# panel open, three rounds. Run as root on the desktop; restores shell.json (cmp).
set -u
R=/run/user/1000
CJ=/home/chrisgray/.config/omarchy/shell.json
BAK=/home/chrisgray/.cache/dante-oa/r4-shell.json.bak
AS() { H=$(ls $R/hypr | head -1); sudo -u chrisgray env XDG_RUNTIME_DIR=$R WAYLAND_DISPLAY=wayland-1 HYPRLAND_INSTANCE_SIGNATURE=$H DBUS_SESSION_BUS_ADDRESS=unix:path=$R/bus bash -lc "$1"; }
qspid() { AS "qs list --all" | awk '/Process ID/{print $3}' | head -1; }
rss() { awk '/^VmRSS/{print $2}' /proc/$1/status; }
pss() { awk '/^Pss:/{print $2}' /proc/$1/smaps_rollup; }
[ -f $BAK ] || sudo -u chrisgray cp -p $CJ $BAK
cmp -s $CJ $BAK || { echo "shell.json differs from backup at start"; exit 1; }
restart() { AS "omarchy-restart-shell" >/dev/null 2>&1; sleep 75; }
for round in 1 2 3; do
  for mode in present absent; do
    if [ $mode = absent ]; then
      sudo -u chrisgray bash -c "jq '.bar.layout.right |= map(select(.id != \"latentoperator.audible\"))' $BAK > $CJ.tmp && cat $CJ.tmp > $CJ && rm $CJ.tmp"
    else
      sudo -u chrisgray bash -c "cat $BAK > $CJ"
    fi
    restart
    P=$(qspid)
    echo "round=$round mode=$mode pid=$P rss_kb=$(rss $P) pss_kb=$(pss $P)"
    if [ $mode = present ]; then
      AS "qs ipc --pid $P call latentoperator.audible toggle" >/dev/null; sleep 20
      echo "round=$round mode=present+panel pid=$P rss_kb=$(rss $P) pss_kb=$(pss $P) panel=$(AS "qs ipc --pid $P call latentoperator.audible panelState")"
      AS "qs ipc --pid $P call latentoperator.audible toggle" >/dev/null; sleep 20
      echo "round=$round mode=present+closed pid=$P rss_kb=$(rss $P) pss_kb=$(pss $P)"
    fi
  done
done
sudo -u chrisgray bash -c "cat $BAK > $CJ"
cmp $CJ $BAK && echo "shell.json restored (cmp clean)"
restart
P=$(qspid)
echo "final pid=$P"
AS "qs ipc --pid $P call latentoperator.audible playerStatus; qs ipc --pid $P call latentoperator.audible libraryState"
pgrep -a -x mpv | cut -c1-60

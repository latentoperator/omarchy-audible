#!/usr/bin/env bash
# Run with OA_AUTH_FILE=/path/to/audible-auth.json. Prints counts/shapes only.
# S2: download + decrypt one multi-part book as AAX and one book as AAXC,
# using a plugin-style private AUDIBLE_CONFIG_DIR. Prints sizes, timings,
# field names and checks only. Deletes everything at the end.
set -uo pipefail
PY=~/.local/share/uv/tools/audible-cli/bin/python
AUD=~/.local/share/uv/tools/audible-cli/bin/audible
W=$(mktemp -d -p "$XDG_RUNTIME_DIR" oa-s2.XXXX)   # tmpfs, private
CFG=$W/config; BOOKS=$HOME/.cache/oa-spikes/books
trap 'rm -rf "$W" "$BOOKS"' EXIT
mkdir -p "$CFG" "$BOOKS"; chmod 700 "$W" "$CFG" "$BOOKS"

# Plugin-owned config dir: copy auth, write a minimal profile.
install -m 600 "${OA_AUTH_FILE:?set OA_AUTH_FILE to an audible auth json}" "$CFG/plugin.json"
cat > "$CFG/config.toml" <<EOF
title = "Audible Config File"
[APP]
primary_profile = "plugin"
[profile.plugin]
auth_file = "plugin.json"
country_code = "us"
EOF
chmod 600 "$CFG/config.toml"
export AUDIBLE_CONFIG_DIR=$CFG

$PY -W ignore ~/.cache/oa-spikes/s2_pick.py "$W/picks.json" || exit 1
echo "== profile in private config dir:"; $AUD manage profile list 2>&1 | grep -c plugin

peak() { du -sb "$1" | cut -f1; }
check() { # file catalog_ms catalog_chapters
  local f=$1 cat_ms=$2 cat_ch=$3
  local dur ch
  dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")
  ch=$(ffprobe -v error -show_chapters -of json "$f" | jq '.chapters|length')
  python3 -c "d=float('$dur')*1000; c=$cat_ms; print(f'  duration_ratio={d/c:.4f} within_1pct={abs(d/c-1)<0.01} chapters={$ch} catalog_chapters=$cat_ch')"
  ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,bit_rate -of csv=p=0 "$f" | sed 's/^/  audio=/'
  # decode 5s from the middle to prove it is really decrypted audio
  local mid; mid=$(python3 -c "print(int(float('$dur')/2))")
  ffmpeg -v error -ss "$mid" -t 5 -i "$f" -f null - && echo "  decode_check=ok"
}

for kind in MultiPartBook SinglePartBook; do
  asin=$(jq -r ".$kind.asin" "$W/picks.json"); ms=$(jq -r ".$kind.runtime_ms" "$W/picks.json"); ch=$(jq -r ".$kind.chapters" "$W/picks.json")
  d=$BOOKS/$kind; mkdir -p "$d"
  if [[ $kind == MultiPartBook ]]; then fmt=--aax; else fmt=--aaxc; fi
  echo "== $kind via $fmt"
  t0=$(date +%s.%N)
  $AUD download -a "$asin" $fmt --chapter -q best -y --no-progress -f asin_only -o "$d" >"$W/dl-$kind.log" 2>&1
  rc=$?; t1=$(date +%s.%N)
  echo "  download_rc=$rc seconds=$(python3 -c "print(round($t1-$t0,1))")"
  echo "  files: $(cd "$d" && ls | sed -E "s/$asin/<ASIN>/g" | tr '\n' ' ')"
  raw=$(ls "$d"/*.aax "$d"/*.aaxc 2>/dev/null | head -1)
  [[ -n $raw ]] || { echo "  NO RAW FILE"; grep -i -E "error|fail" "$W/dl-$kind.log" | sed -E "s/$asin/<ASIN>/g" | head -5; continue; }
  echo "  raw_count=$(ls "$d"/*.aax "$d"/*.aaxc 2>/dev/null | wc -l) raw_bytes=$(stat -c %s "$raw")"
  t0=$(date +%s.%N)
  if [[ $raw == *.aax ]]; then
    ab=$($AUD activation-bytes 2>/dev/null | tail -1 | tr -d '[:space:]')
    ffmpeg -v error -y -activation_bytes "$ab" -i "$raw" -map 0:a -c copy "$d/book.m4b.tmp.m4b"; rc=$?
    unset ab
  else
    v=$(ls "$d"/*.voucher | head -1)
    echo "  voucher_top_keys: $(jq -c 'keys' "$v")"
    echo "  license_response_keys: $(jq -c '.content_license.license_response | if type=="object" then keys else type end' "$v")"
    key=$(jq -r '.content_license.license_response.key' "$v"); iv=$(jq -r '.content_license.license_response.iv' "$v")
    ffmpeg -v error -y -audible_key "$key" -audible_iv "$iv" -i "$raw" -map 0:a -c copy "$d/book.m4b.tmp.m4b"; rc=$?
    unset key iv
  fi
  t1=$(date +%s.%N)
  echo "  decrypt_rc=$rc seconds=$(python3 -c "print(round($t1-$t0,1))") peak_dir_bytes=$(peak "$d") m4b_bytes=$(stat -c %s "$d/book.m4b.tmp.m4b" 2>/dev/null)"
  [[ $rc == 0 ]] && check "$d/book.m4b.tmp.m4b" "$ms" "$ch"
  echo "  chapter_json_present=$(ls "$d"/*chapters*.json 2>/dev/null | wc -l)"
  rm -rf "$d"
done
echo "== cleanup"; rm -rf "$W" "$BOOKS"; ls "$BOOKS" 2>&1 | head -1

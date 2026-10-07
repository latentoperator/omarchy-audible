# Brief: B11 locked-file playback, desktop part (Claude Code / Codex on HMSP-OMARCHYBEE)

You are finishing B11 on Chris's desktop (HMSP-OMARCHYBEE), inside the real Omarchy shell. B11 stops the plugin from storing a decrypted copy of any book: `get` keeps the file exactly as Audible sent it, and mpv unlocks it in memory at load time (SPIKE-RESULTS S7, decision D7). The backend half and the pure-JS helpers were built on Hopebox and merged into the **`b11` integration branch**, not `main`. Your job is the QML wiring and the real-mode acceptance. After that, Dante merges `b11` into `main` in one step. This brief is self-contained. Read it in full before you start.

## 0. Before you start

Work only in the live checkout and its worktrees on BEE. The Hopebox copy mounted at `~/Hopebox/...` is CIFS and can't execute anything (review brief §4.1), so treat it as read-only.

1. **Don't put `b11` in the live plugin folder until you're ready to test real mode.** The live plugin is `~/.config/omarchy/plugins/latentoperator.audible`, a git checkout on `main` that Chris listens on daily. Develop in a worktree under `~/Projects/oa-wt/b11` (never inside `~/.config/omarchy/plugins/`): `git -C ~/.config/omarchy/plugins/latentoperator.audible fetch origin && git -C ~/.config/omarchy/plugins/latentoperator.audible worktree add -b b11-desktop ~/Projects/oa-wt/b11 origin/b11`.
2. To run the shell on your branch, switch the live folder to `b11-desktop` (that branch is checked out in your worktree, so commit there and use `git checkout --detach <sha>` in the live folder), then restart once. Before you leave, put the live folder back on `main` and restart, unless Dante has already merged `b11` into `main`.
3. Read `docs/STATE.md`, PLAN's B11 entry, `docs/SPIKE-RESULTS.md` S7 (the whole section, especially "Not covered here" and the PCM check), and `docs/ARCHITECTURE.md` §3, §4.2 (`play-info`), §4.3 and §5.1 as updated on `b11`. Then read `docs/briefs/M4-desktop.md` §0–§3 and `docs/briefs/M3-laptop.md` §2–§3. Their hard rules and dev loop apply here unchanged.
4. Check what the Hopebox half delivered: `git log origin/main..origin/b11`, and the PR the Kanban merge card links in `docs/STATE.md`.

## 1. What the backend gives you (on `b11`)

- A locked book's directory is `<booksDir>/<asin>/` with `book.aaxc` or `book.aax` (the original), `key.json` (`0600`), `chapters.txt` (ffmetadata from Audible's list) and `meta.json`. Old books keep `book.m4b`, and both kinds count as local.
- **`play-info <asin>`** is a non-job command, so it runs during a download. It emits one `{"type":"play_info","path":…,"chapters_file":…|null,"lavf_options":…}` and then `done`. `lavf_options` is the ready-made `demuxer-lavf-o` value (`audible_key=…,audible_iv=…` or `activation_bytes=…`). It is `""` for an old `.m4b` and is a **secret**.
- `Mpv.loadCommand(path, startSec, options)` builds `["loadfile", path, "replace", -1, {"start": …, "demuxer-lavf-o": …, "chapters-file": …}]` and leaves out empty options. `Mpv.clearKeyCommand()` builds the command that blanks `demuxer-lavf-o`. `Playback.asinFromPath` understands `book.aaxc`, `book.aax` and `book.m4b`. `EventLog.summarize` never includes `lavf_options`.
- Fake mode: fake `get` writes an unencrypted test file named `book.aaxc` with a fake key, and mpv plays it with the key option set. `OMARCHY_AUDIBLE_FAKE_CHAPTERS=<n>` (or `--fake-chapters <n>`) gives a fake book with `n` chapters, which you can use for the 100+ chapter UI check before the real one.

## 2. What you're building (branch `b11-desktop`, one PR into `b11`)

1. **Play through `play-info`.** `Service.playNow(asin, startSec)` stops building `…/book.m4b` itself. It runs `play-info <asin>` (purpose `play`), and on its `play_info` event calls `player.play(path, startSec, {lavf, chaptersFile})`. A `play-info` error shows the existing "Couldn't start playback" notice and the Mini line. Every way into playback goes through it: pick, resume, Resume / Start over, ⏯ catch-up and the hotkeys.
2. **`PlayerController.play` passes the options** to `Mpv.loadCommand`. After mpv reports the file loaded (`file-loaded` or `playback-restart`, whichever `PlayerController` already uses), send `Mpv.clearKeyCommand()` once. Then `get_property demuxer-lavf-o` over the socket must return empty while the book plays.
3. **The key never leaves memory except over the socket.** Don't keep it in `state.json`, a QML property that outlives the load, `recentEvents`, `console.*`, the journal, `playerStatus`/`panelState` IPC output, or any notification. Hold it only in the pending load and drop it when the load is sent. mpv must still have no log file (no `--log-file`, no `--msg-level` that prints option values).
4. **Reattach after `omarchy-restart-shell`** must still work. mpv already has the file open, so no key is needed. Check it.
5. **Chapters:** with `chapters-file` set, `PlayerController.chapters` must match Audible's list (the phone's), not the file's coarser embedded marks.
6. Tick B11 in PLAN, update STATE, and say in README and SCOPE §7 that no unlocked copy is stored, unless the Hopebox half already did. Check the `b11` text.

No view changes are expected. If one turns out to be necessary, keep it small and say so in the PR.

## 3. Hard rules

- Everything in M4-desktop §2 still applies: fake mode for development, no simulated input, theme tokens only, no logic in views, and don't edit `AGENTS.md` or `backend/`. A backend gap is a finding: write it up for Dante and stop.
- **Keys:** never print, copy, screenshot or paste a key, voucher, `key.json`, `activation_bytes` or `auth.json`, including in PR text, test output or this repo. When a check involves a key, report counts and booleans only ("key in argv: none", "`demuxer-lavf-o` after load: empty").
- Never copy book files, keys or anything from `~/.config/omarchy-audible/` off the desktop.
- **Real-mode downloads touch Chris's account and disk.** Ask Chris before each `get`, and he does the clicking as at G4. `remove` never touches the Audible account, but only remove books he names.

## 4. Real-mode acceptance (with Chris, after Codex's review PASS)

Record each step in `docs/MANUAL-TEST.md` under a new `## B11` heading: one line per check with the steps, the result and the date.

1. **Fresh locked download:** get a short cloud book chosen by Chris. Its directory has `book.aaxc` (or `.aax`), `key.json` at mode `0600`, `chapters.txt` and `meta.json`, and **no `.m4b` and no `.partial`** anywhere under `~/Audiobooks/Audible/`. Check with `find … -name '*.m4b'` and `stat -c %a`. Peak disk use during `get` is about 1× the book, not 2×.
2. **Play → seek → chapter → resume → remove** on that book: start, seek to the start, middle and near the end, jump chapters from the popup and the Full list, quit and resume at the saved spot, then Remove from this device.
3. **100+ chapters:** one real book with more than 100 chapters (Chris picks it; ask before the download). Its chapter list matches the phone's, the Full list scrolls smoothly, and chapter jumps land exactly.
4. **The unlock is real:** with mpv playing a locked book, decode 20 s at two points to PCM as in S7, using mpv's own `--ao=pcm` on a throwaway mpv with its own socket, or the method S7 used. The output must be non-silent with no decoder errors. Then confirm the control: the same file with no key gives decoder errors. `file-loaded` alone is not proof.
5. **No key anywhere:** while a locked book plays, `ps -eo args` contains neither the key nor the activation bytes (grep for both inside the shell, then report only "none"). Do the same for `journalctl --user -b` since the load, `omarchy-shell latentoperator.audible recentEvents`, `playerStatus`, `state.json`, and `get_property demuxer-lavf-o` after load (it must be empty).
6. **Old books still play:** Carl (`book.m4b`, 50 chapters) plays, seeks and resumes as before.
7. **J6 in full** (carried over from G4): finish a book, Remove from this device, download it again, and play. It resumes where Audible says, and the finished book's Resume / Start over prompt behaves as it did before B11.
8. **Shell restart during playback** of a locked book: the audio continues and the service reattaches with live state.
9. **B15, `last_updated` is UTC** (review F2): during step 2 or 7, note the wall-clock UTC time of one real position push, read it back with `position-get`, and record the offset between `updated_at` and that time in `docs/SPIKE-RESULTS.md` S3 (offset in seconds only).
10. **Fake mode** still works end to end (fake get → play, including `OMARCHY_AUDIBLE_FAKE_CHAPTERS=120`), and `make test`, `make check-symlinks` and `omarchy plugin validate .` pass on the branch.

## 5. Review and merge

The same as M4-desktop §5. One CLI implements and the other reviews the exact head. The reviewer checks §2 and §3 above, and that no code path writes a key anywhere except over the mpv socket. After PASS and the §4 acceptance, open a PR from `b11-desktop` into `b11`. Tell Chris "B11 desktop PR #<n> passed review and real-mode acceptance at <sha>". Dante then merges `b11-desktop` → `b11` → `main`, pinned to the reviewed SHAs.

At the end of every session: put the live plugin folder back on `main` (unless `b11` has merged), delete the dev-fake flag, restart once, and confirm real mode (one `quickshell`, one bar per monitor, 91 books). Tell Chris you did.

## 6. When you're stuck

If the docs and reality disagree, stop and write down what you saw; don't redesign around it. If mpv 0.41 rejects the per-file option map, or `demuxer-lavf-o` can't be cleared after load, stop and report it. S7 proved the load path, but the clear step is new. Exit code 0 is not proof: check the actual result. Before you report anything, check `git status` and the diff.

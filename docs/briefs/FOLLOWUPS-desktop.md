# Brief: review follow-ups, desktop part (Claude Code / Codex on HMSP-OMARCHYBEE)

You are finishing the review follow-ups that need the real Omarchy shell on Chris's desktop (HMSP-OMARCHYBEE). Everything that could be done and tested without a shell was built on Hopebox and is already in `main` (P6's backend half, B12, B13, P7 and H1's Hopebox part, merged 2026-10-07). What's left is QML wiring, view changes and things someone has to look at or listen to. This brief is self-contained. Read it in full before you start.

## 0. Before you start

1. **Ask Chris whether a book is playing.** If one is, ask him to pause it. Then bring the live plugin up to date: `cd ~/.config/omarchy/plugins/latentoperator.audible && git checkout main && git pull --ff-only`. It is about 33 commits behind `main` (B11 as merged, `5f3877e`). Even a pull that changes nothing makes the shell hot-reload the plugin (a second of `is not a function` warnings, then it recovers), so do it only while paused. Afterwards confirm one `quickshell`, one bar per monitor and 91 books.
2. Delete the leftover worktree from B11: `git worktree remove ~/Projects/oa-wt/b11` (the `b11-desktop` branch is merged and gone from GitHub; delete the local branch too). Put new worktrees under `~/Projects/oa-wt/`, never inside `~/.config/omarchy/plugins/`.
3. Read `docs/STATE.md`; PLAN's P6, U8, U9, U10, P8 and H1 entries; `docs/briefs/REVIEW-2026-10-06.md` F17–F19, F21–F23 and F25–F27; `docs/briefs/REVIEW-2026-10-07.md` F37; `docs/MANUAL-TEST.md` `## B11` (where U10 came from). Then `docs/briefs/M4-desktop.md` §2–§3 and `docs/briefs/M3-laptop.md` §2–§3. Their hard rules and dev loop apply unchanged; §2 below repeats the ones that matter most.
4. Use the repo's tools as they are now: `make lint` runs `ruff check .` and `ruff format --check .` (H1), and the `qml/lib` tests **fail** if PySide6 is missing, unless `OMARCHY_AUDIBLE_ALLOW_SKIP_QJS=1` is set. Don't set it. If ffmpeg isn't on PATH for the tests, set `OMARCHY_AUDIBLE_FFMPEG_DIR`.

## 1. What you're building

One branch and one PR each, in this order. Each PR starts from the current `origin/main`, so rebase onto the previous merge before you start the next.

| # | Task | Branch | Gist |
|---|---|---|---|
| 1 | P6 desktop | `p6-desktop` | `PositionSync` counts consecutive `stale`; Mini shows `Sync.staleNotice` |
| 2 | H1 F27 + U10(a) | `h1-dev-ipc` | Test-only IPC methods work only in fake mode; `libraryQuery` stops changing the drawer |
| 3 | U10(b)(c) + F37 | `u10-findings` | Finished-book question on the row; play errors name the title; Stop clears the error |
| 4 | H1 F25, F26 | `h1-views` | Chapter popup only in the open panel; one shared muted-text colour |
| 5 | U8 | `u8-full-library` | Library button in the Full view |
| 6 | P8 | `p8-service-fixes` | F17, F18, F19, F21, F22, F23 |
| 7 | U9 | `u9-pause-lag` | Measure the pause lag; change something only if the fix is ours and safe |

P9 (the `Service.qml` split) is **not** in this brief. It's a large refactor of the file every item above touches, so it gets its own brief after these merge.

## 2. Hard rules (short form; M3 brief §2 is the full list)

- **The shell is in real mode, and Chris listens on it daily.** Develop in fake mode: with Chris's OK pause playback, `touch /run/user/$(id -u)/omarchy-audible-dev-fake`, `omarchy-restart-shell`, and confirm fake mode with `playerStatus` and the journal before testing anything. **At the end of every session, delete the flag and restart once** so Chris is back in real mode, and tell him you did.
- **Never** run `position-push`, `logout`, `login-*`, `remove`, `get` or `setup` in real mode yourself. Real-mode checks happen in §5 with Chris doing the clicking. Never open, print or copy anything in `~/.config/omarchy-audible/` or `~/.audible/`, or any key, voucher or activation bytes (B11 rules: report booleans and counts only).
- **No simulated input** (`wtype`, `ydotool`, `hyprctl dispatch` input). Drive the shell through IPC and check views with `grim -o DP-4` / `grim -o DP-5` screenshots of fake data. Batch anything that needs a hand into a **hand-check list** in each PR.
- Theme only through `qs.Commons` tokens. **No logic in views:** it goes in `qml/lib/*.js` (pure ECMAScript, `.pragma library`, no `Qt.*`, never throws) with QJSEngine tests. Don't edit `AGENTS.md`, `docs/SCOPE.md`, `backend/` or Omarchy's own files. A backend gap is a finding: write it up for Dante and stop.
- Never start a second Quickshell. Announce each restart, and afterwards check there is one `quickshell` and one bar per monitor. Copy says "this device".

## 3. Dev loop

The same as M4-desktop §3. `omarchy-shell shell rescanPlugins` after a view change; `omarchy-restart-shell` after `Service.qml`, anything it loads, or a `qml/lib/*.js` change. Zero QML warnings from our files; lint changed QML with `/usr/lib/qt6/bin/qmllint`. Before every PR: the full test suite with nothing skipped, `make lint`, `make check-symlinks` and `OMARCHY_PATH=/usr/share/omarchy omarchy plugin validate .`.

## 4. Task notes (in addition to the PLAN acceptance criteria)

**1. P6 desktop: the stale line.** The Hopebox half is in `main`: the backend recognises its own echo, so a computer whose clock is behind Audible no longer refuses its own pushes, and `Sync.staleNotice(count)` returns the line ("Your position isn't reaching Audible. Check this computer's clock.") once `count` reaches `Sync.STALE_NOTICE_AFTER` (2). Wire it:
- `PositionSync.handleFinished` already drops a `stale` push from the queue. Also count consecutive `stale` outcomes; any successful push resets the count to 0. Expose the count (or the notice text) as a property. Don't persist it.
- Mini shows the line where it shows other sync notices, in the same muted style, only while the text is non-empty. The view binds to the text; the decision stays in `Sync.js`.
- Check in fake mode: make the fake account hold a newer position from "another device" for a book (write the fake tree's `fake-account-positions.json` with a later `updated_at` and a different `ms`), then pause twice so two pushes come back `stale`. The line appears; a push that succeeds clears it. Screenshot both. Tick P6 in PLAN.

**2. H1 F27 and U10(a): dev IPC.** About 35 IPC methods in `Service.qml`'s `IpcHandler` exist for testing (`removeBook`, `quitPlayer`, `autoRemove`, `syncNow`, `libraryQuery`, `flushState`, the dev `view` method and others) and today any local process can call them in real mode.
- First list every IPC method and sort it into **public** (what Omarchy keybindings, the bar or a documented user command call; check ARCHITECTURE §6, README and `omarchy` binding files, and grep `~/.config/hypr` for `latentoperator.audible` read-only) and **test-only**. Put the list in the PR.
- Test-only methods do nothing in real mode: return `"error: dev only"` unless fake mode is on. A separate `DevIpc` object loaded only in fake mode is fine too, but it's more work. Pick one and say why. Public methods stay exactly as they are.
- `libraryQuery` (U10a) must not change `library.sortKey`, `filterKey` or `searchText`. Compute its rows from a copy using the pure `Library.js` sort/filter/search functions (add a small pure helper with tests if search isn't exposed). The drawer looks the same before and after a call. Prove it with a screenshot pair and `libraryState`.
- Update ARCHITECTURE §6 with the public list.

**3. U10(b)(c) and F37.**
- **(b)** When a finished book's Resume / Start over question is up, show it on that book's row (two clear buttons, or the row's subtitle line changing to the question), not only in the one-line banner. Clicking the row's ▶ while the question is up answers it with the default (Resume), not asks again. P7 already makes Start over clear `finished`; hand-check that a finished book restarted at 0 shows under In progress and no longer asks. The choice logic stays in `LibraryUi.js` (Hopebox-owned; if it needs a change, make it small, test it, and say so in the PR).
- **(c)** A `not_local` (or any) play error shows the book's **title** from the catalog row, not the ASIN. Fall back to the ASIN only if the row is missing. The text comes from `Player.js` (`playFailure` or a helper next to it).
- **F37** `quitPlayer()` clears `playError`. One line, plus a test if the logic lives in a lib.

**4. H1 F25 and F26.**
- **F25:** every monitor's `MiniView` opens its chapter popup from the shared `service.chapterListOpen` flag, including in closed panels. Open the popup only in the view whose own panel is open. Hand-check on both monitors.
- **F26:** `Qt.rgba(Color.popups.text…, 0.75)` appears five times (MiniView, FullView, BookRow). Make it one shared property in one place the views already import. Screenshots before and after must match.
- Tick H1 in PLAN once 2 and 4 are both merged; the Hopebox part is done.

**5. U8.** Add the same Library button Mini has to the Full view header, next to collapse and ✕. Add it to FR-U4 in the PR description (SCOPE is Dante's; Dante updates it at merge).

**6. P8.** Each finding gets a test that fails on the old code where one is possible, and a hand-check line otherwise.
- **F17:** auto-remove (`removeIfStillFinished`) goes through the same unload-then-remove path as the user's Remove (`removeAfterUnload`). It must land before R1 exposes the setting. Test in fake mode with `autoRemove` through IPC.
- **F18:** the offline retry backs off exponentially, capped around 30 minutes, and resets on a successful flush, on play and on panel open. Put the schedule in `Sync.js` with tests. Check in fake mode with the network-failure fake (or by pointing at a missing backend) that the interval grows.
- **F19:** `startPicked` remembers which surface (monitor) was open and the player reopens there, not on `primarySurface()`. Hand-check: pick a book on DP-5; Mini opens on DP-5.
- **F21:** volume and speed are written to `state.json` on change (debounced) and passed to `launchMpv` (`--volume`, `--speed`), so the next mpv starts with them. Range-check the saved values.
- **F22:** reset `fadeBaseVolume` with `mpvState` and `sleepTimer` on disconnect, so a later `cancelSleep()` never sends an old volume to a new mpv.
- **F23:** a minutes sleep timer stores the remaining ms on pause and restarts from it on resume. Pause 2 min inside a 1-min timer (fake mode), resume: it must not fire at once.
- Update ARCHITECTURE §5.1 if the volume/speed start behaviour now matches it; say so if it didn't before.

**7. U9: pause lag.** Chris hears about a second of audio after ⏯. Measure before changing anything, in fake mode with a book playing:
- Timestamp the IPC `set pause` send, mpv's `pause` property change event, and when the audio actually stops (watch `pw-top`, or record the sink monitor with `pw-record` and find the last non-silent sample). Repeat five times and report the three gaps.
- Then try, one at a time: mpv `--audio-buffer` (default 0.2 s) at a lower value, and the PipeWire node latency for the mpv stream (`PULSE_LATENCY_MSEC` or `--audio-stream-silence=no`, whatever applies to mpv's PipeWire/Pulse output on BEE). Measure each the same way and listen for dropouts at 1× and 3× for a few minutes.
- Change something only if the cause is in our launch options and the fix doesn't cause dropouts. If the lag is in PipeWire or the hardware, write it up in the PR with the numbers and change nothing. Either way, record the numbers in `docs/SPIKE-RESULTS.md` as a short U9 section. The mpv args live in `PlayerController.launchMpv`, which P8's F21 also changes, so U9 goes after P8.

## 5. Real-mode acceptance (with Chris, after all seven are merged)

Quit fake playback, delete the dev flag, pull `main` into the live folder while paused, restart once, and confirm real mode (one `quickshell`, one bar per monitor, 91 books). Chris does the clicking. Record each line in `docs/MANUAL-TEST.md` under a new `## Follow-ups (desktop)` heading: steps, result, date.

1. **P6:** play a book for a minute and pause. The push goes through (no stale line), and the phone shows the same spot.
2. **P7:** on a finished book, Start over, listen a minute, pause. It shows under In progress, the row's question is gone, and "You finished" isn't shown.
3. **U10:** the row's Resume / Start over question is visible and ▶ answers it. A play error shows a title (if one can be produced safely, e.g. by playing a book Chris has just removed; otherwise mark it fake-mode only). Stop clears it.
4. **F27:** in real mode, a test-only IPC method (`libraryQuery`) returns `error: dev only`; `playerStatus` and the keybindings still work.
5. **Two monitors:** pick a book on DP-5 and the player opens on DP-5 (F19); the chapter popup opens only on the panel you're looking at (F25).
6. **F21:** change speed to 1.5× and volume, quit the player, start a book again: both come back.
7. **U9:** Chris listens to ⏯ a few times and says whether it's better, the same or worse.
8. **Smoke:** seek, a chapter jump, a shell restart during playback (audio continues, service reattaches), and `journalctl --user -b` shows zero QML warnings from our files.

If Chris has an **aax** book on BEE, also run PLAN's R2 note for B13 (activation bytes filled on first play, file back at `0600`). His current local books are all aaxc, so this is likely skipped. Say so.

## 6. Review and merge

The same as M4-desktop §5. One CLI implements and the other reviews the exact head. The implementer posts the in-shell evidence (IPC output, fake-data screenshots, journal excerpts) and the hand-check results in each PR. Reviewers check the PLAN acceptance items, §2 of this brief, no logic in views, and that public IPC behaviour is unchanged. After PASS, tell Chris "<task> PR #<n> passed review at <sha>", and Dante does the final check and merges pinned to that SHA. Then rebase the next branch onto the new `main`. Each PR updates its own row in `docs/STATE.md` and ticks its PLAN checkbox.

At the end of every session: live folder on `main`, dev-fake flag deleted, one restart, real mode confirmed. Tell Chris you did.

## 7. When you're stuck

If the docs and reality disagree, stop and write down what you saw; don't redesign around it. Exit code 0 is not proof: check the actual result. Before you report anything, check `git status` and the diff.

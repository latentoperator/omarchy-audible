# Brief: M4 player views, desktop part (Claude Code / Codex on HMSP-OMARCHYBEE)

You are finishing the player UI for the Omarchy Audible plugin on Chris's desktop (HMSP-OMARCHYBEE), inside the real Omarchy shell. M4 moved here from the laptop (HMSP-OMARCHYXPS) on 2026-10-06; the M2/M3 briefs still say "laptop", and their rules apply here unchanged. Today the Mini view is the minimal U2a version and the Full view is a placeholder (`qml/views/FullView.qml`) that nothing opens. Chris has been using the plugin for real since G3 and has asked where the maximized player is. This brief is self-contained. Read it in full before you start.

## 0. Before you start

1. `cd ~/.config/omarchy/plugins/latentoperator.audible && git checkout main && git pull --ff-only`. On BEE this folder is its own git checkout and **is** the live plugin (not a link; there is no `~/Projects/omarchy-audible` to work in). Put review worktrees under `~/Projects/oa-wt/`, never inside `~/.config/omarchy/plugins/`, where the shell would discover them as plugins. Delete leftovers from earlier sessions.
2. Read `docs/STATE.md` and the M4 section of `docs/PLAN.md` (U5, U6, U7, G4). Check whether S7 or B11 (locked-file playback) has run or merged. They change how books are stored and where chapters come from, not the views. If B11 is in flight, bind chapters only through `PlayerController.chapters` and you won't conflict.
3. Then read `AGENTS.md`, `docs/SCOPE.md` §3 (J3–J5), §4.4 (FR-P2, FR-P3), §4.5 (FR-U3–FR-U7) and §6, `docs/ARCHITECTURE.md` §4.8 and §6 (panel, views, keys), and `docs/briefs/M3-laptop.md` §2–§3. The hard rules and dev loop there still apply, and §2 below repeats the ones that matter most.
4. Reference UI: `/usr/share/omarchy/shell/plugins/panels/audio/` (a themed panel with sliders and lists), `/usr/share/omarchy/shell/Ui/` and `Commons/`, and our own `LibraryView.qml`/`MiniView.qml`. `quickshell.spotify` isn't installed on BEE; don't install it. Copy patterns, not code blocks.
5. **Display:** BEE has two 1920×1080 monitors at scale 1 (DP-4 at 0,0 and DP-5 at 1920,0), and the bar exists once per monitor. Take screenshots per output (`grim -o DP-4`), check elision at this width, and check that the panel opens on the monitor whose icon was clicked.

## 1. What you're building

These tasks are in `docs/PLAN.md`, in this order. Each one is one branch and one PR.

| Task | Branch | Gist |
|---|---|---|
| U5 | `u5-mini-complete` | Complete Mini view per FR-U3: current chapter with a chapter popup, scrub bar, ⏮ ⏪N ⏯ ⏩N ⏭, speed pill, **maximize**, library, dismiss ✕ |
| U6 | `u6-full-view` | Replace the `FullView.qml` placeholder per FR-U4: large cover, chapter list, speed, sleep timer, details, Remove from this device, collapse |
| U7 | `u7-strip-check` (only if needed) | The now-playing strip already exists in `LibraryView.qml` (U2). Check it against U7's acceptance criteria. If it passes, tick U7 in the U6 PR with the evidence and skip the branch. |

Then **G4**, which Chris runs with you (see §6).

The player already supports everything these views need, so this milestone should be **QML views plus small `qml/lib` helpers, with no backend or service redesign**. `PlayerController` already has `chapters`, `chapterIndex`, `positionMs`, `durationMs`, `speed`, `sleepTimer`, `seekMs`, `setChapter`, `jumpChapter`, `setSpeed`, `setSleepTimer`, `setSleepEndOfChapter` and `cancelSleep`. `Service` already has `showView`, `playPause`, `removeBook`, `loadedRow` and `loadedAsin`. `Panel.VIEW_FULL` exists, and `Onboarding.view` already falls back to Library when `full` is asked for with nothing loaded. If you find a missing piece in the service, add the smallest function that does the job, say so in the PR, and remember that a `Service.qml` change needs `omarchy-restart-shell`.

## 2. Hard rules (short form; M3 brief §2 is the full list)

- **The shell is in real mode, and Chris listens on it daily.** Develop in fake mode: ask Chris whether a book is playing. If one is, ask him to pause it, or with his OK run `omarchy-shell latentoperator.audible pause`. Then `touch /run/user/$(id -u)/omarchy-audible-dev-fake` and `omarchy-restart-shell`, and confirm fake mode with `playerStatus` and the journal before testing anything. **At the end of each session, delete the flag and restart once so Chris is back in real mode**, and tell him you did.
- **Never** run `position-push`, `logout`, `login-*`, `remove`, `get` or `setup` in real mode, and never let the service do so. Never open, print or copy anything in `~/.config/omarchy-audible/` or `~/.audible/`.
- **No simulated input** (`wtype`, `ydotool`, `hyprctl dispatch` input, or anything similar). Drive views through IPC (`toggle`, `openLibrary`, `chapter`, `speed`, `sleepMinutes`, …). There is no IPC method to open Mini or Full directly yet, so add a dev `view <name>` method that calls `showView` in U5's first commit (it's a `Service.qml` change, so restart after it). Check the views with `grim` screenshots of fake data and with IPC state, and batch everything that needs a hand into a **hand-check list** in each PR.
- Theme only through `qs.Commons` tokens (`Color.*`, `Style.*`). Icons come from the theme's icon font. No hard-coded colors, fonts, radii or pixel sizes that should come from `Style`.
- **No logic in views.** Formatting, preset cycling, percent complete, chapter labels and sleep-timer text go in `qml/lib/*.js` with QJSEngine tests in `tests/`. Use a new `qml/lib/Player.js` for M4 logic. Don't edit the Hopebox-owned `Format.js`, `LibraryUi.js` or `Onboarding.js`; if one is wrong, raise it in the PR.
- Don't edit `AGENTS.md`, `docs/SCOPE.md` or `backend/`. Never edit Omarchy's own files, never start a second Quickshell, announce each restart, and after each restart check there is one `quickshell` and one bar.
- Copy says "this device", never "this laptop" (PR #49).

## 3. Dev loop

The same as M3 §3. Run `omarchy-shell shell rescanPlugins` after a view change, and `omarchy-restart-shell` after `Service.qml`, anything it loads, or a `qml/lib/*.js` change. QML warnings from our files must be zero. Lint changed files with `/usr/lib/qt6/bin/qmllint`. Run the tests with `~/.cache/oa-venv/bin/python -m pytest -q`; the `qml/lib` tests must run, not skip. Before every PR, run `make check-symlinks` and `OMARCHY_PATH=/usr/share/omarchy omarchy plugin validate .`.

Fake books have three or five chapters. For U6's "100+ chapters scroll smoothly" check, add a fake-mode-only way to get a long chapter list, such as a `--fake-chapters N` option on fake `get` or a fixture. That is a backend change, so write it up as a finding and stop. Don't edit `backend/`; Dante or Hopebox adds it. Until then, check the scrolling with a long synthetic `chapters` array in a QJSEngine test of the list logic, and ask Chris to look at a real long book during G4.

## 4. Task notes (in addition to the PLAN.md acceptance criteria)

**U5: Mini view, complete.** Extend `qml/views/MiniView.qml` in place.
- **Chapter line:** shows the current chapter title (from `player.chapters[player.chapterIndex]`, labeled through `Player.js`, with a fallback like "Chapter 3" when the title is empty). Clicking it opens a chapter popup listing every chapter with its start time, current one highlighted and scrolled into view. Clicking a chapter calls `setChapter`. The popup closes on choice, Esc or click-outside, and doesn't close the panel.
- **Scrub bar:** a book-level slider with elapsed on the left and remaining on the right. **While dragging, the handle follows the pointer and ignores incoming `positionMs`**. Seek once on release (`seekMs`), then resume binding. Show chapter boundaries as ticks if it's cheap; skip them if they clutter at 100+ chapters. This is the "doesn't fight position updates" acceptance item: prove it with a hand-check (drag and hold for 3 s while playing; the handle must not jump back).
- **Transport:** ⏮ ⏪N ⏯ ⏩N ⏭. N is `Mini.skipSeconds` (15 until R1 adds the setting). ⏮/⏭ use `prevChapter`/`nextChapter`. ⏯ keeps going through `service.playPause()` (catch-up check), not `player.toggle()`.
- **Speed pill:** shows the current speed ("1.0×"), and a click cycles presets `0.75 → 1.0 → 1.25 → 1.5 → 1.75 → 2.0 → 2.5 → 3.0 → 0.75`. A speed that isn't a preset snaps to the next preset up. The cycle logic goes in `Player.js` with tests.
- **Maximize:** a button that calls `service.showView(Panel.VIEW_FULL)`. This is the control Chris has been looking for, so make it easy to spot (top-right, next to ✕, theme icon font "expand" glyph, tooltip "Full player").
- **Library** button stays. **Dismiss ✕** closes the panel the same way Esc does and never touches playback. Prove it with `playerStatus` before and after.
- Long titles, authors and chapter names elide cleanly at the panel's width. Check with the longest fake title and a made-up 80-character chapter name.

**U6: Full view.** Replace `qml/views/FullView.qml`. The Full view grows the same drawer (ARCHITECTURE §6); it doesn't open a new window or surface.
- **Header:** a large cover (`Cover.qml`, square), title, author and narrator(s) (`loadedRow.narrators`), plus a **collapse** button back to Mini (`showView(Panel.VIEW_MINI)`) and ✕.
- **Details:** runtime, % complete (from `positionMs`/`durationMs`, computed in `Player.js`) and time left at the current speed.
- **Transport and scrub bar:** the same behavior as Mini. Reuse a shared component (`qml/components/ScrubBar.qml`, `TransportRow.qml`) rather than copying the code between views.
- **Chapter list:** a `ListView` showing chapter titles and durations, current chapter highlighted, **auto-scrolled to the current chapter when the view opens and when the chapter changes** (unless the user scrolled in the last few seconds). A click jumps to that chapter. Use delegates, and don't build all rows eagerly.
- **Speed:** preset chips (the same list as the pill) plus fine control in ±0.05 steps, clamped to 0.75–3.0 (FR-P2), showing the current value.
- **Sleep timer:** choices 15 / 30 / 45 / 60 min and End of chapter, through `setSleepTimer` and `setSleepEndOfChapter`. When a timer is set, show the time left ("Sleeping in 12:40" or "At end of chapter") and a Cancel button (`cancelSleep`). The Mini view shows a small moon glyph when a timer is active, and nothing else. The time-left text comes from `Player.js` using the existing `Mpv.sleepRemainingMs`.
- **Remove from this device:** asks first ("Remove this book from this device? It stays in your library."), then calls `service.removeBook(loadedAsin)`. The service already unloads the player before removing. After removal, the view goes to Library.
- **Keys** (add them to ARCHITECTURE §6 in your PR only if they differ from it): Esc closes the panel, Space plays/pauses, ←/→ skip, and Backspace or the collapse button returns to Mini.

**U7: Now-playing strip.** Check that the existing strip appears only when a book is loaded, that the list doesn't jump when it appears or disappears (screenshot before and after loading a fake book with the Library open), and that clicking it opens Mini. It also needs ⏪/⏩ per PLAN U7. If they're missing, add them in the U6 PR, which is a two-button change.

## 5. Review and merge

The same as M3 §5. One CLI implements and the other reviews the exact head. Codex has no live-shell access, so the implementer posts the in-shell evidence (IPC output, fake-data screenshots, journal excerpts) and Chris's hand-check results in the PR. Reviewers check the PLAN acceptance items, §2 of this brief, no logic in views, and the scrub-bar drag behavior. After PASS, tell Chris "U<n> PR #<num> passed review at <sha>", and Dante does the final check and merges. Each PR updates its own row in `docs/STATE.md` and ticks its PLAN checkbox.

## 6. G4 (Chris, with you driving)

Only after U5 and U6 are merged and U7 is confirmed. Runs on BEE. Quit any fake playback, delete the dev flag, restart once, and confirm real mode (one `quickshell`, one bar per monitor, 91 books). With Chris doing all the clicking:
1. **J1–J7** from `docs/SCOPE.md` §3, recorded in a new `docs/MANUAL-TEST.md` (one line per journey: steps, result, date). J2 now means download, then a second Enter to play (PR #50).
2. **J4/J5 on a long real book:** chapter popup, a chapter jump from the Full list, a sleep timer of 15 min that he cancels, speed changes, Remove from this device on a finished short book (and it's still in the phone app).
3. **Themes:** with Chris's OK, one light and two dark themes plus a live switch with the Full view open. Note his theme first and restore it at the end.
4. Record the result in `docs/STATE.md` in a PR.

## 7. When you're stuck

If the docs and reality disagree, stop and write down what you saw; don't redesign around it. Exit code 0 is not proof: check the actual result. Before you report anything, check `git status` and the diff.

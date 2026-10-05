# Brief: M3 first usable UI, laptop part (Claude Code / Codex on HMSP-OMARCHYXPS)

You are building the drawer for the Omarchy Audible plugin on Chris's laptop, inside the real Omarchy shell. It follows the M2 laptop work (P1–P5, G2), which you or a sibling agent did. This brief is self-contained. Read it in full before you start.

## 0. Before you start

1. `cd ~/Projects/omarchy-audible && git checkout main && git pull --ff-only`. This directory **is** the live plugin (`~/.config/omarchy/plugins/latentoperator.audible` links to it). Delete any leftover review worktrees under `~/Projects/oa-wt/`.
2. Read `docs/STATE.md` and the M3 section of `docs/PLAN.md`, including the "Split" note. Hopebox is building five pieces in parallel with you: **B9, B10** (backend) and **L1, L2, L3** (pure JS in `qml/lib/`). Check which have merged (STATE and PRs #26 onward). Each of your tasks below says which ones it needs. **Never write your own version of a Hopebox piece.** If you reach a task whose piece hasn't merged, tell Chris and wait, or work on a task that is unblocked.
3. Then read `AGENTS.md`, `docs/SCOPE.md` §3 and §4.5–§6 (journeys J1–J7, FR-U1–U7, the failure table), `docs/ARCHITECTURE.md` §4.7 and §6, and `docs/SPIKE-RESULTS.md` S6. Working panel code is in `spikes/s6-BarWidget.qml` and the current `BarWidget.qml`.
4. Reference UI: `~/.config/omarchy/plugins/quickshell.spotify/` (its mini player is the closest analogue), `/usr/share/omarchy/shell/Ui/` and `Commons/`. Copy patterns, not code blocks.

## 1. What you're building

These tasks are in `docs/PLAN.md`, in this order. Each one is one branch and one PR.

| Task | Branch | Needs from Hopebox | Gist |
|---|---|---|---|
| U1 | `u1-panel-shell` | nothing | Bar glyph with play/pause state and FR-U1 tooltip, left/middle click, `KeyboardPanel` with a view stack (Onboarding/Library/Mini/Full placeholders). **Removes the debug panel.** |
| U4 | `u4-cover-badge` | L1, L2 | `Cover.qml`, `StateBadge.qml` |
| U2a | `u2a-mini-view` | L1 | Minimal Mini view: title, author, elapsed/remaining, ⏯, ⏪15/⏩15, library button |
| U2 | `u2-library-view` | L2 | Library view: search, sort, filters, storage line, book rows, download-then-play, remove, all states |
| U3 | `u3-onboarding` | L3, B9 | Missing tools, setup, connect (sign-in link + paste), import existing login, errors, reconnect banner, disconnect |

Then **G3**, which Chris runs with you (see §6).

U1 can start now. If L1/L2 aren't merged when U1 is done, build U2a with a temporary inline duration format and swap it for `Format.js` before opening the PR, or wait. Don't open a PR with logic that duplicates a Hopebox file.

Where files go: views in `qml/views/` (`OnboardingView.qml`, `LibraryView.qml`, `MiniView.qml`, `FullView.qml`, the last a placeholder until M4), small parts in `qml/components/` (`Cover.qml`, `StateBadge.qml`, `BookRow.qml`). Logic stays in `qml/lib/*.js` with QJSEngine tests: views only bind and call. Import the libraries with names that don't clash with the view types (`import "../lib/LibraryUi.js" as LibraryUi`).

## 2. Hard rules

- **The shell is in real mode right now.** G2 removed the dev flag, so anything played through the plugin pushes Chris's real positions. **Develop in fake mode:** before your first restart, ask Chris whether a book is playing. If one is, ask him to pause it (or run `omarchy-shell latentoperator.audible pause` with his OK), then `touch /run/user/$(id -u)/omarchy-audible-dev-fake` and `omarchy-restart-shell`. Confirm with `omarchy-shell latentoperator.audible playerStatus` and the journal that the service is in fake mode before you test anything. Leave the flag in place until G3.
- **Never** run `position-push`, `logout`, `login-*`, `remove`, `get` or `setup` in real mode, and never let the service do so. Real-mode `status`, `doctor`, `local` and `sync` are fine. Never open, print or copy anything in `~/.config/omarchy-audible/` or `~/.audible/`.
- **No simulated input.** Don't send clicks or key presses to the desktop (`wtype`, `ydotool`, `hyprctl dispatch` for input, or anything similar). Other apps' dialogs can take them; in M2 a stray click landed on an Outlook "Delete 10000+ items" dialog. Open and switch views with IPC (`toggle`, `openLibrary`), check them with screenshots (`grim`, fake titles only) and IPC state, and put every check that needs a hand (typing in the search field, arrow keys, Enter, Esc, click-away, middle click, the paste button) in a short **hand-check list** in the PR for Chris to run. Batch them so he does each PR's list in one sitting.
- **Don't change Chris's theme.** U1–U3 are checked under his current theme. The three-theme check happens at G3 with him there.
- **Never** edit Omarchy's own files (`/usr/share/omarchy`, `~/.local/state/omarchy/`, other plugins), and never start a second Quickshell process. Say before each `omarchy-restart-shell`, don't loop restarts, and after each one check there is one `quickshell` process and one bar.
- Theme only through `qs.Commons` tokens (`Color.*`, `Style.*`). No hard-coded colors, fonts or radii. Icons come from the theme's icon font, as the bar glyph does now.
- Never commit symlinks, a `.venv`, real data, or screenshots that show real titles.
- `AGENTS.md` is protected. Don't edit it, `docs/SCOPE.md`, or anything under `backend/`. Any backend gap goes in the PR as a finding for Dante. Don't edit the `qml/lib` files Hopebox owns (`Format.js`, `LibraryUi.js`, `Onboarding.js`); if one is wrong, say so in the PR. New logic of your own goes in a new `qml/lib` file with tests.
- Keep the extra IPC methods (`play`, `pause`, `playerStatus`, `libraryQuery` and the rest). You need them to test without input.

## 3. Dev loop

Same as M2: `omarchy-shell shell rescanPlugins` after a widget or view change; `omarchy-restart-shell` after `Service.qml`, anything it loads, or `qml/lib/*.js` changes. Logs: `journalctl --user -f -o cat | grep -iE "audible|qml"`. QML warnings from our files must be zero before a PR. Lint changed files with `/usr/lib/qt6/bin/qmllint`. Tests: `~/.cache/oa-venv/bin/python -m pytest -q`; the `qml/lib` tests must run, not skip. Before every PR: `make check-symlinks` and `OMARCHY_PATH=/usr/share/omarchy omarchy plugin validate .`.

Fake-mode tools for U3 (after B9 merges): `omarchy-audible logout --fake` signs the fake account out, and fake `login-finish` accepts any text containing `openid.oa2.authorization_code=`. Writing `~/.config/omarchy-audible-fake/fake-status.json` (`{"missing": ["mpv"]}` or `{"venv_ready": false}`) shows the missing-tools and setup screens; delete it afterward. For the Library view, `get --fake` downloads a fake book, and `--fake-fail disk|network|decrypt|novoucher` produces each failure row.

## 4. Task notes (in addition to the PLAN.md acceptance criteria)

**U1.** All state stays in `Service.qml`; the widget, one per monitor, only registers and binds (S6 pattern). Add a `view` property to the service (`onboarding`/`library`/`mini`/`full`), set through `Onboarding.view` once L3 merges; until then, a two-line rule (`mini` if loaded, else `library`) is fine and gets replaced in U3. Esc, click-away and the popout switch close the panel and never touch playback. Prove that with `playerStatus` before and after in fake mode. Remove the debug panel and `DebugCatalog.js` if nothing else uses it, along with their tests.

**U4.** `Cover.qml` loads `<dataDir>/covers/<asin>.jpg` asynchronously, keeps a fixed square aspect, and shows a themed placeholder (the book glyph) when the file is missing or fails. `StateBadge.qml` renders `LibraryUi.badge(...)`.

**U2a.** Bind to `PlayerController` and the library row of the loaded book. Skip uses 15 s for now (the setting arrives in R1). The library button switches the service view to `library`. Don't add a scrub bar, chapters or speed; those are U5.

**U2.** Search, sort and filter go through `Library.js` (`searchRows`, `sortRows`, `filterRows`), and every display decision through `LibraryUi.js`. The search field has focus when the drawer opens; ↑/↓ move, Enter plays, Esc closes, Space plays/pauses when the search is empty (ARCHITECTURE §6). Selecting a local book: hide the panel, play, and reopen on Mini once playback starts. Selecting a cloud book: enqueue `get`, show the progress on the row, then play. Remove from laptop is in the row menu; "Remove all downloads" asks first. Opening the drawer runs `sync` when `LibraryUi.syncDue` says so. Test every row state with `--fake-fail`, and the empty, no-results, loading and offline states. Use a `ListView` with delegates; don't build all 91 rows eagerly.

**U3.** Steps come from `Onboarding.step(status)`. Missing tools show `Onboarding.installCommand` with a copy button (`wl-copy`), never a run button. "Set up" runs `setup` with its progress events. "Connect Audible": the marketplace picker (default `us`), then `login-start`, then open the URL with `xdg-open`, then a paste field plus "Paste from clipboard" (`wl-paste`), then `login-finish` with the text on **stdin**, never in argv. Show "That doesn't look like the Amazon page address" when `Onboarding.looksLikeRedirect` is false, without sending it. Clear the field and the property as soon as it's sent. After success, show the clipboard notice when `done` reports it, then run the first `sync`. Offer "Use existing audible-cli login" when `doctor` or `status` shows one. A reconnect banner appears on `auth_failed` from any job. Disconnect sits in a small account row (name and marketplace) and asks first. **The pasted text must never reach a log line, an event, a file, or `recentEvents`.** Add a test that grep-checks the service code paths, and say how you checked it in the PR.

## 5. Review and merge

The same as M2 §5. One CLI implements and the other reviews the exact head. Codex has no live-shell access, so the implementer posts the in-shell evidence (IPC output, screenshots of fake data, journal excerpts) and Chris's hand-check results in the PR. Reviewers also check §2 of this brief, no logic in views, and (for U3) the secret handling. After PASS, tell Chris "U<n> PR #<num> passed review at <sha>", and Dante does the final check and merges. Stack the next branch on the previous one if you don't want to wait. **Each PR updates its own row in `docs/STATE.md` and ticks its PLAN checkbox**; Hopebox cards don't touch STATE, so you won't conflict with them.

## 6. G3 (Chris, with you driving)

Only after U1–U4 and U2a are merged. Quit any fake playback, delete the dev flag, restart the shell, and confirm real mode (one bar, 91 books). Then, with Chris doing all the clicking:
1. **J1:** Disconnect, then Connect Audible from the drawer. This deregisters the plugin's own device and registers a new one; books and the audible-cli login aren't touched. Check the account row shows his name, and the clipboard notice if it appears.
2. **J2, J3, J6** by hand on a short book. For J6, remove the downloaded test book and confirm it's still in the phone app.
3. The two G2 items not yet run in real mode: a chapter change, and `omarchy-restart-shell` during playback with the audio continuing.
4. **J7 spot check:** listen on the phone for a minute, then resume on the laptop at the phone's position.
5. **Themes:** with Chris's OK, one light and two dark themes (`omarchy-theme-list`, `omarchy-theme-set`), plus a live switch with the drawer open. Note his theme first and restore it at the end.
6. Record the result in `docs/STATE.md` in a PR. Then Chris uses it for a day; blockers get fixed before M4.

## 7. When you're stuck

If the docs and reality disagree, stop and write down what you saw; don't redesign around it. Exit code 0 is not proof: check the actual result. Before you report anything, check `git status` and the diff.

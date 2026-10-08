# Brief: P9, the Service split and orchestration reducers (Claude Code / Codex on HMSP-OMARCHYBEE)

You are breaking `Service.qml` (about 1,260 lines) into child objects and turning the untested orchestration into pure reducers with tests. The work comes from the whole-repo review (`docs/briefs/REVIEW-2026-10-06.md` F28, F29). It also covers one confirmed bug that was never placed (F38, the paused seek) and three small nits from the P8 review. Every desktop follow-up is in `main` and passed real mode with Chris (MANUAL-TEST `## Follow-ups (desktop)`, #85). This brief is self-contained. Read it in full before you start.

**What P9 is:** a refactor. Apart from F38 and nit 3 (§4), Chris must not be able to tell anything changed. The IPC answers, the views, the event log and `state.json` stay the same. If you find another bug along the way, write it up for Dante and don't fix it inside a refactor PR.

## 0. Before you start

1. **Ask Chris whether a book is playing.** If one is, ask him to pause it. Then bring the live plugin up to date: `cd ~/.config/omarchy/plugins/latentoperator.audible && git checkout main && git pull --ff-only` (to `c13855d` or later). That pull is docs only, but every pull hot-reloads the plugin, so do it only while paused. Confirm one `quickshell`, one bar per monitor, real mode and 91 books.
2. `~/Projects/oa-wt/` should be empty, because Chris clears the eight finished worktrees after #85. If anything is left, list it and ask before deleting. New worktrees go there, never inside `~/.config/omarchy/plugins/`.
3. Read `docs/STATE.md`, PLAN's P9 entry, REVIEW-2026-10-06 F28 and F29, and `docs/ARCHITECTURE.md` §2, §4.8, §5 and §6. Then read `qml/PositionSync.qml` (the child-object pattern to copy), `qml/lib/JobQueue.js` (the reducer pattern to copy) and `tests/qjs.py` (the harness, including `.import` support). The hard rules and dev loop of `docs/briefs/FOLLOWUPS-desktop.md` §2–§3 apply unchanged, and §2 below repeats the ones that matter most.
4. Tests: `~/.cache/oa-venv/bin/python -m pytest -q`, with nothing skipped and `OMARCHY_AUDIBLE_ALLOW_SKIP_QJS` unset. `main` is at 2,097 passed. `make lint` runs ruff check and ruff format.

## 1. What you're building

One branch and one PR each, in this order. Each PR starts from the current `origin/main`, so rebase after every merge. Don't stack PRs.

| # | Branch | Gist | Changes behaviour? |
|---|---|---|---|
| 1 | `p9-paused-seek` | F38: a seek, skip or chapter jump while paused is saved | **yes** (fix) |
| 1b | `p9-switch-report` | F39: a report from the next book never lands in the old book's snapshot | **yes** (fix) |
| 2 | `p9-lib-hygiene` | One home for each duplicated constant; P8 nits 1 and 2 | no |
| 3 | `p9-ipc` | `IpcHandler` moves to `qml/ServiceIpc.qml` | no |
| 4 | `p9-removals` | `qml/Removals.qml` + a pure removal reducer; P8 nit 3 | nit 3 only |
| 5 | `p9-catchup` | `qml/CatchupFlow.qml` + a pure read-bookkeeping reducer | no |
| 6 | `p9-signin` | `qml/SigninFlow.qml` (onboarding, login, clipboard) | no |
| 7 | `p9-sync-reducer` | `PositionSync` flush sequencing as a reducer in `Sync.js` | no |
| 8 | `p9-store-reducer` | `StateStore` adopt, replay and backup decisions as pure functions | no |
| 9 | `p9-player-machine` | `PlayerController` connect/launch/quit/relaunch as a pure reducer | no |

PR 1 (F38) merged as #86. Number 9 is the riskiest, because it is the code that keeps Chris's audio alive across shell restarts, so it goes last, once the pattern is proven. Tick P9 in PLAN only in PR 9.

## 2. Hard rules (short form; FOLLOWUPS-desktop §2 is the full list)

- **The shell runs in real mode, and Chris listens on it every day.** Develop in fake mode: with Chris's OK, pause, `touch /run/user/$(id -u)/omarchy-audible-dev-fake`, `omarchy-restart-shell`, and confirm fake mode before testing. **At the end of every session, delete the flag and restart once** so Chris is back in real mode, and tell him you did.
- **Never** run `position-push`, `logout`, `login-*`, `remove`, `get` or `setup` in real mode yourself. Never open, print or copy anything in `~/.config/omarchy-audible/` or `~/.audible/`, or any key, voucher or activation bytes.
- **No simulated input.** Drive the shell through IPC and check views with `grim -o DP-4` / `grim -o DP-5` screenshots. Batch anything that needs a hand into a hand-check list in the PR.
- Theme only through `qs.Commons` tokens. **No logic in views or in the new QML children beyond wiring:** decisions go in `qml/lib/*.js` (pure ECMAScript, `.pragma library`, no `Qt.*`, never throws) with QJSEngine tests. Don't edit `AGENTS.md`, `docs/SCOPE.md`, `backend/` or Omarchy's own files.
- Never start a second Quickshell. There must be exactly **one** `IpcHandler` with target `latentoperator.audible`, and it must be a child of the service (a widget is created once per monitor; see SPIKE-RESULTS "Why the service, not the widget").

## 3. How a split works (PRs 3–6)

Copy `PositionSync`:

- The child is a zero-size, invisible `Item` in `qml/` with plain properties for what it needs (`service`, `store`, `player`, `runner`), declared once in `Service.qml` with `service: root`. Don't give it a name that clashes with a JS qualifier Service already imports (`Catchup`, `Onboarding`, `Signin`, `Sync`, `Player`, `Drawer`…), which is why the names in §1 are what they are.
- The child owns its state, its timers, its `Process` objects and its functions. Nothing else writes that state.
- Job routing stays in Service's `JobRunner` handlers as one dispatch line per child, the way `sync.handleEvent` / `sync.handleFinished` already work. The child decides what a record means for it.
- **The names views and `BarWidget` use stay on Service** (`service.catchupNote`, `service.onboardingStep`, `service.removeBook(...)` and so on), as `readonly property alias` or a one-line forwarder, so no view changes in a split PR. Grep `qml/views`, `qml/components` and `BarWidget.qml` for every name you move and list the ones you kept in the PR. Moving views onto `service.<child>.x` is not P9 work.
- **Tests that read `Service.qml` as text** (`test_g3_fixes`, `test_ipc`, `test_p8_service`, `test_row_actions`, `test_signin_secret_paths`, `test_sync`) move with the code. Point them at the new file and keep every assertion. Never delete or weaken one to make a split pass. If a reducer makes a source-grep test redundant, replace it with a behaviour test in the same PR and say which.
- **Same-behaviour proof** for every no-behaviour PR, in fake mode, posted as before/after output (`main` vs branch): `playerStatus`, `libraryState`, `pushState`, `onboardingState`, `panelState` and the last `events` after this journey: pick B0FAKE0001 → `answer resume` if asked → `skip 30` → `playPause` (pause) → `playPause` (resume) → `chapter 1` → `quitPlayer` → `removeBook` on a local fake book → `syncNow`. Differences in positions and timestamps are fine. Any other difference needs a sentence. Zero QML warnings from our files after a restart.
- Update ARCHITECTURE §2 (file tree) and the relevant §5/§6 lines to name the new object.

## 4. Task notes

**1. F38, paused seek (fix first, before anything moves).** In `Service.qml`, the `Connections` on `player` sets `snapMs` on every position change but sets `snapDirty`/`snapUnpushed` only while playing. So a seek, ⏪/⏩ or chapter jump made while paused, followed by Stop, a book switch or a shell restart, is never written (Codex confirmed this in #55). Fix:
- Mark the position dirty when **the user** moves it while paused: a seek, skip or chapter jump through `PlayerController` (scrub bar, transport, chapter list/popup, IPC `skip`/`nextChapter`/`prevChapter`). Don't infer it from position deltas. A reattach after a shell restart reports a position too, and that must **not** count as listening (no new `last_played_at`, no push).
- A paused move is saved and pushed like a played one (Dante's call: the phone should follow a skip Chris made while paused). It follows the catch-up rule ARCHITECTURE §4.6 already states, where "a skip made while paused is kept".
- The decision goes in a lib with a test that fails on the old code. Hand check (fake mode): pause, ⏩ twice, Stop, play the book again: it resumes at the moved spot. Then restart the shell while paused, without moving anything: `state.json`'s `last_played_at` for that book doesn't change.
- Add F38 to STATE as its own row.

**1b. F39, book-switch report order (Dante placed 2026-10-07 from the PR 1 session; verify, then fix).** `Mpv.OBSERVED` puts `time-pos` at observe id 1 and `path` at id 7. If mpv sends B's `time-pos` before B's `path` in a switch from A to B, `onPositionMsChanged` still sees `path` = A, so `snapMs` takes B's position, and while playing it is marked as A's listening. `onBookSwitched` then saves and **pushes B's position as A's**, which silently moves A on the phone (ARCHITECTURE §4.6). A paused A with an F38 move has the same problem. If mpv first reports `path`/`time-pos` as null (unloaded), the existing guards hold, so whether this bites depends on mpv's real order.
- **Verify first (fake mode):** record the raw socket lines (a tee in `handleLine` behind the fake flag, or a second observer on the socket with `socat`) for 10 switches A→B while playing and 5 while paused after a move. Report the order of `time-pos`, `path`, `idle-active` and `file-loaded` in each, and whether a null `path` or `time-pos` comes between.
- **Fix either way, since it costs one guard:** a position report counts for the snapshot only when `Mpv.moveHitsPath(player.path, player.loadPath, player.loadArrived)` holds (F38's gate: no load on its way), so reports between sending `loadfile` and B's `path` + `file-loaded` are ignored. Reattach (`loadPath` "") keeps working. Put the decision in a lib function with vectors for both orders, and add a wiring test that fails on the old code.
- In-shell: switch A→B while playing, then read `state.json` and the account for A: A's `ms` is where A stopped, not B's position. Add an F39 row to STATE with the observed order.

**2. Lib hygiene.** F28's second half, plus P8 nits 1 and 2:
- `VIEW_*` lives only in `Panel.js` (`Onboarding.js` uses `.import "Panel.js" as Panel`). The key codes `KEY_ESCAPE/RETURN/ENTER` live in one lib (`Drawer.js` and `Signin.js` both define them today). Each glyph is defined once: a new `qml/lib/Glyphs.js` holds every `GLYPH_*` (they are spread over `Panel`, `Mini`, `Player`, `Drawer`, and `Drawer`/`Player` both define `GLYPH_DISMISS`). Views reference `Glyphs.X`, and libs that pick a glyph in logic `.import` it.
- The volume and speed ranges live once (`Mpv.js`: `MIN_SPEED`/`MAX_SPEED` plus new `MIN_VOLUME`/`MAX_VOLUME`). `Playback.withPlayerSettings` uses them instead of its own `0–130` / `0.5–3`. Put the `// A copy of state with the push queue replaced.` comment back above `withQueue`.
- Add one static test: every `Qualifier.UPPER_NAME` that a `.qml` file or a `.js` file under `qml/` references is defined in that qualifier's lib. That catches a blank icon from a typo, which no other test would.
- Screenshots of Library, Mini and Full before and after must match (ImageMagick AE, as in #80).

**3. `ServiceIpc.qml`.** Move the whole `IpcHandler` (public, status and test-only methods) into `qml/ServiceIpc.qml`. It holds a `service` property, and each method calls the service or its children. The fake-mode gate stays the first line of every test-only method, `Ipc.PUBLIC_METHODS`/`STATUS_METHODS` don't change, and `test_ipc.py` reads the new file. Check that `qs ipc show` lists the target once, with the same methods as on `main`.

**4. `Removals.qml`.** Owns `removeAfterUnload`, `unloadTimer`, `flushRemovals`, `abandonRemovals`, `removeAll`, `removeBook`'s unload branch, and the auto-remove path (`removeCandidate`, `autoRemoveTimer`, `removeIfStillFinished`, and the auto-remove half of `checkFinished` and `jobAllowed`). The pending-unload list and its transitions (add, drop on a new intent, flush when unloaded, abandon after the timeout) become a pure reducer with tests. **Nit 3 (behaviour):** a removal that came from auto-remove keeps saying so after the unload. Its event log and job purpose show auto-remove, not `user`, and turning `autoRemoveFinished` off before the flush cancels it, while a user's Remove is not affected. Careful: `jobAllowed`'s auto-remove gate calls `atEnd()`, which is false once the book is unloaded. P8 used purpose `user` partly to get around that. The gate for a post-unload auto-remove is the setting plus `Drawer.removalAllowed` (not busy), not `atEnd`. Fake-mode check with the `autoRemove` IPC: play B0FAKE0004 to the end with auto-remove on → the event log says auto; repeat and switch auto-remove off during the unload → nothing is removed.

**5. `CatchupFlow.qml`.** Also (Dante, from PR 2 #88): `FINISH_TRAILING_MS` is defined three times (`Positions.js`, `Playback.js`, `LibraryUi.js`); keep it only in `Positions.js` and `.import` it in the other two, with the PR 2 constant check covering it. Owns `pausedAtMs`, `catchupAsin`, `catchupReads`, `prefetched`, `catchupResults`, `catchupNote`, both catch-up timers, `cancelCatchup`, `prefetchCatchup`, `readCatchup`, `resumeCaughtUp`, `showCatchupNote` and the `purpose === "catchup"` event and finish handling. `playPause` stays on Service (it is public) and asks the child. The finish bookkeeping (drop the read, keep only this read's own result, clear `prefetched` only for the same book, decide whether the waiting ⏯ resumes) becomes one pure function in `Catchup.js` with vectors covering A-fails-while-B-is-prefetched.

**6. `SigninFlow.qml`.** Owns `reconnecting` through `loginStarting`, `settingUp`, `onboardingStep`, `loginPhase`, the `opener`/`copier`/`paster` processes, `clipboardRead`/`clearPaste`, `checkStatus`, `startSetup`, `startLogin`, `finishLogin`, `cancelLogin`, `importCliLogin`, `disconnect`, `reconnect`, `openUrl`, `copyText`, `readClipboard`, `onboardingFinished` and the `login-start`/`login-finish` record handling. `test_signin_secret_paths` must still prove the pasted text never lands in a property or argv. Check onboarding in fake mode with `fakeOnboarding` through every step, and Chris's hand check of the Connect screen in fake mode. **No real sign-in.**

**7. Sync reducer.** `PositionSync`'s `flush` → `handleEvent` → `handleFinished` → `sendNext` sequence becomes `Sync.step(state, event)` returning the next state plus effects (`run position-get`, `run position-push args`, `setQueue`, `flush later`, `finish result`). `PositionSync.qml` applies the effects, much as JobRunner switches on `JobQueue`'s actions. Vectors: a batch with drops and sends; a newer listening arriving mid-flush (the old entry is skipped, not sent); `stale` counting and reset (P6); offline backoff and reset (F18); a refused `run`; and the 25-entry batch boundary.

**8. Store reducer.** `StateStore`'s decisions become pure functions: adopt (parse, recovered → back up first, nothing written until the copy succeeds), pending-op replay order, and the retry on a failed backup. Vectors: ops made before load are applied after it in order; a corrupt file is copied aside before any write; a failed copy writes nothing and retries.

**9. Player machine.** `PlayerController`'s connection state (`wanted`, `attaching`, `launching`, `quitting`, `quitPending`, `relaunchPending`, `attempt`, `connection`, `lastError`, whether a load is pending) moves into a pure reducer (`qml/lib/PlayerMachine.js`) driven by events (`play`, `quit`, `connected`, `disconnected`, `retry_tick`, `give_up`, `probe_result`, `scope_gone`). It returns effects (`launch`, `connect`, `send_quit`, `flush_pending`, `subscribe`, `clear_key`, `begin_relaunch`, `reset_state`). The key never enters the reducer's state: carry a flag that a load is pending, and keep the options object in `PlayerController`. Vectors for the S5 pitfalls (SPIKE-RESULTS), quit during startup, play during a quit, an unexpected exit with and without a wanted book, a stale socket at reattach with a play waiting, and F22's `fadeBaseVolume` reset. In-shell: fake play → `omarchy-restart-shell` while playing → same mpv PID, reattached and playing; quit → relaunch → play; kill mpv while playing → "mpv exited unexpectedly" then reconnect.

## 5. Real-mode acceptance (with Chris, after PR 9 merges)

Quit fake playback, delete the dev flag, pull `main` into the live folder while paused, restart once, and confirm real mode. Chris does the clicking. Record each line in `docs/MANUAL-TEST.md` under `## P9 (desktop)`:

1. **F38:** pause, ⏩ a few times, Stop, play the book again: it resumes at the moved spot. Open the phone app: it shows the same spot.
2. **Catch-up:** pause for more than 30 s, move the book on the phone, ⏯ here: "Checking Audible…", then it jumps with the catch-up note.
3. **Push:** play a minute, pause: `pushState` shows `last` done, queue empty, no stale line.
4. **Player machine:** seek, a chapter jump, then `omarchy-restart-shell` during playback: the same mpv PID keeps playing, the shell reattaches, and Chris hears no break. Then Stop and play again.
5. **IPC:** `toggle`, `playPause` and `playerStatus` work; `libraryQuery` returns `error: dev only`.
6. **Removal:** remove a finished local book from Full ("Remove from this device"), then confirm it is still in the phone app. Only if Chris has one he is happy to remove; otherwise skip it and say so.
7. **Smoke:** `journalctl --user -b` shows zero QML warnings from our files after the restart.

## 6. Review and merge

The same as FOLLOWUPS-desktop §6. One CLI implements and the other reviews the exact head. The implementer posts the same-behaviour proof (§3), the in-shell evidence and any hand checks in the PR. Reviewers check that nothing outside the PR's row in §1 changed, that the moved state has exactly one writer, that the view-facing names are unchanged, that no source-grep test was weakened, and that each new reducer's tests exercise the transitions the QML used to do inline. After PASS, tell Chris "P9 <#> PR #<n> passed review at <sha>". Dante does the final check and merges, pinned to that SHA. Each PR adds or updates its own STATE row.

At the end of every session: live folder on `main`, dev-fake flag deleted, one restart, real mode confirmed. Tell Chris you did.

## 7. When you're stuck

If the docs and reality disagree, stop and write down what you saw. Don't redesign around it. If a split turns up a hidden coupling (a child would need to write another child's state), stop and describe it for Dante. Don't add a back-channel. Exit code 0 is not proof: check the actual result. Before you report anything, check `git status` and the diff.

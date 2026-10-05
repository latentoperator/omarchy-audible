# Brief: M2 player service, laptop part (Claude Code / Codex on HMSP-OMARCHYXPS)

You are building the QML player service for the Omarchy Audible plugin on Chris's laptop, inside the real Omarchy shell. This brief is self-contained. Read it in full before you start.

## 0. Before you start

1. `cd ~/Projects/omarchy-audible && git checkout main && git pull --ff-only`. This directory **is** the live plugin: `~/.config/omarchy/plugins/latentoperator.audible` is a symlink to it.
2. Read `docs/STATE.md`. Overnight, Hopebox ran four tasks: **B8, P1a, P3a and P4a**. Check which ones merged. Status is in the "Where we are" table and on PRs #14 and up.
   - **If B8 has not merged, stop and tell Chris.** Until it does, fake mode writes into the real plugin folders, which hold Chris's real login and catalog.
   - If B8 merged but some of P1a/P3a/P4a didn't, do them first, on the laptop, exactly as specified in `docs/PLAN.md`, before the matching laptop task.
3. Then read, in order: `AGENTS.md`, `docs/ARCHITECTURE.md` (§2, §3, §4.2, §4.8, §5 and §6), `docs/PLAN.md` M2, and `docs/SPIKE-RESULTS.md` (S5 and S6). **The S5 pitfalls list is mandatory reading.** Working spike code is in `spikes/s5-s6-Service.qml` and `spikes/s6-BarWidget.qml`.
4. Read the reference plugins, but don't copy them blindly:
   - `~/.config/omarchy/plugins/quickshell.spotify/`: service, bar widget, backend client and mini player. It's the closest analogue.
   - `/usr/share/omarchy/shell/README.md`, `plugins/README.md`, `Ui/`, `Commons/`.

## 1. What you're building

These tasks are in `docs/PLAN.md`, in this order. Each one is one branch and one PR.

| Task | Branch | Gist |
|---|---|---|
| P1 | `p1-service-jobrunner` | `Service.qml` singleton plus `qml/JobRunner.qml` (spawns `bin/omarchy-audible` with `Process`, feeding stdout chunks to `qml/lib/Ndjson.js` and queueing through `qml/lib/JobQueue.js`), plus a **temporary debug panel** |
| P2 | `p2-player-mpv` | `qml/PlayerController.qml`: mpv in a systemd scope, socket IPC, reattach, sleep timer |
| P3 | `p3-library-model` | `qml/LibraryModel.qml` on top of `qml/lib/Library.js`, plus the `state.json` writer |
| P4 | `p4-position-sync` | push and resume wiring on top of `qml/lib/Positions.js` |
| P5 | `p5-ipc` | `IpcHandler` methods plus a README section with a Hyprland bind |

Then **G2**, which Chris runs (see §6).

Logic belongs in `qml/lib/*.js`, which is pure JavaScript with no Qt imports and has unit tests. The QML files are thin wiring around it. If you need new logic, add it to a `qml/lib` file with a test, not inline in QML.

## 2. Hard rules

- **Fake mode only, through the dev flag.** Chris's real login, catalog and books are on this laptop. While developing, the service must run every backend command in fake mode. Implement it this way in P1: if the file `$XDG_RUNTIME_DIR/omarchy-audible-dev-fake` exists when the service starts, add `OMARCHY_AUDIBLE_FAKE=1` to every backend process environment and show "FAKE" in the debug panel. The flag lives on tmpfs, so a reboot always returns to real mode. Create it with `touch /run/user/$(id -u)/omarchy-audible-dev-fake` before you restart the shell.
- **Never** run `position-push`, `logout`, `login-*`, `remove` or `get` in real mode, and never let the service do so. Real-mode `status`, `doctor`, `local` and `sync` are fine. Never open, print or copy anything in `~/.config/omarchy-audible/` or `~/.audible/`.
- **Never** edit Omarchy's own files (`/usr/share/omarchy`, `~/.local/state/omarchy/`, other plugins), and never start a second Quickshell (`qs`/`quickshell`) process.
- **Restarting the shell is visible to Chris.** It flashes the bar and closes any open panels. Say what you're about to do, then run `omarchy-restart-shell`. Don't loop restarts. If a restart leaves the bar missing, run it once more and then stop and tell Chris.
- Theme only through `qs.Commons` tokens (`Color.*`, `Style.*`), and never hard-code a color.
- Never commit symlinks, `.venv`, real data, or screenshots that show real titles.
- `AGENTS.md` is protected. Don't edit it, `docs/SCOPE.md`, or anything under `backend/`, unless a task explicitly says so. Any backend gap goes in the PR description as a finding.

## 3. Dev loop

| You changed | Reload with |
|---|---|
| `BarWidget.qml` or views | `omarchy-shell shell rescanPlugins` |
| `Service.qml`, anything it loads, or `qml/lib/*.js` | `omarchy-restart-shell`. Playback in the mpv scope survives a restart. |

- Enable the plugin once, at the start of P1: `omarchy plugin enable latentoperator.audible`. That adds the book icon to the bar.
- Shell logs: `journalctl --user -f -o cat | grep -iE "audible|qml"`. QML warnings from our files must be zero before you open a PR.
- Lint: `/usr/lib/qt6/bin/qmllint` on changed `.qml` files. Unresolved `qs.*` and `Quickshell` import warnings are expected; anything else is not.
- Drive the service through IPC: `omarchy-shell latentoperator.audible <method> [args]`. List the methods with `qs ipc show`.
- Screenshots for the PR: `grim -g "$(slurp)" /tmp/x.png`, or `grim /tmp/x.png`. Fake titles only.
- Python and JS tests: create the env once with `python3 -m venv ~/.cache/oa-venv && ~/.cache/oa-venv/bin/pip install -q pytest jsonschema pyside6-essentials`. Run `~/.cache/oa-venv/bin/python -m pytest -q` from the repo root. The venv lives outside the repo; never create one inside it. The `qml/lib` tests must **run**, not skip.
- Before every PR: `make check-symlinks` and `OMARCHY_PATH=/usr/share/omarchy omarchy plugin validate .`.

## 4. Task notes (in addition to the PLAN.md acceptance criteria)

**P1.** Use `Process` for backend commands. Backend commands are short-lived and may die with the shell. mpv is different, see P2. The service reads the paths from the `status` event, which B8 added. **Don't recompute paths in QML.** The debug panel is a small temporary view in the existing bar widget's `KeyboardPanel`. Follow the S6 pattern: the widget registers with the service, and all state lives in the service. It shows the fake/real mode, the job queue, recent events, and buttons for `status`, `sync`, and `get <first catalog asin>`. Mark it with `// TEMPORARY (removed in U1)`. For acceptance, run `status` and `sync` from the panel in fake mode and show the events.

**P2.** Launch mpv exactly as ARCHITECTURE §5.1 describes, with `Quickshell.execDetached` and `systemd-run --user --scope --unit=omarchy-audible-mpv`, never with `Process`. Handle every S5 pitfall:
- Subscribe on the derived `connected` property.
- Recreate the `Socket` on each retry.
- An existing socket file doesn't prove mpv is alive.
- Detect a failed launch by timeout.
- Retry only while `state.json` says a book is loaded, with backoff and a cap.

Test with the fake m4b from `get --fake`. It's a 3-chapter sine wave, so turn the volume down. For acceptance, do all of these and record each one in the PR with the observed property values:
- play, pause, ±skip, chapter jump, speed change;
- the sleep timer (use a 10 s timer for the test);
- `omarchy-restart-shell` mid-playback: the audio continues and the state reattaches with the same mpv PID;
- `kill -9` on mpv: it's detected and surfaced.

**P3.** `state.json` is written only by the service, atomically: write to a temp file in the same dir, then rename. Use `FileView` if its atomic write is confirmed; otherwise run `Process` with a small stdlib Python one-liner that reads the content on stdin. Save every 10 s while playing and on pause, switch and quit. For acceptance, run sort, filter and search against the fake catalog through IPC or the debug panel. Then `kill -9` the shell process mid-playback (find it with `pgrep -f "qs -c"`, ask Chris first, and restart it with `omarchy-restart-shell`) and show that the position loss is at most 10 s.

**P4.** All push decisions go through `Positions.js` (`shouldPush`, `enqueue`, `flushPlan`). Push about every 60 s while playing, and on pause, stop, switch and quit. Re-read the remote position (`position-get`) right before each push. Pass `--at <last local listening time>` to `position-push`. Fake mode's position store stands in for Audible. For acceptance, run the five scenarios from PLAN.md P4 in fake mode. Simulate a newer remote position by running `position-push --fake` by hand with a later `--at`.

**P5.** Add the methods `toggle`, `playPause`, `skip <seconds>`, `nextChapter`, `prevChapter` and `openLibrary`. All arguments and return values are strings. Return `"ok"` or a short error string, never throw. `toggle` and `openLibrary` operate on the registered widget surface, as in the S6 spike. Add a README section with the call syntax and `bind = SUPER, A, exec, omarchy-shell latentoperator.audible toggle`. Don't add the bind to Chris's Hyprland config.

## 5. Review and merge

Implement with one CLI and review with the other. For example, Claude Code implements and Codex reviews, or the other way round.

1. The **implementer** pushes the branch and opens the PR with `gh pr create`; `gh` is logged in on the laptop. The PR body includes the acceptance checklist with evidence for each item (IPC output, log excerpts, property values, screenshot paths), the test counts, the `qmllint` result, and anything unverified. It does **not** merge.
2. The **reviewer** checks the exact head. Run `git rev-parse HEAD`, which must match the PR head, and work read-only. Check:
   - the PLAN.md acceptance criteria, item by item;
   - §2 of this brief;
   - the S5 pitfalls (P2);
   - single-writer ownership (§4.8);
   - no logic in QML that belongs in `qml/lib`;
   - no real-mode mutating commands.

   Rerun the tests and spot-check one in-shell behavior yourself. Post `PASS — exact-head review <sha>` or a numbered list of findings as a PR comment. On FAIL, the implementer fixes the same branch and the reviewer re-checks the new head.
3. After PASS, tell Chris: "P<n> PR #<num> passed review at <sha>." Chris passes it to Dante, who does the final check and merges.
4. **Don't wait for the merge.** Start the next task on a branch made from the previous task's branch, and set the PR base to that branch. When the earlier PR merges and its branch is deleted, GitHub moves the base to `main` automatically.

## 6. G2 (Chris, with you driving)

With the dev flag set and the fake book, use only IPC and the debug panel to start, pause, skip, change chapter, and restart the shell, showing that playback continues. Then **delete the dev flag** and restart the shell, so the service runs in real mode with the real catalog. Chris starts one short real book (he picks which), checks one ±skip and one pause, and stops it. That real playback is the first time the service pushes a real position. That's fine and expected, but tell Chris before it happens. Record the result in `docs/STATE.md`, in a PR like the others.

## 7. When you're stuck

If the docs and reality disagree (an API that doesn't exist, a spike result that doesn't hold), stop and write down what you saw. Don't redesign around it. Note it in the PR or tell Chris. Exit code 0 is not proof; check the actual result. Before you report anything, check `git status` and the diff.

# Project plan — Omarchy Audible

Read [SCOPE.md](SCOPE.md) (what and why) and [ARCHITECTURE.md](ARCHITECTURE.md) (how) first. This file is the work breakdown. It is written so that tasks can be handed to separate, cheaper agents one at a time.

## How to use this plan

- Work milestone by milestone. **Do not start a milestone until the previous gate is passed.**
- Each task has an ID, dependencies, an acceptance checklist, and a tier:
  - **A** = a cheap or fast agent can do it from this doc alone.
  - **B** = a mid-tier agent, but needs a human or strong-model review of the diff before merge.
  - **S** = spike or design-sensitive work. Do it with the strongest available model, or pair with the maintainer, and write findings down.
- One task = one branch = one PR. Keep PRs small. Reference the task ID in the title (`B3: sync command`).
- If a task's assumption turns out false, **stop and write it up** in `docs/SPIKE-RESULTS.md` rather than improvising a different design. The maintainer decides.
- Update the checkbox in this file in the same PR that completes the task.

## Dependency graph (summary)

```
M0  S1 S2 S3 S4 S5 S6   (all independent, run in parallel)  ──▶ GATE G0
M1  B1 → B2 → B3 → B4 ; B5, B6, B7 after B1                 ──▶ GATE G1
M2  P1 → P2 → P3 ; P4 after P2                              ──▶ GATE G2
M3  B9 → B10 ; L1 → L2 → L3 (Hopebox) ; U1 → U4 → U2a → U2 → U3 (laptop) ──▶ GATE G3  (first usable build)
M4  U5, U6, U7 after G3 ; S7 (desktop spike) → B11 if it passes ──▶ GATE G4
M5  R1 … R7                                                 ──▶ release v0.1.0
```
M1 (backend) and M2/M3 (QML) can overlap after G0 because the fake backend freezes the protocol.

---

## M0 — Spikes and scaffolding

Goal: replace every ❓ in ARCHITECTURE.md with a ✅ or a documented fallback. Output goes in `docs/SPIKE-RESULTS.md` (one section per spike: question, method, result, decision, code snippet that works).

- [x] **S1 — Programmatic Audible login** (tier S) — done 2026-10-04, see SPIKE-RESULTS.md
  Prove the in-drawer login (nice-to-have; a one-time terminal login is the fallback): build the sign-in URL, take a pasted redirect URL, register a device, write an auth file, get activation bytes. Use the `audible` library's `login`/`register` modules (read their source and docs at audible.readthedocs.io).
  Done when: a throwaway script `login-start` prints a URL, `login-finish <pasted>` produces a working auth file, `audible -P <profile> library list` works with it, and the pasted URL is not written anywhere. Also test: an existing-`~/.audible` import. Note the marketplaces supported and any CAPTCHA/2FA behavior seen.
  *Fallback if impossible:* document why, and propose the copy-paste-a-command alternative.

- [x] **S2 — Download and decrypt both formats** (tier S) — done 2026-10-04, see SPIKE-RESULTS.md
  Using the plugin-owned config dir (`AUDIBLE_CONFIG_DIR`), download one `.aax` book and one book that is **aaxc-only** (find one in the library, or note none exists). Decrypt both to m4b with `ffmpeg -c copy`. For aaxc, prove `-audible_key/-audible_iv` from the voucher JSON.
  Done when: both produce playable m4b with chapters and the sanity check (duration within 1% of catalog) passes. Record the exact commands and the voucher JSON field names. Measure peak disk use during conversion.

- [x] **S3 — Position write-back** (tier S) — done 2026-10-04 incl. phone-app check, see SPIKE-RESULTS.md
  Find a reliable way to write "last position heard" so the phone picks it up (the community-documented endpoint involves an `acr` value from a content-license request). Verify on a real book by pushing a position and reading it back with `lastpositions`, then confirm in the Audible phone app.
  Done when: a script does a round trip, or `SPIKE-RESULTS.md` records that it's unreliable and D4 is resolved to "read-only sync". Restore any position you changed afterward.

- [x] **S4 — Catalog fields and multi-part books** (tier S) — done 2026-10-04, fixture in `fixtures/library-sample.json`
  Use the raw `1.0/library` endpoint (paged, `num_results` ≤ 50) to obtain: subtitle, series name and number, `content_type`, `content_delivery_type`, runtime, cover URLs, `listening_status`, `percent_complete`. Pick the smallest `response_groups` that works without timeouts. Examine a `MultiPartBook` (e.g. the C. S. Lewis collection): does `download` produce one file or several? Are chapters sane?
  Done when: a sample JSON for 5 books is saved to `fixtures/` (sanitized, invented titles) and D5 is decided.

- [x] **S5 — mpv under Quickshell** (tier S) — done 2026-10-04, see SPIKE-RESULTS.md
  In a throwaway plugin, start mpv detached with an IPC socket, connect from QML via `Quickshell.Io` `Socket`, observe `time-pos`/`pause`/`chapter-list`, send `seek` and `loadfile … start=`. Restart the shell (`omarchy-restart-shell`) and prove mpv keeps playing and QML reattaches. Decide between `execDetached` and `systemd-run --user --scope`.
  Done when: a 40-line QML prototype does all of the above, and the decision is recorded.

- [x] **S6 — Panel + bar-widget mechanics** (tier S) — done 2026-10-04, see SPIKE-RESULTS.md
  Study `quickshell.spotify` and `panels/audio`. Determine: how a third-party bar widget opens/toggles its own panel anchored to the icon; how to size the panel; how to close on click-away/Esc; how to read theme tokens; how to register a shell IPC target; how the manifest `schema` appears in settings; what the third-party capability facade blocks. Build the smallest widget → panel → close loop.
  Done when: a book-glyph widget opens a themed empty panel that closes on Esc/click-away, and the answers are in `SPIKE-RESULTS.md`.

- [x] **A0 — Scaffolding** (tier A, parallel with spikes)
  Create `manifest.json` (id `latentoperator.audible`, kinds `service`, `bar-widget`, `panel`, entry points per ARCHITECTURE §2), empty `Service.qml`/`BarWidget.qml`/`Panel.qml` that load cleanly, `bin/omarchy-audible` stub, `backend/` package skeleton, `tests/`, `pyproject.toml` (pytest only as dev dep), `.editorconfig`, a `Makefile` with `test`, `lint`, `dev-link` (symlink into `~/.config/omarchy/plugins/`), `dev-unlink`.
  Done when: `make dev-link && omarchy-shell shell rescanPlugins` lists the plugin without errors (if the shell refuses a symlinked plugin dir, switch `dev-link` to an rsync-based sync and note it), `omarchy plugin validate .` passes, the repo contains no symlinks (add a `make check-symlinks` target: `find . -type l -not -path './.git/*'` must print nothing), and `make test` runs (even with zero tests). Add `validate` and `check-symlinks` to `make lint`.

**GATE G0** — maintainer reviews `SPIKE-RESULTS.md`, resolves D4 and D5, and confirms the architecture still holds. Edit ARCHITECTURE.md to reflect reality before continuing.
✅ **Passed 2026-10-04.** Chris approved: D5 no special handling for multi-part books; D4 ship write-back with local-listening-only push rules; aaxc first with aax fallback; chapters rebuilt from Audible's list; D1 AGPL-3.0-only; no `panel` kind; IPC target `latentoperator.audible`; `login-finish` reads stdin. ARCHITECTURE now has the ownership contracts (§4.8) and a minimal Mini view moved into M3 (U2).

---

## M1 — Backend

All commands follow the protocol in ARCHITECTURE §4.2. Build the **fake mode first** so everything after it is testable offline.

- [x] **B1 — Launcher, protocol helpers, fake mode skeleton** (tier B; needs A0)
  `bin/omarchy-audible` (stdlib only) dispatches subcommands; shared `emit()` NDJSON writer; error codes; secret-scrubbing logger; the **job lock** from ARCHITECTURE §4.8 (non-blocking `flock` on `job.lock` for job commands only, `error(code=busy)` when held; `job.json` helper); `--fake` / `OMARCHY_AUDIBLE_FAKE=1` switch; `status` and `doctor` working (checks for `mpv`, `ffmpeg`, `ffprobe`, `python`, `wl-paste`, `xdg-open`, `systemd-run`, venv, auth).
  Acceptance: `status` and `doctor` output validates against `tests/schemas/*.json`; works with no venv; unknown command exits nonzero with an `error` event; a second job command while one holds the lock gets `busy`; a non-job command (`status`) succeeds while the lock is held.

- [x] **B2 — Setup/venv bootstrap** (tier B; needs B1)
  `setup` creates the venv, installs the pinned `audible-cli` and `audible[cryptography]` **and this repo's `backend/` package** (so `venv/bin/python -m omarchy_audible` works), streams progress events, is idempotent, and cleans up on failure. Pins live in one place (`backend/requirements.lock`; S1–S4 used audible-cli 0.6.0 / audible 0.12.0).
  Acceptance: from a clean `~/.local/share/omarchy-audible`, `setup` yields a venv where `python -c "import audible, omarchy_audible"` works and the launcher dispatches into it; second run is a no-op; killing it midway then re-running recovers.

- [x] **B3 — Auth commands** (tier B, S1 result required; needs B2)
  `login-start`, `login-finish`, `login-import-cli`, `logout`, plus `status.authenticated/account/marketplace`. Implements ARCHITECTURE §4.7 exactly; working reference code is `spikes/s1_login.py`. `login-finish` reads the URL from **stdin**. Files created `0600` under umask 077. The clipboard-history check and `logout` deregistering only this device are part of the task.
  Acceptance: unit tests with mocked `audible` calls; file-mode test (including an import from a `0644` source); a test asserting the pasted URL and code never appear in argv, any log line, any event, or any file; expired/bad-URL tests; a test that `deregister_all=True` appears nowhere; a test that `logout` after `login-import-cli` (or with no recorded origin) makes **no** deregister call; manual run against a real account by Dante on the laptop.

- [x] **B4 — Catalog sync** (tier B, S4 result required; needs B3 or fake mode)
  `sync` pages the library (`num_results=50`, groups per ARCHITECTURE §4.5), builds `catalog.json` per the schema, filters out `Podcast*` types only (**keeps `Lecture`**), downloads missing covers (thumbnail ~252 px), fetches remote positions in batches of ≤ 25 into **`remote.json`** (never `state.json`, which the service owns), and writes everything atomically. Progress events per page. Never pushes a position.
  Acceptance: fake mode yields the fixture catalog; real mode matches `audible library list` count (minus filtered items); interrupted sync leaves the old catalog intact.

- [x] **B5 — `get` / `cancel` / `local` / `remove`** (tier B, S2 result required; needs B1)
  Implements the §4.3 pipeline (aaxc first, aax fallback; chapters rebuilt from `chapters.json`; 2.1× free-space pre-flight; `acr` cached in `meta.json`), §4.4 safety, and `cancel` per §4.8. Fake mode generates a 3-chapter sine m4b plus a fake `chapters.json` with a different chapter count, and simulates progress and failures (`--fake-fail disk|network|decrypt|novoucher`).
  Acceptance (all as pytest): atomic rename; `.partial` and raw file removed on success **and** on each failure mode; `cancel <asin>` mid-download (from a second process) cleans up and the job emits `error(code=cancelled)`; `novoucher` falls back to aax; output chapter count equals the `chapters.json` flat list; free-space pre-flight; `remove` refuses a path outside `booksDir` and symlinks; `remove` never invokes any network call (assert by running with network access blocked); the "no mutating API calls" grep test from ARCHITECTURE §4.4 (only `PUT 1.0/lastpositions/` allowed). Real-account check of one aaxc and one aax book by Dante on the laptop.

- [x] **B6 — Positions** (tier B, S3 result required; needs B1)
  `position-get` (writes `remote.json`) and `position-push <asin> <ms>`. A pure newest-wins `merge()` helper that the service's QML port must match. `position-push` re-reads the remote position first and refuses with `error(code=stale)` when remote is newer than the pushed local timestamp (ARCHITECTURE §4.6 push rules).
  Acceptance: unit tests for merge edge cases (equal timestamps, missing remote, remote newer); the stale-refusal test; `lastpositions` batching ≤ 25; `acr` read from `meta.json`, else fetched from content metadata; a test that `sync` never calls `position-push`. Real-account round trip with restore by Dante on the laptop.

- [x] **B7 — Protocol schemas and contract tests** (tier A; needs B1; extended as commands land)
  JSON Schema file per event type; a test that runs every command in fake mode and validates every emitted line.
  Acceptance: CI-style `make test` fails if a command emits an unknown or malformed event.

**GATE G1** ✅ passed 2026-10-04 — a README section "Backend CLI" documents every command with an example. The maintainer runs `sync` and `get` against the real account, and `remove` leaves the Audible account unchanged.

---

## M2 — Player service (QML)

Depends on S5/S6 results and the fake backend.

**Split (2026-10-04).** Hopebox can't run the Omarchy shell, so M2 is done in two parts.
- **Tonight, Hopebox Kanban:** B8, then the pure-logic halves P1a → P3a → P4a. Each one is a standalone JavaScript library under `qml/lib/` with no Qt imports. It's tested from pytest through PySide6's `QJSEngine`, which uses the same JS engine as Quickshell.
- **Next, laptop agent:** the QML wiring and in-shell acceptance for P1, P2, P3, P4 and P5, then G2. The brief is in [briefs/M2-laptop.md](briefs/M2-laptop.md). The laptop parts import the `qml/lib/` libraries rather than re-implementing them.

- [x] **B8 — Fake mode uses its own folders** (tier B; needs B1–B7)
  Today `--fake` runs offline, but it reads and writes the **real** plugin folders. `sync --fake` overwrites the real `catalog.json`, `get --fake` writes into the real books folder, and `status --fake` claims a login. The laptop now holds a real login and catalog, so in-shell testing in fake mode would clobber them. In fake mode, `Paths` must resolve to separate roots: `<XDG_CONFIG_HOME>/omarchy-audible-fake`, `<XDG_DATA_HOME>/omarchy-audible-fake`, `<XDG_RUNTIME_DIR>/omarchy-audible-fake`, and books at `<data>/omarchy-audible-fake/books`. In fake mode, `OMARCHY_AUDIBLE_BOOKS_DIR` is **ignored**. Add `config_dir`, `data_dir`, `runtime_dir` and `books_dir` (absolute strings) to the `status` event in both modes, updating the schema first, so the QML never recomputes paths. Fix the README "Backend CLI" fake-mode sentence.
  Acceptance: a test runs every command in fake mode with HOME and XDG pointing to a tmp tree that already contains a real-mode layout (dummy `auth.json`, `catalog.json`, `remote.json`, a book dir), and asserts that nothing under the real-mode paths changed: same bytes, same mtimes, no new files. `status --fake` reports the fake dirs, and real-mode `status` reports the real dirs. The contract test still covers every command.

- [x] **P1a — NDJSON + job-queue logic** (tier B; needs B8)
  `qml/lib/Ndjson.js`: a line splitter that buffers partial chunks; parse each line; classify `done`/`error`/`progress`/other; non-JSON lines become a `{type:"_bad_line"}` record (truncated to 200 chars, never thrown); `finish(exitCode, events)` returns the job outcome. A missing final `done`/`error` is an `internal` error, and exit code 3 (or `error.code=busy`) is `busy`. `qml/lib/JobQueue.js`: a pure state machine. Job commands (the §4.8 list) run one at a time in FIFO order. Non-job commands bypass the queue. A `busy` outcome re-queues once after a delay the caller supplies, then fails. `cancel(asin)` drops a queued `get` or returns "send the cancel command" for the running one.
  Acceptance: QJSEngine pytest suite covering chunk boundaries (a line split across 3 chunks, several lines per chunk, a trailing line without a newline at exit), bad lines, every `ErrorCode` in `protocol.py`, ordering, bypass, the busy retry, and cancel in both states. Feed recorded fake-mode output from **every** backend command through `Ndjson.js`, and assert that it reproduces the B7 contract outcome.

- [x] **P3a — Library logic and `state.json`** (tier B; needs P1a)
  `qml/lib/Library.js`: `buildRows(catalog, remote, state, local, jobs)` returns one row per catalog book with the §5.3 state (`cloud`/`queued`/`downloading`/`converting`/`local`/`error`, where `local` comes from the local scan and the rest from `jobs`), position (newest-wins merge), progress percent, and `recentKey = max(state.last_played_at, remote.updated_at)`. Also `sortRows(rows, "recent"|"added"|"title"|"author")` (stable; title ignores a leading "The"/"A"/"An" and case; author sorts by the first author's surname, skipping honorifics such as "Dr." and suffixes such as "Jr." — fixed after U2), `filterRows(rows, "all"|"local"|"in-progress")`, and `searchRows(rows, text)` (title, subtitle, authors, narrators, series; case- and accent-insensitive). `state.json` schema v1, documented in ARCHITECTURE §3 (this task may edit §3): `{"schema":1,"books":{asin:{"ms","updated_at","last_played_at","played_since_download","finished"}},"push_queue":[{"asin","ms","at"}],"volume","speed"}`. Add `parseState(text)`, which never throws: garbage, a wrong schema or a missing file returns an empty v1 and a `recovered` flag. Add `serializeState(obj)`, which is deterministic and keeps unknown keys.
  Acceptance: QJSEngine suite against `fixtures/library-sample.json` run through the backend's own `build_catalog`, so the shapes are real. Cover every sort, filter and search case, including accents and articles, the state derivation for every job state, and the parse/serialize round trip, including recovering from truncated JSON.

- [x] **P4a — Position and push rules** (tier B; needs P3a)
  `qml/lib/Positions.js`: `parseUpdatedAt` and `merge` ported from `backend/omarchy_audible/positions.py`. A shared vector file `tests/fixtures/position-vectors.json` (at least 20 cases, including the Audible no-timezone format, `Z`, offsets, null, equal timestamps and garbage) is asserted against **both** the Python and the JS implementation. Also `resumeMs(local, remote)`; `shouldPush(book)`, which is true only when `played_since_download` is set and the position changed since the last push; `enqueue(queue, push)`, which keeps the newest per asin; `flushPlan(queue, remoteNow)`, which splits the queue into send and drop, where drop means the remote is newer than the queued `at` (§4.6); `isFinished(posMs, durMs, eofReached)`, meaning EOF or within 30 s of the end; and `autoRemoveAllowed(setting, finished, isPlaying)`.
  Acceptance: the vector file passes on both sides. Tests cover: a book never played locally is never pushed; a newer remote wins on resume; a stale queued push is dropped; offline pushes accumulate one per asin; auto-remove never fires while playing or with the setting off.

- [x] **P1 — Service skeleton and JobRunner** (tier B; needs A0, B1, P1a; laptop)
  `Service.qml` as `keepLoaded` singleton. `JobRunner.qml` spawns backend commands, parses NDJSON from stdout, exposes `running`, `progress`, `lastError`, and emits per-event signals. Handles process exit and non-JSON lines defensively.
  Acceptance: a debug panel (temporary) runs `status` and `sync` in fake mode and shows events.

- [x] **P2 — PlayerController (mpv)** (tier S/B; needs S5, P1; laptop)
  Implements ARCHITECTURE §5.1–5.2 including reattach after shell restart, `observe_property` handling, resume via `start=`, chapter list parsing, and the skip/chapter/speed commands. Includes the sleep timer with a 5 s fade.
  Acceptance: with a fake m4b — play, pause, ±skip, chapter jump, speed change, sleep timer; `omarchy-restart-shell` mid-playback and audio continues and state reattaches; mpv crashing is detected and surfaced.

- [x] **P3 — LibraryModel and persistence** (tier B; needs P1, P3a, B4/B5 in fake mode; laptop)
  Merges `catalog.json`, `remote.json`, `state.json`, and the local-books scan into one list model with the book state machine (§5.3), sort (recent/added/title/author), filter (all/local/in-progress), and search. The service is the **only** writer of `state.json` (§4.8), with atomic writes; saves position every 10 s while playing and on pause/switch/quit.
  Acceptance: sort/filter/search verified against the fixture catalog; kill -9 the shell mid-playback and the position loss is ≤ 10 s.

- [x] **P4 — Remote position sync + finished handling** (tier B; needs P2, P4a, B6; laptop)
  Push every ~60 s and on pause/stop/switch/quit, following the push rules in ARCHITECTURE §4.6 (local listening only; never stale); failures queued and retried; resume from newest of local/remote; finished detection and optional auto-remove (setting, default Off).
  Acceptance: simulated remote-newer position wins on play; a book that was never played locally is never pushed; offline pushes are queued and flushed later; a queued push that has become stale is dropped; auto-remove only fires when the setting is on and never during playback.

- [x] **P5 — Shell IPC target** (tier A; needs P2, S6; laptop)
  Registers `latentoperator.audible` (in `Service.qml`) with `toggle`, `playPause`, `skip`, `nextChapter`, `prevChapter`, `openLibrary`.
  Acceptance: each method works from a terminal using the call syntax documented in S6; documented in README with a sample Hyprland bind.

**GATE G2** — you can start, pause, skip, change chapter, and restart the shell without losing playback, driven only by IPC calls and a debug panel. No real UI yet.

---

## M3 — First usable UI

**Split (2026-10-05).** As in M2: Hopebox Kanban builds the pure logic and the two backend fixes the UI needs; the laptop agent builds the QML views in the real shell, following [briefs/M3-laptop.md](briefs/M3-laptop.md).
- **Hopebox, two chains that run side by side:** B9 → B10 (backend) and L1 → L2 → L3 (pure JavaScript under `qml/lib/`, tested through PySide6 `QJSEngine` like P1a/P3a/P4a). Implementers tick their own checkbox here but **do not edit `docs/STATE.md`**, so the two chains never conflict; Dante updates STATE.
- **Laptop:** U1 → U4 → U2a → U2 → U3, then G3 with Chris. U1 needs nothing new and can start at once. Each later task waits for the Hopebox piece it imports.

- [x] **B9 — `status` fields and fake sign-in states for onboarding** (tier B; needs B3, B8)
  Three changes; update `tests/schemas/status.json` and ARCHITECTURE §4.2 first. (1) **Account name.** `account` is `null` for a login made by `login-finish`, because it registers with `with_username=False` and Amazon returns no email. When `account.json` has no account, fall back to the first name in the saved login's `customer_info` (`given_name`, then `name`), read from `auth.json` as plain JSON: no network, no `audible` import. Never use `user_id`. `login-finish` and `login-import-cli` also store that fallback in `account.json` when there is no email. A masked email still wins when there is one. (2) **`venv_ready`** (bool, the same check `ready` already uses), so the UI can tell "run setup" apart from "connect". (3) **Fake sign-in states**, so the onboarding view can be tested without the real account. Today `status --fake` always says signed in, even after `logout --fake`. In fake mode only: a fresh fake tree starts signed in (so the M2 flow and existing tests keep working); `logout --fake` signs out, and `login-finish --fake` / `login-import-cli --fake` sign back in, tracked by a marker file in the fake config dir. An optional `<fake config dir>/fake-status.json` (`{"missing": [...], "venv_ready": false}`, both keys optional) overrides those two fields so a tester can show the missing-tools and setup screens by writing a file; `setup --fake` sets `venv_ready` back to true. Real mode ignores both files.
  Acceptance: tests for each `customer_info` shape (email, name only, given name only, nothing, garbage, unreadable file), with `user_id` never returned; `venv_ready` true and false; fake logout → `authenticated: false` → fake login-finish → `true`; `fake-status.json` overrides and `setup --fake` clearing `venv_ready`; real mode never reads the fake files; the contract test passes with the updated schema; the B8 fake-path test still passes; the name appears in no stderr log line.

- [x] **B10 — Fake mode keeps positions** (tier B; needs B6, B8)
  Fake mode's position store is stateless today: `position-push --fake` is a no-op and `position-get --fake` always returns 0 (finding from P4, #22). Make it hold state in the fake tree: a push writes `{ms, updated_at}` (`updated_at` is the `--at` value, else now) to `<fake data dir>/fake-account-positions.json`, and `position-get --fake` and `sync --fake` read it back, so the stale check and resume-from-the-account can be tested end to end in fake mode. Real mode is unchanged. The file exists only in the fake tree.
  Acceptance: push then get returns the pushed position; a push older than the stored one is refused with `error(code=stale)`; `sync --fake` writes the stored positions into the fake `remote.json`; the B8 test (real tree untouched) still passes; no real-mode code path changes (test with the real port mocked).

- [x] **L1 — `Format.js`** (tier A; needs nothing)
  `qml/lib/Format.js`, pure: `duration(ms)` ("3h 12m", "45m", "<1m", "0m"; bad input gives ""), `left(positionMs, durationMs)` ("3h 12m left", "" at or past the end), `clock(ms)` ("0:00", "2:05", "1:02:33", "123:04:05"), `bytes(n)` (1024-based, "B"/"KB"/"MB"/"GB", one decimal under 10), `storageLine(count, totalBytes)` ("No books on this laptop", "1 book · 12 MB", "3 books · 780 MB"), `ago(iso, nowMs)` ("just now", "5 min ago", "3 h ago", "2 days ago", "never" for null), `names(list)` ("A", "A and B", "A, B and 2 more"), and `tooltip(title, author, leftText)` for FR-U1 ("Title — Author · 3h 12m left", leaving out missing parts).
  Acceptance: QJSEngine tests for 0, under a minute, over 100 hours, negative, NaN, null, missing title or author, and singular versus plural.

- [x] **L2 — Library view logic** (tier B; needs L1, P3a)
  `qml/lib/LibraryUi.js`, pure, working on `Library.js` rows: `badge(row, progress, offline)` returns `{kind, label}` for every §5.3 state (`downloading` shows a percent from the `get` progress event's `bytes`/`total`; `error` is "Failed — Retry"; a cloud book while offline is "Offline"). `primaryAction(row, offline)` returns `play` (local), `download` (cloud and online), `retry` (error) or `none`. `resumeChoice(row, durationMs)` returns `resume`, `ask` (finished but not within 30 s of the end: offer Start over or Resume, SCOPE §6) or `start-over`. `listState({catalogLoaded, syncing, total, shown, offline, errorCode})` returns `{state, banner}`, where the state is `loading`/`error`/`empty`/`no-results`/`list` and the banner is `offline`/`reconnect`/`syncing`/null; `auth_failed` means reconnect (FR-A4). `moveSelection(index, delta, count)` clamps, and returns -1 for an empty list. `syncDue(catalogAgeS, hours)` is true when the age is null or at least `hours` (FR-L2). `storage(localBooks)` returns `{count, bytes}`.
  Acceptance: QJSEngine tests for each function, covering every row state, offline versus online, and the empty and no-results cases, using rows built by `Library.buildRows` from `fixtures/library-sample.json`.

- [x] **L3 — Onboarding logic** (tier B; needs L2, B9)
  `qml/lib/Onboarding.js`, pure: `step(status)` returns `loading` (null), `missing` (`missing` not empty), `setup` (`venv_ready` false), `connect` (not authenticated) or `ready`. `installCommand(missing)` returns `omarchy pkg add mpv ffmpeg`, mapping `ffprobe` to `ffmpeg`, removing duplicates and keeping a stable order. `view(step, playerLoaded, requested)` applies ARCHITECTURE §6: onboarding unless ready; a bar click opens `mini` when a book is loaded and `library` otherwise; `full` only when a book is loaded. `errorText(code, message, hint)` returns `{title, body, reconnect}` for **every** `protocol.ErrorCode` plus `no_venv`, never including the raw pasted URL. `looksLikeRedirect(text)` is true when the text holds `openid.oa2.authorization_code=`, and it never echoes the text. `marketplaces()` returns `[{code, label}]`. `clipboardNotice(done)` returns the clear-clipboard-history text when `done.clipboard_history_contains_code` is true (G1 note) and "" otherwise.
  Acceptance: QJSEngine tests; one test asserts that `marketplaces()` codes equal the backend's `MARKETPLACES` in order, and one that `errorText` covers every `ErrorCode` member.

- [x] **U1 — Bar widget + Panel shell** (tier B; needs S6, P1; laptop)
  Book glyph; play/pause state; optional title; tooltip; left click toggles the drawer (Mini if loaded else Library); middle click toggles play/pause. The widget's `KeyboardPanel` (pattern in `spikes/s6-BarWidget.qml`) hosts a stacked layout with Library/Mini/Full/Onboarding placeholders, closes on Esc/click-away/popout switch, and never affects playback. Widgets are per monitor: keep state in the service. **Removes the temporary debug panel.** The extra IPC methods added for testing (`play`, `pause`, `playerStatus`, `libraryQuery`, and the rest) stay through M3 so agents can test without touching the desktop; R6 either documents or removes them.
  Acceptance: matches the behavior in SCOPE FR-U1/U5 under Chris's current theme; the three-theme check runs at G3.

- [x] **U4 — Cover + StateBadge** (tier A; needs U1, L1; laptop)
  `Cover.qml` (async load, placeholder, fixed aspect, rounded per theme tokens) and `StateBadge.qml` (renders `LibraryUi.badge`). Text formatting comes from `Format.js` (L1).
  Acceptance: documented manual checks for a missing cover, a very long title and each badge kind.

- [x] **U2a — Minimal Mini view** (tier B; needs U1, U4, L1, P2; laptop) — moved into M3 at G0 because the Library view's "reopen on Mini when playback begins" and G3's "use it for a day" both need it.
  Title and author, elapsed/remaining text, ⏯, ⏪15/⏩15, and a library button. No scrub bar, chapter popup, or speed (those stay in U5).
  Acceptance: J3's basic controls work with the fake backend; U5 later extends this file rather than replacing it.

- [x] **U2 — Library view (drawer)** (tier B; needs U1, U4, L2, P3; laptop)
  Search field (autofocus), sort dropdown, filter chips, storage line, `ListView` of `BookRow` (cover, title, author, runtime, progress bar, `StateBadge`). Enter/click plays; cloud books enqueue a download and show progress, then auto-play; row menu has Remove from laptop; "Remove all downloads"; designed empty/loading/offline/error states; placeholder cover. All decisions come from `LibraryUi.js`.
  Acceptance: J2 and J6 pass with the fake backend; keyboard navigation per ARCHITECTURE §6.

- [x] **U3 — Onboarding / Setup / Login view** (tier B; needs U1, L3, B9; laptop)
  Shows missing dependencies with copyable install commands; a "Set up" button that runs `setup` with progress; marketplace picker; "Connect Audible" opens the URL with `xdg-open`, shows a paste field plus "Paste from clipboard", then runs `login-finish` and starts the first `sync`; "Use existing audible-cli login" shortcut when detected; clear error messages for bad URL/expired session; the clear-clipboard-history notice when `login-finish` reports it. Reconnect banner when credentials fail later. Disconnect action, showing the account name and marketplace (FR-A3). All decisions come from `Onboarding.js`.
  Acceptance: every step and error state is checked in fake mode, using B9's fake sign-in states and `fake-status.json`; J1 end-to-end against the real account is run at G3 with Chris; no secret ever appears in the UI.

**GATE G3** — first usable build, with Chris at the laptop in real mode. Checklist:
1. J1: Disconnect, then Connect Audible through the drawer (this deregisters and re-registers the plugin's device; books stay). Then J2, J3 and J6 by hand.
2. The two G2 items not yet run in real mode: a chapter change, and `omarchy-restart-shell` during playback with the audio continuing.
3. J7 spot check: listen on the phone, then resume on the laptop at the phone's position.
4. Three themes (one light, two dark) and a live theme switch with the drawer open; Chris's own theme restored afterward.
5. Chris uses it for a day with real books. Fix blockers before M4. After G3, flip the repo to public if D2 still stands.

---

## M4 — Player UI

- [x] **S7 — Play locked files, keep no decrypted copy** (tier S; desktop HMSP-OMARCHYBEE, moved from the laptop 2026-10-06) — **go**, see SPIKE-RESULTS S7
  Question: can mpv play the file exactly as Audible sent it, unlocking it only in memory, so no DRM-free `.m4b` ever lands on disk? ffmpeg's mov demuxer has `-activation_bytes` (aax) and `-audible_key`/`-audible_iv` (aaxc); mpv uses the same demuxer through `--demuxer-lavf-o`. This matters for the marketplace listing (keeping a "clean copy" is the hardest thing to defend) and drops the ~2× free-space conversion step.
  Method: with real-mode files on the desktop (no shell restart), play one locked aaxc and one locked aax book directly in mpv. Pass the key without putting it in mpv's argv (other users can read `/proc/<pid>/cmdline`): try an owner-only options file, mpv's IPC `set_property`, or an `--include` config. Check seek and skip latency (start, middle, near the end), chapter display from Audible's `chapters.json` (the locked file's embedded chapters can be coarser; feed a chapter file or keep the service's own list), resume at a saved position, and that `acr`/position push still work.
  Done when: findings are in `SPIKE-RESULTS.md` with timings, the key-passing method that works, and a go/no-go. Keys and titles stay out of the repo, logs and argv.
  *If it fails:* keep today's decrypt-to-m4b path and record why.

- [x] **B11 — Drop the decrypted copy** (tier B; S7 = go and D7 = go, both 2026-10-06; design in SPIKE-RESULTS S7 → D7. Split: backend `get`/`remove`/`local` on Hopebox Kanban, `PlayerController` load path on the desktop)
  `get` keeps the original aaxc/aax plus its key material (`0600`) instead of converting; the free-space check falls to ~1×; `PlayerController` passes the key the S7 way; chapters come from `chapters.json`; `remove` deletes the key material too. Existing `.m4b` books keep playing as they are; only new downloads are locked. README and SCOPE §7 say no unlocked copy is stored.
  How it runs (Dante, 2026-10-06): everything lands on a `b11` integration branch, which merges into `main` in one step, because `main`'s QML would not play a new locked download on its own. Backend, `play-info` and the pure-JS helpers go through Hopebox Kanban as a PR into `b11`. The QML wiring and real-mode acceptance follow [briefs/B11-desktop.md](briefs/B11-desktop.md) on the desktop.
  Acceptance: fake and real-mode get → play → seek → chapter → resume → remove on the desktop, including one 100+ chapter book; a PCM-decode test (not just `file-loaded`) proves the unlock; no key in any process's argv (`ps -eo args`), logs or `recentEvents`; contract tests updated; J6 in full in real mode (finish a book → Remove from this device → download it again → it resumes where Audible says, including the finished-book Resume / Start over prompt), carried over from G4.
  *Accepted 2026-10-07 on the desktop* (MANUAL-TEST.md, B11): all §4 checks pass. The 100+ chapter check ran on Carl's 50 chapters through `chapters-file`, because no book in the library has 100+ (finding d, for Dante to rule on).

- [x] **U5 — Mini view, complete** (tier B; needs G3, extends U2a)
  Per SCOPE FR-U3: cover, title/author, current chapter with a tap-to-open chapter popup, scrub bar (drag to seek, elapsed/remaining), ⏮ ⏪N ⏯ ⏩N ⏭, speed pill that cycles presets, maximize, library, dismiss.
  Acceptance: J3, J4 pass; dragging the scrub bar doesn't fight position updates; text elides cleanly for long titles.

- [x] **U6 — Full view** (tier B; needs U5)
  Large cover, chapter list (auto-scroll to current, click to jump), speed presets and fine control, sleep timer picker, details (narrator, runtime, % complete), Remove from this device, collapse.
  Acceptance: J5 passes; 100+ chapter books scroll smoothly.

- [x] **U7 — Now-playing strip in Library view** (tier A; needs U2, P2)
  A compact pinned strip showing title, play/pause, and ⏪/⏩, tapping it opens Mini.
  Acceptance: visible only when a book is loaded; no layout jump when it appears.

- [ ] **U8 — Library button in the Full view** (tier A; Chris, G4) — Full has collapse, ✕ and Backspace but no way to reach the Library directly; add the same library button Mini has (FR-U3), and add it to FR-U4.
  Acceptance: one click from Full opens Library with playback untouched; the now-playing strip still leads back to Mini.

- [ ] **U9 — Pause lag check** (tier B; G4 finding) — audio carries on for about a second after ⏯. The plugin sends one `set pause` over IPC, so first measure the gap (IPC send → `pause` property change → silence) and try mpv's `--audio-buffer` and PipeWire latency. Change something only if the cause is in our hands and the fix doesn't cause dropouts.
  Acceptance: a measured cause is written down; pause is clearly faster, or the reason it can't be is written down.

**GATE G4** — all journeys J1–J7 pass in `docs/MANUAL-TEST.md` under three themes (one light, two dark) plus a live theme switch while the panel is open.
  *Passed 2026-10-06 (Dante's ruling on #56):* the journeys ran under one theme, and each of the three themes was checked across Mini, Full and Library with a real book loaded. That meets the gate: themes only change colours (theme tokens, DoD 4), not journey logic, and every view was seen under each theme, including a live switch with Full open. J6's re-download-and-resume half was not run at G4. The same path (download a cloud book, resume from Audible's position) passed in J2, and B11 rewrites `get`/`remove`, so that check is now part of B11's acceptance.

---

## Review follow-ups (whole-repo review 2026-10-06, [briefs/REVIEW-2026-10-06.md](briefs/REVIEW-2026-10-06.md))

Second review, 2026-10-07 ([briefs/REVIEW-2026-10-07.md](briefs/REVIEW-2026-10-07.md), F34–F37, placed by Dante): F34 and F35 join **B12** (*done in #68*), F36 joins **H1**, and F37 goes in the next desktop brief with U10(c).

Placed by Dante. Order: B14 lands on `b11` before it merges, then the rest in this order, after `b11` is in `main` (B12 and P6 touch the same files as B11). Finding numbers (F1–F33) are the brief's.

- [x] **B14 — Re-download keeps the working copy until the new one is ready** (tier B; Hopebox, **on `b11`**, before `b11` merges; F7, F10). Stage `key.json`, `chapters.txt` and the audio in `.partial/`, verify there, and only then clear the old files and move the new ones in. The free-space check counts the space the old copy will free.
  Acceptance: a failed or cancelled re-download of a local book (every fake-fail mode) leaves the old book playable and unchanged; a successful one leaves only the new layout.
- [x] **P6 — Clock-skew lockout** (tier B; Hopebox JS + backend, then a desktop wiring touch; F1, F3). A remote entry whose `ms` equals this device's last pushed `ms` is our own echo, not newer (the rule `Catchup.js` already uses). `position-push` without `--at` is `invalid_args`. A repeated `stale` shows a line in Mini instead of being dropped silently.
  Acceptance: a test with the device clock behind the server by more than the push interval keeps pushing; vectors shared by Python and JS.
  *Hopebox half done in #65; desktop wiring of `staleNotice` done on `p6-desktop` (2026-10-07).*
- [x] **B15 — Confirm `last_updated` is UTC** (maintainer; F2). Folded into B11's desktop acceptance (one real push read back against the wall clock); record the result in SPIKE-RESULTS S3. *Done 2026-10-07: UTC, offset about +1 s.*
- [x] **B12 — Backend hardening** (tier B; Hopebox; F3 if not in P6, F4, F6, F8, F9, F13, F14, **F34, F35**). Tests first.
- [x] **B13 — Login saves before fetching activation bytes** (tier A; Hopebox; F5). No orphan device registration when the activation-bytes fetch fails.
- [x] **P7 — Finished flag and one merge** (tier B; Hopebox JS; F16, F20). Start over clears `finished`; `Library.js` has one timestamp merge. Vectors.
- [ ] **P8 — Service and player fixes** (tier B; desktop; F17, F18, F19, F21, F22, F23). F17 must land with or before R1. Brief: [briefs/FOLLOWUPS-desktop.md](briefs/FOLLOWUPS-desktop.md), which also carries the P6 desktop wiring, H1's F25–F27, U8 and U9. P9 gets its own brief after it.
- [x] **H1 — Hygiene** (tier A; Hopebox; F24–F27, F30–F33, **F36**). Includes adding `ruff check` to `make lint`, the `dev` extra, and the `conftest.py` ffmpeg path. **Ruff format is policy** (Dante, 2026-10-06); the one mechanical `ruff format` PR is done (#63, 2026-10-07), so H1 adds `ruff format --check` to `make lint`.
  Desktop part: F25–F27 (MiniView popup gating, the shared colour property, dev IPC gating) — each needs a shell to verify, so they are left for the desktop. H1's Hopebox part (F24, F30–F33, F36) lands without them. *F27 done in #78; F25 and F26 done on `h1-views` (2026-10-07).*
- [ ] **P9 — Service split and orchestration reducers** (tier B, incremental; desktop + Hopebox JS; F28, F29). After U8/U9; one child object per PR.
- [x] **U10 — B11 acceptance findings** (tier A/B; Dante placed 2026-10-07 from MANUAL-TEST B11). (a) the debug IPC `libraryQuery` must not change the drawer's live sort, filter or search (it hid all but one book while the search field looked empty); make it read-only or route it through `libraryState`, as R6 already notes. (b) the finished-book Resume / Start over banner is easy to miss, and a row's ▶ only asks again; make the question visible on the row. Start over keeping `finished` is P7 (F16). (c) a `not_local` play error names the ASIN; the service shows the title from the catalog row. With it, F37: Stop clears `playError`. All of U10 and F37 are in the desktop brief [briefs/FOLLOWUPS-desktop.md](briefs/FOLLOWUPS-desktop.md) (Dante, 2026-10-07): (a) and (c) live in `Service.qml`, so they need the shell. *(a) done in #78; (b), (c) and F37 done on `u10-findings` (2026-10-07).*
- [ ] **R2 note (B11 d)** — no book in the library has 100+ chapters; accepted on Carl (50 through `chapters-file`) plus the 120-chapter fake book. If a 100+ chapter book is ever bought, run MANUAL-TEST B11 step 3 on it. BEE has no old-style `.m4b` left, so the `.m4b` path is covered by tests and fake mode only.
- [ ] **R2 note (B13)** — the `play-info` lazy activation-bytes fill for a legacy aax book is covered by stub-port tests only. After B13, with Chris present and an aax book on BEE: delete `activation_bytes` from the plugin config dir, play the book once in real mode, and confirm it plays and the file comes back `0600`. Record it in MANUAL-TEST.
- F15 goes on R2's sweep list.

## M5 — Polish and release

- [ ] **R1 — Settings schema** (tier A) — manifest `schema` for all keys in SCOPE §4.6; each setting is wired and takes effect without restart.
- [ ] **R2 — Error and edge-case sweep** (tier B) — walk SCOPE §6 line by line; add a test or a manual-test entry for each.
- [ ] **R3 — MPRIS (optional)** (tier B) — detect `mpv-mpris`; if installed, pass `--script=`; confirm media keys and the stock media widget. Document the optional package. Never required.
- [ ] **R4 — Idle-cost audit** (tier B) — verify no timers/polling when nothing plays, and measure memory (target < 100 MB excluding mpv). Fix offenders.
- [ ] **R5 — Clean-install test** (tier B) — on a fresh Omarchy install (VM or a spare user account): `omarchy plugin add <repo-url> --enable --yes`, then J1 → J7 using only the UI. Record time to first audio (target ≤ 5 min).
- [ ] **R6 — Docs and release assets** (tier A) — README with screenshots/GIF, install, hotkeys, FAQ ("Does removing a book delete it from Audible?" → no), the legal/ToS statement from SCOPE §7, a **"What setup installs" section** documenting the first-run venv and `pip install` (what is downloaded, from where, where it is written, how to remove it) as the marketplace asks, CHANGELOG, LICENSE (AGPL-3.0-only, added at G0), `docs/RELEASING.md` (including `omarchy plugin validate .`), tag `v0.1.0`. For the test IPC methods R6 keeps or removes: `libraryQuery` sets the drawer's live sort, filter and search (G4 finding), so it must not be documented as a read. Use `libraryState` to read counts, or make `libraryQuery` side-effect-free.
- [ ] **R7 — Marketplace submission** (tier maintainer) — repo must be public with `manifest.json`, README, and license. Read https://plugins.omarchy.org/publish.html first, then submit via its issue form with a category and 1–3 tags. Expect automated validation of the exact commit and a maintainer decision; a maintainer may decline a plugin that decrypts DRM, so be ready to rely on `omarchy plugin add <git-url>` instead.

---

## Definition of done (every PR)

1. Acceptance checklist for the task is satisfied and ticked here.
2. `make test` and `make lint` pass (lint includes `omarchy plugin validate .` and the no-symlink check); new behavior has tests (or a MANUAL-TEST entry for QML).
3. No secrets, real library data, or personal paths in the diff.
4. No hard-coded colors in QML; theme tokens only.
5. No code path that mutates the Audible account other than position write-back.
6. Docs updated if behavior or protocol changed (ARCHITECTURE/protocol schemas first, then code).

## Suggested order for a single agent working alone

A0 → S6 → S5 → S1 → S2 → S4 → S3 → (G0) → B1 → B7 → B5 → B4 → B2 → B3 → B6 → (G1) → P1 → P2 → P3 → P5 → P4 → (G2) → U4 → U1 → U2a → U2 → U3 → (G3) → U5 → U6 → U7 → (G4) → B11 (+B14) → P6 → B12 → B13 → P7 → H1 → U10 → U8 → U9 → P8 → P9 → R1 … R7.

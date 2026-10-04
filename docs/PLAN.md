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
M3  U1 → U2a → U2 → U3 ; U4 after U1                        ──▶ GATE G3  (first usable build)
M4  U5, U6, U7 after G3                                     ──▶ GATE G4
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

- [ ] **B1 — Launcher, protocol helpers, fake mode skeleton** (tier B; needs A0)
  `bin/omarchy-audible` (stdlib only) dispatches subcommands; shared `emit()` NDJSON writer; error codes; secret-scrubbing logger; the **job lock** from ARCHITECTURE §4.8 (non-blocking `flock` on `job.lock` for job commands only, `error(code=busy)` when held; `job.json` helper); `--fake` / `OMARCHY_AUDIBLE_FAKE=1` switch; `status` and `doctor` working (checks for `mpv`, `ffmpeg`, `ffprobe`, `python`, `wl-paste`, `xdg-open`, `systemd-run`, venv, auth).
  Acceptance: `status` and `doctor` output validates against `tests/schemas/*.json`; works with no venv; unknown command exits nonzero with an `error` event; a second job command while one holds the lock gets `busy`; a non-job command (`status`) succeeds while the lock is held.

- [ ] **B2 — Setup/venv bootstrap** (tier B; needs B1)
  `setup` creates the venv, installs the pinned `audible-cli` and `audible[cryptography]` **and this repo's `backend/` package** (so `venv/bin/python -m omarchy_audible` works), streams progress events, is idempotent, and cleans up on failure. Pins live in one place (`backend/requirements.lock`; S1–S4 used audible-cli 0.6.0 / audible 0.12.0).
  Acceptance: from a clean `~/.local/share/omarchy-audible`, `setup` yields a venv where `python -c "import audible, omarchy_audible"` works and the launcher dispatches into it; second run is a no-op; killing it midway then re-running recovers.

- [ ] **B3 — Auth commands** (tier B, S1 result required; needs B2)
  `login-start`, `login-finish`, `login-import-cli`, `logout`, plus `status.authenticated/account/marketplace`. Implements ARCHITECTURE §4.7 exactly; working reference code is `spikes/s1_login.py`. `login-finish` reads the URL from **stdin**. Files created `0600` under umask 077. The clipboard-history check and `logout` deregistering only this device are part of the task.
  Acceptance: unit tests with mocked `audible` calls; file-mode test (including an import from a `0644` source); a test asserting the pasted URL and code never appear in argv, any log line, any event, or any file; expired/bad-URL tests; a test that `deregister_all=True` appears nowhere; manual run against a real account by Dante on the laptop.

- [ ] **B4 — Catalog sync** (tier B, S4 result required; needs B3 or fake mode)
  `sync` pages the library (`num_results=50`, groups per ARCHITECTURE §4.5), builds `catalog.json` per the schema, filters out `Podcast*` types only (**keeps `Lecture`**), downloads missing covers (thumbnail ~252 px), fetches remote positions in batches of ≤ 25 into **`remote.json`** (never `state.json`, which the service owns), and writes everything atomically. Progress events per page. Never pushes a position.
  Acceptance: fake mode yields the fixture catalog; real mode matches `audible library list` count (minus filtered items); interrupted sync leaves the old catalog intact.

- [ ] **B5 — `get` / `cancel` / `local` / `remove`** (tier B, S2 result required; needs B1)
  Implements the §4.3 pipeline (aaxc first, aax fallback; chapters rebuilt from `chapters.json`; 2.1× free-space pre-flight; `acr` cached in `meta.json`), §4.4 safety, and `cancel` per §4.8. Fake mode generates a 3-chapter sine m4b plus a fake `chapters.json` with a different chapter count, and simulates progress and failures (`--fake-fail disk|network|decrypt|novoucher`).
  Acceptance (all as pytest): atomic rename; `.partial` and raw file removed on success **and** on each failure mode; `cancel <asin>` mid-download (from a second process) cleans up and the job emits `error(code=cancelled)`; `novoucher` falls back to aax; output chapter count equals the `chapters.json` flat list; free-space pre-flight; `remove` refuses a path outside `booksDir` and symlinks; `remove` never invokes any network call (assert by running with network access blocked); the "no mutating API calls" grep test from ARCHITECTURE §4.4 (only `PUT 1.0/lastpositions/` allowed). Real-account check of one aaxc and one aax book by Dante on the laptop.

- [ ] **B6 — Positions** (tier B, S3 result required; needs B1)
  `position-get` (writes `remote.json`) and `position-push <asin> <ms>`. A pure newest-wins `merge()` helper that the service's QML port must match. `position-push` re-reads the remote position first and refuses with `error(code=stale)` when remote is newer than the pushed local timestamp (ARCHITECTURE §4.6 push rules).
  Acceptance: unit tests for merge edge cases (equal timestamps, missing remote, remote newer); the stale-refusal test; `lastpositions` batching ≤ 25; `acr` read from `meta.json`, else fetched from content metadata; a test that `sync` never calls `position-push`. Real-account round trip with restore by Dante on the laptop.

- [ ] **B7 — Protocol schemas and contract tests** (tier A; needs B1; extended as commands land)
  JSON Schema file per event type; a test that runs every command in fake mode and validates every emitted line.
  Acceptance: CI-style `make test` fails if a command emits an unknown or malformed event.

**GATE G1** — a README section "Backend CLI" documents every command with an example. The maintainer runs `sync` and `get` against the real account, and `remove` leaves the Audible account unchanged.

---

## M2 — Player service (QML)

Depends on S5/S6 results and the fake backend.

- [ ] **P1 — Service skeleton and JobRunner** (tier B; needs A0, B1)
  `Service.qml` as `keepLoaded` singleton. `JobRunner.qml` spawns backend commands, parses NDJSON from stdout, exposes `running`, `progress`, `lastError`, and emits per-event signals. Handles process exit and non-JSON lines defensively.
  Acceptance: a debug panel (temporary) runs `status` and `sync` in fake mode and shows events.

- [ ] **P2 — PlayerController (mpv)** (tier S/B; needs S5, P1)
  Implements ARCHITECTURE §5.1–5.2 including reattach after shell restart, `observe_property` handling, resume via `start=`, chapter list parsing, and the skip/chapter/speed commands. Includes the sleep timer with a 5 s fade.
  Acceptance: with a fake m4b — play, pause, ±skip, chapter jump, speed change, sleep timer; `omarchy-restart-shell` mid-playback and audio continues and state reattaches; mpv crashing is detected and surfaced.

- [ ] **P3 — LibraryModel and persistence** (tier B; needs P1, B4/B5 in fake mode)
  Merges `catalog.json`, `remote.json`, `state.json`, and the local-books scan into one list model with the book state machine (§5.3), sort (recent/added/title/author), filter (all/local/in-progress), and search. The service is the **only** writer of `state.json` (§4.8), with atomic writes; saves position every 10 s while playing and on pause/switch/quit.
  Acceptance: sort/filter/search verified against the fixture catalog; kill -9 the shell mid-playback and the position loss is ≤ 10 s.

- [ ] **P4 — Remote position sync + finished handling** (tier B; needs P2, B6)
  Push every ~60 s and on pause/stop/switch/quit, following the push rules in ARCHITECTURE §4.6 (local listening only; never stale); failures queued and retried; resume from newest of local/remote; finished detection and optional auto-remove (setting, default Off).
  Acceptance: simulated remote-newer position wins on play; a book that was never played locally is never pushed; offline pushes are queued and flushed later; a queued push that has become stale is dropped; auto-remove only fires when the setting is on and never during playback.

- [ ] **P5 — Shell IPC target** (tier A; needs P2, S6)
  Registers `latentoperator.audible` (in `Service.qml`) with `toggle`, `playPause`, `skip`, `nextChapter`, `prevChapter`, `openLibrary`.
  Acceptance: each method works from a terminal using the call syntax documented in S6; documented in README with a sample Hyprland bind.

**GATE G2** — you can start, pause, skip, change chapter, and restart the shell without losing playback, driven only by IPC calls and a debug panel. No real UI yet.

---

## M3 — First usable UI

- [ ] **U1 — Bar widget + Panel shell** (tier B; needs S6, P1)
  Book glyph; play/pause state; optional title; tooltip; left click toggles the drawer (Mini if loaded else Library); middle click toggles play/pause. The widget's `KeyboardPanel` (pattern in `spikes/s6-BarWidget.qml`) hosts a stacked layout with Library/Mini/Full/Onboarding placeholders, closes on Esc/click-away/popout switch, and never affects playback. Widgets are per monitor: keep state in the service.
  Acceptance: matches the behavior in SCOPE FR-U1/U5; works under three themes.

- [ ] **U2a — Minimal Mini view** (tier B; needs U1, P2) — moved into M3 at G0 because the Library view's "reopen on Mini when playback begins" and G3's "use it for a day" both need it.
  Title and author, elapsed/remaining text, ⏯, ⏪15/⏩15, and a library button. No scrub bar, chapter popup, or speed (those stay in U5).
  Acceptance: J3's basic controls work with the fake backend; U5 later extends this file rather than replacing it.

- [ ] **U2 — Library view (drawer)** (tier B; needs U1, P3)
  Search field (autofocus), sort dropdown, filter chips, storage line, virtual-free `ListView` of `BookRow` (cover, title, author, runtime, progress bar, `StateBadge`). Enter/click plays; cloud books enqueue a download and show progress, then auto-play; row menu has Remove from laptop; "Remove all downloads"; designed empty/loading/offline/error states; placeholder cover.
  Acceptance: J2 and J6 pass with the fake backend; keyboard navigation per ARCHITECTURE §6.

- [ ] **U3 — Onboarding / Setup / Login view** (tier B; needs U1, B2, B3)
  Shows missing dependencies with copyable install commands; a "Set up" button that runs `setup` with progress; marketplace picker; "Connect Audible" opens the URL with `xdg-open`, shows a paste field plus "Paste from clipboard", then runs `login-finish` and starts the first `sync`; "Use existing audible-cli login" shortcut when detected; clear error messages for bad URL/expired session. Reconnect banner when credentials fail later. Disconnect action.
  Acceptance: J1 passes end-to-end against a real account on a machine with no prior plugin state; no secret ever appears in the UI.

- [ ] **U4 — Cover + Format utilities** (tier A; needs A0, runs parallel with U1)
  `Cover.qml` (async load, placeholder, fixed aspect, rounded per theme tokens), `Format.js` (durations like "3h 12m left", timestamps `1:02:33`), `StateBadge.qml`.
  Acceptance: small QML test harness or documented manual checks for edge values (0, <1 min, >100 h, missing cover).

**GATE G3** — first usable build. The maintainer uses it for a day with real books. Fix blockers before M4. After G3, flip the repo to public if D2 still stands.

---

## M4 — Player UI

- [ ] **U5 — Mini view, complete** (tier B; needs G3, extends U2a)
  Per SCOPE FR-U3: cover, title/author, current chapter with a tap-to-open chapter popup, scrub bar (drag to seek, elapsed/remaining), ⏮ ⏪N ⏯ ⏩N ⏭, speed pill that cycles presets, maximize, library, dismiss.
  Acceptance: J3, J4 pass; dragging the scrub bar doesn't fight position updates; text elides cleanly for long titles.

- [ ] **U6 — Full view** (tier B; needs U5)
  Large cover, chapter list (auto-scroll to current, click to jump), speed presets and fine control, sleep timer picker, details (narrator, runtime, % complete), Remove from laptop, collapse.
  Acceptance: J5 passes; 100+ chapter books scroll smoothly.

- [ ] **U7 — Now-playing strip in Library view** (tier A; needs U2, P2)
  A compact pinned strip showing title, play/pause, and ⏪/⏩, tapping it opens Mini.
  Acceptance: visible only when a book is loaded; no layout jump when it appears.

**GATE G4** — all journeys J1–J7 pass in `docs/MANUAL-TEST.md` under three themes (one light, two dark) plus a live theme switch while the panel is open.

---

## M5 — Polish and release

- [ ] **R1 — Settings schema** (tier A) — manifest `schema` for all keys in SCOPE §4.6; each setting is wired and takes effect without restart.
- [ ] **R2 — Error and edge-case sweep** (tier B) — walk SCOPE §6 line by line; add a test or a manual-test entry for each.
- [ ] **R3 — MPRIS (optional)** (tier B) — detect `mpv-mpris`; if installed, pass `--script=`; confirm media keys and the stock media widget. Document the optional package. Never required.
- [ ] **R4 — Idle-cost audit** (tier B) — verify no timers/polling when nothing plays, and measure memory (target < 100 MB excluding mpv). Fix offenders.
- [ ] **R5 — Clean-install test** (tier B) — on a fresh Omarchy install (VM or a spare user account): `omarchy plugin add <repo-url> --enable --yes`, then J1 → J7 using only the UI. Record time to first audio (target ≤ 5 min).
- [ ] **R6 — Docs and release assets** (tier A) — README with screenshots/GIF, install, hotkeys, FAQ ("Does removing a book delete it from Audible?" → no), the legal/ToS statement from SCOPE §7, a **"What setup installs" section** documenting the first-run venv and `pip install` (what is downloaded, from where, where it is written, how to remove it) as the marketplace asks, CHANGELOG, LICENSE (AGPL-3.0-only, added at G0), `docs/RELEASING.md` (including `omarchy plugin validate .`), tag `v0.1.0`.
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

A0 → S6 → S5 → S1 → S2 → S4 → S3 → (G0) → B1 → B7 → B5 → B4 → B2 → B3 → B6 → (G1) → P1 → P2 → P3 → P5 → P4 → (G2) → U4 → U1 → U2a → U2 → U3 → (G3) → U5 → U6 → U7 → (G4) → R1 … R7.

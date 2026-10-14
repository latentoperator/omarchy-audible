# Omaudible v0.1.5 — code and UI/UX remediation brief

**For:** the next implementation agent and its independent reviewer.

**Reviewed:** `d82b252c75ea4e069a79bf8e54f5dd52073e62af` (`main`, v0.1.5, merged PR #121).

**Review date:** 2026-10-14. **Status:** findings and proposed work, not implemented fixes.

## Executive decision

Prioritize data preservation and credential ownership before further feature work. Two injected failure paths reproduce loss of synthetic existing audio and an attempted imported-device deregistration recorded by a stub. Address orphan-book deletion protection alongside them. Then fix async intent ownership and throttled-queue lifecycle, followed by repair/setup and UI accessibility/feedback.

The ordinary suite is green; that does not cover these failure windows. Preserve the existing design: native themed drawer, local-only removal, locked originals, separate mpv lifetime, bounded clipboard reads, and Python-only network access. This is not a redesign brief or permission to operate a real Audible account.

## Evidence, scope, and limits

Review covered Python backend/launcher; service, player, queue and position flows; Library, Onboarding, Mini and Full views; supporting JS/tests; and release/docs consistency. Three independent review passes were consolidated and the backend/service probes were independently rerun by the supervising agent.

Fresh local verification at the reviewed commit:

- `QT_QPA_PLATFORM=offscreen uv run --frozen --extra dev python -m pytest -q -rs`: **2,880 passed in 75.99s**, no skips reported.
- `uv run --frozen --extra dev ruff check .`: passed. `ruff format --check .`: **117 files already formatted** before adding this brief's evidence scripts.
- `omarchy plugin validate <clean-source-export>`: passed, exit 0. Validation of the development clone initially rejected `.venv/bin/python` as a symlink; validation was repeated on a `git archive` export without development dependencies. This is not a product defect.
- Focused UI/JS/offscreen component suite rerun: **917 passed in 0.99s** (command below). Do not add this subset to the full-suite count.
- Backend fault-injection probes and source-extracted service/JS probes reproduce the observations below. See checked-in scripts and captured outputs in [review-v015-evidence/](review-v015-evidence/).
- Post-merge GitHub CI run [38564873983](https://github.com/latentoperator/omarchy-audible/actions/runs/38564873983) passed Python 3.11–3.14 and lint.

**Evidence labels:** **Executed** means synthetic offline backend execution, QJSEngine logic, or an isolated Qt component harness—not live-shell end-to-end behavior. **Static** means traced source wiring. **Historical visual** means repository screenshots, not fresh runtime captures.

No live plugin, shell configuration, account, real credentials, or real books were touched. No real license request, deregistration, or position push was made. Full-panel runtime rendering, current-theme contrast, assistive technology, actual Python OS upgrades, and actual Audible throttling remain unverified. The existing BEE fake-mode check in `docs/MANUAL-TEST.md` is prior evidence, not a new test from this review.

Line references below refer to the reviewed commit, not future edited files.

## Implementation queue

One bounded task/branch/PR per row; coordinate shared service edits rather than landing overlapping branches blindly.

| ID | Priority | Work | Evidence |
|---|---|---|---|
| B01 | P1 | Preserve existing audio across backup/rollback failures | Executed fault injection |
| B02 | P1 | Make credential provenance crash-consistent | Executed with stub account API |
| U01 | P1 | Protect potentially irreplaceable orphan downloads | Static + executed removal predicate |
| B03 | P2 | Validate default/fallback books roots, including fake mode | Executed synthetic symlink cases |
| B04 | P2 | Detect and repair broken/stale setup environments | Executed offline venv |
| B05 | P2 | Validate catalog ASINs before cover writes | Executed synthetic upstream response |
| S01 | P2 | Stop held downloads from resuming on Disconnect | Executed source-extracted callbacks |
| S02 | P2 | Bind resume responses to the latest play intent | Executed source-extracted callbacks |
| S03 | P2 | Settle an expired pause with no held books | Executed JS/timer boundary |
| S04 | P2 | Preserve cancellation intent across throttled completion | Executed JS/job boundary |
| U02 | P2 | Clear destructive confirmations when dismissed | Static lifecycle trace |
| U03 | P2 | Keep position-sync warnings visible in Full | Static view mismatch |
| U04 | P2 | Preserve pasted input and explain bounded-paste failures | Static + offscreen component tests |
| U05 | P2 | Make throttling copy match the deadline and retry behavior | Executed JS copy |
| R01 | P3 | Parse multiline denial records safely | Executed synthetic logging record |
| D01 | P3 | Reconcile current-state and behavioral documentation | Static docs/code comparison |

P1 means prioritize before further release/feature work, not that the fault happens on every normal operation. P2 means a concrete defect with a narrower trigger or lower impact. R01 is a synthetic robustness edge, not an observed live Audible response.

## Backend tasks

### B01 — Failed backup during re-download deletes the old audio

**Files:** `backend/omarchy_audible/download.py:297–302,1043–1044,1057–1070`.

`_clear_local(target_dir, aside)` moves old files before entering the rollback-protected inner `try`. If a later backup rename fails, its partial journal never reaches the caller. The outer `finally` deletes `.partial`, including the old audio already moved there.

**Reproduction:** seed a synthetic existing `book.aaxc` and key; inject EIO on backing up `key.json` after audio has moved. Output: `old_book_local_before=true`, `old_audio_exists_after=false`, `local_after=false`, `recovery_partial_exists=false`.

**Implement:** include backup moves in the transaction and keep a caller-visible journal. Restore incomplete backups. Never delete the only recovery copy after rollback failure. Do not weaken private staging permissions or the successful-commit cancellation rule.

**Acceptance:** fail every old-file backup and every new-file install, for legacy and locked layouts. With successful rollback, old files remain byte-identical and playable, preserving metadata/modes. With failed rollback, recovery data remains available and a clear error is returned. A subsequent `get` must recover or refuse safely without deleting the sole old copy: `_make_partial()` currently removes existing staging data, so retaining it only until retry is not sufficient. Add termination coverage if claiming crash-safe recovery. Existing tests only covering failure while installing new audio are insufficient.

### B02 — Failed import can deregister the external audible-cli device

**Files:** `backend/omarchy_audible/auth.py:378–390,714–719`.

Import overwrites `auth.json` before updating `account.json.origin`. Starting from a plugin-created login, failure or termination after the credential replacement leaves imported credentials paired with `origin="login"`. Logout then deregisters that imported device.

**Reproduction:** injected ENOSPC when writing imported account metadata; a stub API recorded `deregister_device(deregister_all=False)` for `imported-synthetic-device`. No real device was contacted.

**Implement:** replace credentials and ownership metadata as one crash-consistent generation, or durably invalidate ownership before replacing credentials and verify matching device identity before deregistration. Unknown/mismatched provenance must not authorize deregistration. Retain a complete old credential set on failed replacement where possible.

**Acceptance:** inject failure/termination after each write for browser-login → import and import → browser-login. Subsequent logout must never deregister an externally owned device. Cover ordinary imports, repeated imports and concurrent readers. Preserve private file modes and secret-free errors.

### B03 — Unsafe defaults bypass books-root checks

**Files:** `backend/omarchy_audible/paths.py:177–183,216–223`; downstream `library.py:253–289`.

Fake mode returns its default books root without resolved containment validation. Real mode can identify an unsafe default and then select that same rejected path as its fallback.

**Reproductions:** a fake default `books` symlink to a synthetic real-tree directory allowed fake `remove` to delete its sentinel. A real default symlink into synthetic plugin data was reported unsafe, yet removal of the `venv` entry deleted the synthetic environment. These require pre-existing unsafe symlinks; ordinary defaults were not shown unsafe.

**Implement:** validate every effective root, including defaults/fallbacks; fail closed for book I/O when no safe root exists. Preserve supported symlinks to safe real books folders. Do not merely show a warning while using a rejected root.

**Acceptance:** default/override symlink escapes, invalid override plus unsafe default, roots pointing into config/runtime/venv, fake-mode containment and supported safe real-folder symlinks. Outside sentinels must remain unchanged across `get`, `local`, `play-info`, `remove`, and old-folder scanning. Keep tests wholly inside synthetic HOME/XDG trees.

### B04 — Setup cannot repair a broken marked environment

**Files:** `backend/omarchy_audible/bootstrap.py:98–108,220–222`; `commands.py:196–198,245–250`; `bin/omarchy-audible:92–94`.

Readiness relies on marker/interpreter presence rather than usable dependencies/interpreter compatibility. Status also ignores the expected requirements digest. An environment with a marker but a failing `import audible` reports `venv_ready=true`; explicit setup emits `up_to_date` and performs no subprocess work. A mismatched digest also remains status-ready.

**Implement:** distinguish current-ready, usable-old-fallback, and broken. Record/check interpreter compatibility and pins; use a bounded offline health probe before setup's no-op, with an explicit repair path. Avoid expensive subprocess probes on every frequent status poll. Source upgrades themselves already run current backend source through the launcher's `PYTHONPATH`; do not misdiagnose that as stale installed code.

**Acceptance:** missing dependency, changed Python ABI, broken/non-executable interpreter and changed pins. Setup must repair or clearly report inability; it must not silently no-op. Failed offline rebuilding must retain a genuinely usable old environment. The review simulated mismatch with an offline venv, not a real OS upgrade.

### B05 — Remote ASIN is used as an unchecked cover path

**Files:** `backend/omarchy_audible/catalog.py:156–172,360–371`.

Catalog ingestion accepts any nonempty ASIN string; cover writes concatenate it into a filename. Full sync with synthetic `../../outside/sentinel` overwrote a sentinel outside plugin data through the injected library/fetch interfaces.

**Impact boundary:** requires malformed or controlled upstream data; the target name is constrained by appended `.jpg`. This is not demonstrated remote code execution or arbitrary-extension overwrite.

**Implement:** full-match ASIN validation before filesystem/network use and independent cover-destination containment checks. Reject symlink escapes as well as lexical traversal. Reuse a documented validator compatible with existing legitimate/fake IDs.

**Acceptance:** traversal, absolute paths, separators, trailing newline and non-string identifiers cause no outside writes/parent creation and no cover fetch. Valid entries, including full sync, still work.

### R01 — Multiline denial messages defeat throttling recognition

**Files:** `backend/omarchy_audible/audible_download.py:44–47,101–110`.

A synthetic logger record carrying `CustomerThrottled` and a newline in the human message yields `denied=false, throttled=false, reasons=[]`; regex matching does not span the newline. No live multiline denial was observed.

**Implement/accept:** parse known structured logger arguments or use multiline-safe parsing. Test newline/whitespace variants while continuing to suppress message text, titles, ASINs and keys from diagnostics. Keep ordinary throttling/no-AAX-retry tests intact.

## Service and asynchronous state tasks

### S01 — Disconnect releases held downloads

**Files:** `Service.qml:530–534,1000–1003`; `qml/SigninFlow.qml:162–167`; `qml/lib/Held.js:221–224`.

Logout clears the backend pause; the resulting signed-out status has `downloads_paused_until:null`. Service interprets that as cooldown completion and submits held downloads. Executed callbacks yielded `status`, `get B0FAKE0002`, `get B0FAKE0003`, despite `authenticated:false`.

**Implement:** distinguish explicit logout from cooldown expiry. Recommended policy: Disconnect drops waiting download intents without running them. If preserving them instead, require an explicit product decision and authenticated readiness before release. Guard stale/in-flight status replies with lifecycle identity.

**Acceptance:** logout with multiple held/queued books, delayed status responses, then reconnect. No held `get` is launched by Disconnect or a stale pre-logout response. This finding does not claim signed-out downloads can successfully obtain a license.

### S02 — Old resume response wins after Stop → replay

**Files:** `Service.qml:292–307,377–382,1016–1020,1045–1049`.

Resume `position-get` requests are keyed only by ASIN, unlike serialized play-info requests. Stop clears the pending ASIN but leaves the older read running. Replaying the same book lets the old read match the new intent. Probe A₁ → Stop → A₂, with replies 100 seconds then 200 seconds, invoked the `playNow` stub once with a **100-second** start and ignored the newer reply. It did not run play-info or mpv.

**Implement:** carry a unique resume/play-intent identity through request, result storage and completion. Invalidate it on Stop, removal and superseding play. A stale completion must neither start playback nor consume a newer result.

**Acceptance:** both completion orders for A→Stop→A and A→B→A, old failure after new success, and removal during resume. Only the latest valid intent starts playback, from its own response or defined local fallback.

### S03 — Empty held list retains expired pause and spins status calls

**Files:** `qml/lib/Held.js:95–102,143–156`; `Service.qml:121,538–543,627–629`.

`_p.settled()` returns early for an empty list, retaining the expired timestamp. The elapsed handler reschedules it for one second and runs another bypass `status`. If status fails/hangs without returning a record, this repeats. An empty list is normal after restart or cancelling the last waiting book; banner state can also remain paused against the stale status clock.

**Reproduction:** three elapsed events after an empty-list deadline produced three status submissions, `nextWakeMs=1000`, `timerRunning=true`, `bannerPaused=true`.

**Implement/accept:** clear expired local pause state even without held books; bound/deduplicate refreshes and use deliberate failure backoff. Test empty-list startup, cancel-last-book, failed/delayed refresh and clock/deadline changes. No indefinite one-second subprocess stream or stale pause banner.

### S04 — Cancelled download is re-held after throttled completion

**Files:** `Service.qml:568–578,635–647`; `qml/BackendCall.qml:85–95`.

Running cancellation sends a backend cancel but retains no cancellation intent. If throttling has already completed and the UI is in the 60 ms exit-drain window, cancel can return `not_running`; the throttled completion still adds the book to Held. The deterministic job-boundary probe returned `send_cancel` then a held ASIN eligible for future automatic download.

**Implement/accept:** preserve per-request cancellation intent through terminal handling. Test cancel before denial, during exit drain, and after held display; cancelled unsuccessful work must never reappear at expiry. Do not suppress the documented success result when cancellation arrives after a completed atomic install.

## UI/UX tasks

### U01 — Orphan removal needs a distinct destructive warning

**Files:** `qml/components/BookRow.qml:86–99,242–247`; `qml/views/LibraryView.qml:357–367`; `qml/lib/Drawer.js:157–167`; `Service.qml:717–726`; `qml/views/FullView.qml:354`.

A local book marked **No longer in your Audible library** exposes the ordinary one-click trash action. Bulk removal excludes these orphaned books, but the individual predicate permits removal. Its only playable copy may be unrecoverable. Full already asks for confirmation but incorrectly promises “It stays in your library.”

**Evidence:** traced dispatch and evaluated removal predicates, not a real deletion or fresh panel click. Historical `docs/screenshots/library.png` illustrates adjacent play/trash controls but does not show an orphan. This is a data-protection UX recommendation grounded in existing behavior, not a claim that one-click ordinary-cache removal violates scope.

**Implement/accept:** title-specific orphan warning explaining that re-download may be unavailable; no remove until explicit confirmation. Cancel/Esc preserves the local copy. Cover Library and Full, maintain ordinary-cache behavior as agreed, and keep bulk exclusion. Under this proposed protection policy, enabling auto-remove must not delete orphan audio unless this book's destructive removal has been explicitly confirmed; a view-only confirmation must not leave an automatic-removal bypass (`qml/Removals.qml:84–92`).

### U02 — Destructive Library confirmations outlive dismissal

**Files:** `qml/views/LibraryView.qml:35–37,89–95,388–459`; persistent views in `BarWidget.qml:157–185`.

Remove-all/Disconnect flags only reset on their buttons. Esc/click-away or a view change can leave the second-step confirmation armed on reopening. Static lifecycle finding; no live click reproduction claimed.

**Implement/accept:** cancel on panel closure or departure from Library, and let Esc dismiss the active question first. Reset if the bulk-eligible set changes. Exercise ask→Esc, click-away, Mini switch, and reopen; each must require fresh confirmation and cause no removal/logout. Use explicit panel lifecycle signals.

### U03 — Full hides an unresolved position-sync warning

**Files:** `qml/views/MiniView.qml:194–203`; missing counterpart in `qml/views/FullView.qml:138–203`; `qml/lib/Sync.js:102–110`.

Mini displays `staleNotice` (“Your position isn't reaching Audible. Check this computer's clock.”); Full omits it while the condition persists.

**Implement/accept:** share persistent player notices across Mini/Full without interrupting playback. Inject stale-push state, switch views and verify warning remains; successful push clears it everywhere. Do not relabel generic offline failures as clock skew. Consider a Library now-playing warning as a follow-up, not a prerequisite redesign.

### U04 — Paste failures silently erase/ignore user input

**Files:** `qml/components/BoundedTextField.qml:68–74,95–112`; `qml/views/OnboardingView.qml:223–228`; `tests/test_bounded_text_field.py:182–202`.

The helper's timeout/nonzero exit/malformed result and over-limit edits have no useful feedback. The onboarding paste button clears existing text before success. Oversized insertion rejection is exercised by the offscreen harness; clearing-before-result and missing error UI are source-traced.

**Implement/accept:** replace text only after valid bounded paste succeeds; show concise secret-free timeout/size/unavailable-clipboard guidance. Cover no owner, oversized payload, malformed output, timeout and successful replacement. Preserve all byte/time limits and responsiveness; never log/display the pasted URL in errors.

### U05 — Retry copy contradicts its own deadline

**Files:** `qml/lib/Onboarding.js:34`; `qml/lib/Drawer.js:266–277`; `backend/omarchy_audible/pause.py:30–33`; automatic release at `Service.qml:528–543`.

A same-day pause produces “Try again tomorrow. Downloads resume at 2:00 PM.” The instruction also obscures automatic retry. Use **downloaded books** rather than implying every cloud book still plays.

**Implement/accept:** one deadline-derived message, e.g. “Audible is limiting downloads. Downloaded books still play. Waiting downloads will retry automatically at …”. These are retry estimates, not a promise Audible will accept the next request. Test same-day, next-day, midnight and unavailable deadlines; keep Python/JS contracts in sync. Do not promise queue survival across shell restart unless implemented separately.

## Existing issues — extend, do not duplicate

- **[#114](https://github.com/latentoperator/omarchy-audible/issues/114), keyboard access:** retain high priority. Source still lacks the necessary control focus/navigation wiring; installed shell button defaults are not focusable. Acceptance must cover all four views, onboarding, sort/filter/refresh, row cancel/remove, confirmations, chapters, speed/sleep, scrub controls and view navigation. Test Tab/Shift-Tab, Enter/Space, visible focus, Esc and focus return in the actual supported shell. Historical screenshots cannot validate this.
- **[#115](https://github.com/latentoperator/omarchy-audible/issues/115), contrast:** important instructions still use muted text, and historical sign-in imagery is visibly faint. **2.46:1 is the existing issue's measurement, not a current measurement from this review.** Measure one light and two dark themes and a live switch; target 4.5:1 for normal-sized instructional text while using theme tokens. Include timing/status text.
- **[#116](https://github.com/latentoperator/omarchy-audible/issues/116), old-shell callback errors:** no new reproduction here. Retain its original observation/closure criteria; do not claim fixed from this review or add a speculative workaround without reproducing it.

## Design follow-ups, not confirmed runtime defects

- Stress constrained logical height, larger fonts/scales, stacked banners and an active sleep countdown. `BarWidget.qml:136–163` caps the panel, Library uses a fixed list region, and Full has dense non-wrapping controls. **Clipping remains a risk to test, not a reproduced finding.** Require essential actions to remain visible or scroll-reachable.
- Historical Library screenshot elides the selected sort label; disclose full sort/title text via layout or accessible hover/focus details. Test long invented titles/authors.
- Mini indicates sleep with a moon; consider remaining-time/Cancel discoverability without adding clutter.
- Refresh synthetic screenshots after UX work, including waiting/error/confirmation states. Historical sign-in imagery lacks current “page not found” guidance.
- Held-list loss on restart is an explicit architectural choice. Persisting it is a product decision, not an undisclosed bug. If retained, document the distinction: cooldown persists; queued intentions do not.

## D01 — Restore reliable handoff documentation

`docs/STATE.md` still leads with releasing 0.1.0 although v0.1.5 is released. SCOPE still describes conversion/m4b chapters in active requirements despite the later locked-original decision. README's setup discussion says a failed run removes the environment, whereas bootstrap preserves a prior working environment. README/architecture statements that position-push is the only account mutation need to explicitly distinguish login device registration/logout deregistration from library mutations.

**Acceptance:** reconcile STATE's current headline/next steps, SCOPE's current requirements, setup failure semantics, mutation language and this brief's eventual disposition. Retain old decisions/test logs as history rather than rewriting them as current observations. Do not mark any implementation complete merely because this brief is merged.

## Execution instructions for the next agent

1. Read `AGENTS.md`, `docs/WORKFLOW.md`, SCOPE and relevant ARCHITECTURE sections. Rebase understanding onto then-current main and verify each finding still applies.
2. Begin with B01/B02/U01 and existing #114; B03/B05 can proceed in separate backend branches. Coordinate S01/S03/S04 together conceptually but retain small reviewable PRs. S02 has separate intent-identity tests. Then B04 and UI feedback/contrast work.
3. Turn each observation into a **failing regression test asserting the desired behavior**, then implement the smallest fix. Evidence scripts below intentionally describe the buggy baseline; a service probe assertion failing after a fix is expected, not a reason to reintroduce the defect. They are diagnostic artifacts, not permanent acceptance tests.
4. Update protocol schemas/ARCHITECTURE first if interfaces change. Follow the repository's one-task/branch/PR discipline, independently review the exact head, and update PLAN/STATE in implementation PRs.
5. Keep HOME/XDG and TMPDIR isolated for destructive/failure tests. Do not access real credentials or perform account calls. No changes to a live installed plugin or shell without explicit owner coordination. This workstation's Hopebox access remains read-only.
6. Before merge, run full pytest with QJS enabled, lint/format, tracked symlink checks and clean-source plugin validation. For UI changes, arrange owner-supervised fake-mode live-shell checks: keyboard, multiple monitors, supported viewport/scales, one light/two dark themes, restart and teardown. Capture synthetic evidence and restore the prior desktop state. Real-account checks require separate authorization.
7. Report exact commands/results, fixed IDs, residuals and unverified cases. Passing unit tests alone is not proof of live UI accessibility or API behavior.

### Reproduce safely from a disposable clone

Set `TMPDIR` to an existing disposable scratch directory before running. Neither script reads the actual account. Backend probes create/remove only synthetic trees there and execute local Python subprocesses for temporary-venv creation/import checking; service probes read repository source, mock process/timer boundaries and execute actual source functions/JS. The scripts make no network requests at this reviewed revision; the preceding `uv sync` may download development dependencies. Isolation is constructed by the fixtures/stubs, not an OS sandbox: inspect changes before rerunning against another revision.

```sh
uv sync --frozen --extra dev
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python docs/briefs/review-v015-evidence/backend_repros.py
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen \
  .venv/bin/python docs/briefs/review-v015-evidence/service_repros.py

PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_bounded_text_field.py tests/test_library_ui.py tests/test_drawer_js.py \
  tests/test_panel.py tests/test_onboarding.py tests/test_signin_js.py \
  tests/test_throttle_js.py tests/test_player_js.py tests/test_mini_js.py tests/test_row_actions.py
```

Captured supervisor outputs: [backend-output.txt](review-v015-evidence/backend-output.txt), [service-output.txt](review-v015-evidence/service-output.txt). Synthetic labels and values are invented, not customer data. The scripts locate this repository relative to their own path; run them at the reviewed source revision for baseline reproduction.

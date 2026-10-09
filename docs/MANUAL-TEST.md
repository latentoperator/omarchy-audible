# Manual test record

Hand-run journeys from `docs/SCOPE.md` §3, one line per run. Chris does all the clicking; the driving CLI checks state over IPC and writes the line. Real mode unless a line says otherwise.

## R2 — Error and edge-case sweep

Regression proof against the starting `main`: `tests/test_drawer_js.py::test_offline_banner_includes_known_catalog_age` failed all four known-age cases (unknown age passed); both local-orphan vectors failed with `KeyError` because `buildRows` discarded local ASINs outside `catalog.json`.

| SCOPE §6 / note | Result and evidence |
|---|---|
| Offline | **Fixed here.** `tests/test_drawer_js.py::test_offline_banner_includes_known_catalog_age` checks unknown age has no suffix and known ages render just now/minutes/hours/days. Fake sync failure `network` showed “Offline — showing your saved library · Last synced just now”; screenshot `~/.cache/dante-oa/r2-shots/offline-age.png`. |
| Credentials expired or revoked (F15) | **Covered; v1 limitation recorded.** `tests/test_signin_flow.py::test_the_runner_hands_every_record_and_finish_to_the_flow` checks job results reach `SigninFlow`; `tests/test_library_ui.py::test_list_state_auth_failed_is_reconnect` checks Reconnect with and without a cached catalog. Fake `authfail` showed Reconnect while a local book played (loaded and playing at 1,262 ms), then it was paused and quit. `status.authenticated` still means `auth.json` exists; expiry is recognized only when a job returns `auth_failed`, so this remains the accepted F15 gap. |
| Download fails or is cancelled | **Covered and manually checked.** `tests/test_get.py::test_get_failure_removes_everything_and_never_leaves_a_book` asserts failed downloads leave no book/partial; `tests/test_cancel.py::test_cancel_mid_download_stops_the_job_and_cleans_up` asserts cancellation cleans partial work. Fake network failure showed “Failed — Retry” and no `.partial`; screenshot `~/.cache/dante-oa/r2-shots/download-fail-network.png`. A fake B0FAKE0004 download was cancelled after its first 200 KB progress event; final event was `cancelled`, no partial directory remained. |
| Disk full or low | **Covered and manually checked.** `tests/test_get.py::test_get_disk_failure_refuses_before_writing` and `test_free_space_preflight_requires_1_1x` assert preflight failure before writes. Fake `disk` failure showed its row error and left no `.partial`; screenshot `~/.cache/dante-oa/r2-shots/download-fail-disk.png`. |
| Missing dependency | **Covered and manually checked.** `tests/test_onboarding.py::test_install_command` checks the generated install command. Fake status override with missing `mpv` and `ffmpeg` showed the install command `omarchy-pkg add mpv ffmpeg`; screenshot `~/.cache/dante-oa/r2-shots/missing-tools.png`. The override was removed afterward. |
| Audible API change / diagnostic | **Fixed here.** `tests/test_event_log.py::test_diagnostic_redacts_secret_options_and_limits_doctor_details` checks version, command, code, message, hint, tool details and redaction of `lavf_options`, `activation_bytes` and token-looking values. `tests/test_event_log.py::test_service_runs_doctor_and_copies_diagnostic_through_stdin` checks doctor-on-error and stdin-based `wl-copy`. Fake internal sync showed “Audible connection problem” and “Copy diagnostic”; diagnostic IPC included `sync`, `internal`, the simulated API message and tool checks, without auth/file details. Screenshot `~/.cache/dante-oa/r2-shots/diagnostic-error.png`. |
| Multi-part books | **Not applicable.** D5 was approved at G0: S4 found `MultiPartBook` downloads and plays as one file with ordinary chapters; see `docs/SPIKE-RESULTS.md` §S4. |
| Book removed from Audible while local | **Fixed here and manually checked.** `tests/test_library.py::test_local_book_missing_from_catalog_remains_playable_and_searchable` and `test_local_book_missing_catalog_uses_asin_and_no_progress_if_unknown` check metadata/ASIN fallback, local/playable status, position filter and search; `tests/test_local_remove.py::test_local_scan_includes_safe_catalog_metadata` checks scan metadata. Hiding local B0FAKE0001 from fake catalog left a local row named “The Lighthouse Ledger,” marked “No longer in your Audible library”; pick/resume loaded its fake file, and Remove reduced the row count from 5 to 4. Screenshots `~/.cache/dante-oa/r2-shots/orphan-row-while-open.png` and `orphan-removed.png`. |
| Shell restart during playback | **Covered.** `docs/MANUAL-TEST.md` `## P9 (desktop)` row 8 records same fake mpv PID, reattach and continued playback after restart; row 4 records the real-mode acceptance. In this R2 run, the P9 same-behavior IPC smoke journey ran; after removal, restart returned 4 catalog rows, no local fake books and no player loaded. |
| Two instances / double-click | **Covered and manually checked.** `tests/test_joblock.py::test_second_job_command_is_busy` asserts the backend lock returns `busy`; `tests/test_row_actions.py::test_pick_acts_on_the_decision` checks pick/confirm behavior. Fake pick/confirm of B0FAKE0003 followed by a second confirm returned `error: nothing asked`; event log showed one successful `get` for that confirm. |
| Long titles / missing covers | **Covered.** `BookRow.qml` elides long titles and `Cover.qml` uses the themed fallback when cover art is absent. The fake fixture has no long title; the missing-cover tile was visible in the orphan-row screenshot above. |
| Finished book selected again | **Covered.** `tests/test_library_ui.py::test_resume_choice_finished_far_from_the_end_asks` and `test_resume_choice_finished_at_the_end_starts_over` check the Resume / Start over choice; B11 MANUAL-TEST row 7 records the real near-end Start over journey. |
| R2 note — B11 d | **Covered; note remains open for future real book.** B11 MANUAL-TEST row 10 records the 120-chapter fake book; row 3 records Carl's 50 chapters through `chapters-file`. BEE has no real 100+ chapter book to check. |
| R2 note — B13 aax | **Deferred.** BEE has no legacy `.aax` book. Stub-port tests cover lazy activation-bytes fill; keep the real-account step open in PLAN until Chris has an aax book. |

### R2 run notes

The fake `libraryQuery` was reset to `recent all ""` after inspection. A Quickshell crash dialog for PID 461575 was visible during the desktop run and was left untouched; active shell PID 521374 remained responsive. On the post-smoke restart, the journal showed no warnings from this plugin's files; the reported warnings were from Omarchy's stock `Bar.qml` and socket connections.

## R1 (desktop) — 2026-10-09, HMSP-OMARCHYBEE, live folder on `main` (R1a at `a50f32d`, R1b at `cc0cfa2`)

Real mode (no dev-fake flag), connected, 91 books, Dungeon Crawler Carl (`B08V8B2CGV`) loaded and paused in mpv 99684 throughout (16 104 035 ms before and after). Chris edited our entry in `~/.config/omarchy/shell.json` by hand and looked; Dante read IPC, the books-location record and the journal over SSH. No shell restart between edits. The R1b live folder was pulled once and the shell restarted once after #101 merged (new shell 319300: zero non-DEBUG lines from our files, no crash).

| # | Check | Steps | Result | Date |
|---|---|---|---|---|
| 1 | `skipSeconds` applies live | Entry set to `{"id": "latentoperator.audible", "skipSeconds": 30}`, saved; open Mini | **Pass** (Chris): ⏪/⏩ showed 30 with no restart (no book loaded at the time; the buttons were disabled but labelled). | 2026-10-09 |
| 2 | Removing it restores the default live | Key deleted, saved | **Pass** (Chris): ⏪/⏩ back to 15. | 2026-10-09 |
| 3 | First start after R1b records the folder silently | Merge #101, pull, one restart, `booksDir` unset | **Pass.** `~/.local/share/omarchy-audible/books-location.json` written as `{"books_dir": "/home/chrisgray/Audiobooks/Audible"}`; no notice; 4 local books. | 2026-10-09 |
| 4 | Old-books notice | Entry set to `{"id": "latentoperator.audible", "booksDir": "~/Audiobooks/r1b-empty"}`, saved; open Library. Got it not pressed, nothing downloaded | **Pass** (Chris): notice "4 downloaded books are still in ~/Audiobooks/Audible…" naming the new folder; the 4 books shown as not downloaded. Dante: local storage 0, the record still the old folder (no silent ack), `~/Audiobooks/r1b-empty` not created, zero warnings. | 2026-10-09 |
| 5 | Back to the default | Key deleted, saved | **Pass** (Chris): notice gone, the 4 books local again. Dante: storage 4 books (2 796 652 955 bytes), 91 books, record unchanged, `r1b-empty` still absent, player paused at the same position, zero warnings. | 2026-10-09 |

### Notes

- The problem notice (an unsafe `booksDir`) and Got it were checked in fake mode only (#101 rounds 1–2, screenshots on BEE in `~/.cache/dante-oa/r1b-shots/`); pressing Got it in real mode would have recorded the empty folder.
- The other R1a settings (`defaultSort`, `autoRemoveFinished`, `showTitleInBar`, `defaultSpeed`, `syncOnOpenHours`) were checked live in fake mode in #100.

## R8 (desktop) — 2026-10-08, HMSP-OMARCHYBEE, live folder on `main` at `88c51a5`

PR #98 merged; the live folder was pulled once and the shell restarted once (new shell 577997: zero warnings from our files; no crash). Start state: real mode (no dev-fake flag), one `quickshell`, connected, 91 books, Dungeon Crawler Carl (`B08V8B2CGV`) loaded and paused in mpv 262406. Chris did the clicking; Dante read IPC, `state.json` and the account over SSH. Times are local (UTC−5). These rows also close the two P9 §5 "Stop, then play again" steps (P9 rows 1 and 4).

| # | Check | Steps | Result | Date |
|---|---|---|---|---|
| 1 | F38 move while paused, then Stop | Open Mini, ⏯, a few seconds, ⏯ (pause), ⏩15 twice while paused, ■ | **Pass.** mpv ended (no `mpv` process), `playerStatus` unloaded/idle, panel on Library, bar glyph the book. `state.json` held 13 632 711 ms (3:47:12), 30 s past the pause; `pushState` `last: done`, queue empty; a real `position-get` read back 13 632 711 (`own: true`). Pushes: one on pause, one on Stop with the moved spot. Note: the first ⏯ ran catch-up (`catchup jump 21452895 -> 13595201`): the account held a newer position (3:46:35, 02:35 UTC) than BEE's paused 5:57:32, so the book resumed from the account's. That is catch-up working as designed (P9 §5 row 2); Chris had listened on his phone, so the jump was correct. | 2026-10-08 |
| 2 | Play again after Stop | Play Carl from its Library row | **Pass** (Chris): resumed at the stopped spot. | 2026-10-08 |
| 3 | Stop, then play again (player machine) | A few seconds of play, ■, play Carl again from its row | **Pass** (Chris): a new mpv (598283) started and resumed where it stopped; `state.json` 13 651 399 ms, push done, queue empty; zero warnings from our files. | 2026-10-08 |

## P9 (desktop) — 2026-10-08, HMSP-OMARCHYBEE (two 1920×1080 monitors, DP-4 and DP-5), live folder on `main` at `3899312`

Brief: [briefs/P9-desktop.md](briefs/P9-desktop.md) §5, after #86–#96 merged. Start state: real mode (no dev-fake flag), one `quickshell`, one bar per monitor, connected, 91 books. BEE had rebooted at 18:47, so no mpv was running and nothing was loaded; the live folder was pulled to `3899312` and the shell restarted once. Chris did the clicking and listening; Dante drove IPC, `state.json` and the journal over SSH. Times are local (UTC−5). Book: Dungeon Crawler Carl (`B08V8B2CGV`).

| # | Check | Steps | Result | Date |
|---|---|---|---|---|
| 1 | F38, a move while paused | Play, pause, ⏩ three times while paused; open the phone app | **Pass.** `state.json` held the moved spot (3:49:59, 13 799 571 ms) at 20:26:30, `last_played_at` updated, push done, queue empty; the phone picked up exactly where BEE left off. **Stop, then play again: not run**: neither Mini nor Full has a Stop control (see Notes). | 2026-10-08 |
| 2 | Catch-up | Paused well over 30 s; ~90 s skipped ahead on the phone; ⏯ on BEE | **Pass.** "Checking Audible…" showed, then the event log `catchup jump 13859487 -> 13961045` (3:50:59 → 3:52:41) and playback from there. | 2026-10-08 |
| 3 | Push | Play, pause on BEE | **Pass.** `pushState`: `last` done, queue empty, `staleCount` 0, no stale line; `state.json` queue empty. Played a few seconds rather than a minute; the pause push is the same path. | 2026-10-08 |
| 4 | Player machine | Seek with the scrub bar, a chapter jump (to 25), then `omarchy-restart-shell` at 20:58:59 during playback (5:56:39) | **Pass.** The same mpv PID (262406, started 20:25:57) kept playing; the new shell (323920 replacing 230803) reattached within 10 s, connected and playing, the position moving on (5:56:59 → 5:57:02); Chris heard no gap or stutter. **Stop, then play again: not run** (no Stop control). | 2026-10-08 |
| 5 | IPC | `toggle` ×2, `playPause` ×2, `playerStatus`, `libraryQuery title all ""` | **Pass.** `toggle` closed then opened the panel; `playPause` resumed then paused, `playerStatus` following each; `libraryQuery` → `error: dev only` (and the dev-only `quitPlayer` → `error: dev only`, player untouched). | 2026-10-08 |
| 6 | Removal | — | **Skipped** (Chris): removal has passed in real mode several times before (G4, B11, Follow-ups). | 2026-10-08 |
| 7 | Smoke | `journalctl --user -b` for the new shell's PID after the restart in step 4 | **Pass.** Zero warnings from our files; one `quickshell`. | 2026-10-08 |

### Notes

- **No Stop control in the views.** Stop exists only as the dev-only IPC `quitPlayer` (real mode answers `error: dev only`); no view, component or `BarWidget` has ever called it, and SCOPE does not ask for one (FR-U5 only says dismissing never stops playback). In real mode the only way to unload a book and end mpv is to quit the shell or reboot. The F38 and player-machine "Stop, then play again" steps were therefore not run by hand; both are covered in fake mode (#86, #96). Placed in PLAN M5 as R8.
- **Last pause wins.** After the catch-up in step 2, the phone kept playing; BEE's pause then pushed BEE's position, so the account moved back to BEE's spot. That is the designed rule (ARCHITECTURE §4.6), noted because it can look like the phone jumping back.
- **Reboot.** BEE rebooted at 18:47 through `systemctl reboot` from Chris's desktop session, before this check; it was not traced to any agent.

## Follow-ups (desktop) — 2026-10-07, HMSP-OMARCHYBEE (two 1920×1080 monitors, DP-4 and DP-5), live folder on `main` at `4488ef2`

Brief: [briefs/FOLLOWUPS-desktop.md](briefs/FOLLOWUPS-desktop.md) §5, after #77–#84 merged. Start state: real mode (no dev-fake flag; the flag was deleted and the shell restarted on `5e5dfb8` earlier the same day), one `quickshell`, one bar per monitor, connected, 91 books, nothing playing. The live folder was pulled from `5e5dfb8` to `4488ef2` while paused (#84 is docs and spikes only, so no restart). Chris did the clicking; Claude Code drove and checked IPC state and the journal. Times are local (UTC−5).

| # | Check | Steps | Result | Date |
|---|---|---|---|---|
| 1 | P6, push and phone | Play the current book (Dungeon Crawler Carl, chapter 15) a few minutes, pause | **Pass.** Paused at 3:54:27 (14 067 284 ms); `pushState`: `last` done, queue empty, `staleCount` 0, no stale line. The phone app showed the same spot. | 2026-10-07 |
| 2 | P7, Start over on a finished book | Auberon (`1549170090`, 145 min) played to the end, then ▶ from the library; listen, pause | **Pass.** At the end it was finished and not under In progress. ▶ started over at 0 without asking: it was within 30 s of the end, so `LibraryUi.resumeChoice` returns start-over (SCOPE §6, as designed). Paused at 0:47: under In progress, no "You finished", `state.json` `finished: false`, push done. | 2026-10-07 |
| 3 | U10, the row's question | Strange Dogs (`B073X5V27J`; local, finished, saved at 0): pick, then the row's ▶ while the question is up | **Pass.** The Resume / Start over question showed on Strange Dogs' own row; the row's ▶ resumed without asking again; `libraryState` `ask` empty afterwards. Resume keeps `finished` (P7 clears it only on Start over or a move back). The play-error title and Stop clearing it: **fake mode only**, since there is no safe way to cause a real play error (passed in fake mode on `u10-findings`, #79). | 2026-10-07 |
| 4 | F27, dev IPC in real mode | `libraryQuery recent all ""`; `playerStatus`; the public methods a key binding calls | **Pass.** `libraryQuery` → `Error: dev only`. `playerStatus` works. `toggle` → `ok` twice (drawer open, closed); `playPause` → `checking`, playing, then `ok`, paused. BEE has no Hyprland bind for the plugin (the plugin adds none), so the methods were called directly. | 2026-10-07 |
| 5 | Two monitors (F19, F25) | Pick a book from DP-5's drawer; open the chapter popup on DP-5, then on DP-4 | **Pass** (Chris's hand check). The player opened on DP-5; the chapter popup opened only on the panel in use. | 2026-10-07 |
| 6 | F21, speed and volume survive quit | Set 1.5× and a new volume, play, Stop, start a book again | **Pass** (Chris's hand check). Both came back. Chris set them back to 1× and 100 afterwards. | 2026-10-07 |
| 7 | U9, pause lag | — | **Answered in #84.** About 40 ms from ⏯ to silence; the second of lag Chris heard came from Moonlight, and ⏯ is fine at BEE. | 2026-10-07 |
| 8 | Smoke | Seek, a chapter jump, then `omarchy-restart-shell` at 20:32:07 during playback (3:46:34, chapter 16) | **Pass.** Seek and chapter jump landed. The same mpv PID kept playing; the new shell (one `quickshell`, one bar per monitor) reattached, connected and playing, the position moving on (3:46:46); Chris heard no break. `journalctl --user -b --since 20:32:07`: **zero** warnings from our files (Omarchy's own `Bar.qml` `moduleName` only). | 2026-10-07 |
| — | R2 (B13, aax) | — | **Skipped:** every local book on BEE is aaxc. | 2026-10-07 |

### Notes

- **Hot-reload warnings are not startup warnings.** Earlier the same day the journal showed `FullView.qml:289` (`Cannot read property 'chapters' of null`) and `ChapterList.qml:40` (`Property 'follow' … is not a function`) at 15:43:54–15:44:09 and 15:53:53. The first came from another plugin's folder changing (omamail), which reloads every plugin, and a Quickshell crash and self-restart; the second from the `git pull` into the live folder. The brief already expects these warnings during a reload. A clean restart (step 8) logs none.

## B11 — 2026-10-06/07, HMSP-OMARCHYBEE (two 1920×1080 monitors, scale 1), live folder detached at `ad190b4` (`b11-desktop`, Codex PASS)

Start state: real mode (no dev-fake flag), one `quickshell`, one bar per monitor, signed in as Christopher, 91 books, nothing playing; Carl (`book.m4b`) the only local book. Chris did the clicking; Claude Code drove and checked IPC state. Key checks report counts only: the needles are the book's key and iv plus the account activation bytes, read in-process and never printed. Times are UTC.

| # | Check | Steps | Result | Date |
|---|---|---|---|---|
| 1 | Fresh locked download | Strange Dogs (cloud, finished) → click → confirm download; disk sampled every 0.5 s | **Pass.** `book.aaxc` (72.8 MB), `key.json` mode `600` (fields `format`/`key`/`iv`), `chapters.txt` (5), `meta.json` (`aaxc`, `locked: true`). `find ~/Audiobooks/Audible -name '*.m4b'`: only Carl's; no `.partial` anywhere. Peak growth of the books dir **1.000×** the book; `/home` free space dropped 0.93×. Europe later: 1.80 GB, peak 1.000× (free space −0.97×). | 2026-10-06 |
| 2 | Play → seek → chapter → resume | Pick → "You finished…" → Start over; scrub to near the start, middle (71:02), near the end (129:39); Mini popup → chapter 3 (69:43); Full list → chapter 2 (47:05); quit (IPC) and pick → Resume | **Pass.** Every step landed (player log every 0.5 s); no `playError`. Resume started at the saved 45:05. A first resume attempt hit the row's ▶ instead of the banner's Resume, which only asks again (finding b). Remove from this device ran in step 7. | 2026-10-06 |
| 3 | 100+ chapters | **Not possible:** no book in Chris's library has 100+ chapters (Chris checked the phone app). Europe (61 h) has 17 in both Audible's list and the file. **Substitute, Chris's choice:** Carl removed and downloaded again as a locked `book.aaxc` (50 chapters through `chapters-file`) | **Pass on the substitute.** mpv's 50 chapter starts match `chapters.txt` exactly (max difference 0 ms); Chris compared the list with the phone, scrolled the Full list (smooth) and jumped from it ("all checks passed"). The 120-chapter fake book covers the long-list path in fake mode (step 10). **For Dante:** BEE no longer has an old `.m4b`. | 2026-10-06 |
| 4 | The unlock is real | Throwaway mpv 0.41 (`--no-config --ao=pcm`, own socket, key sent only in the `loadfile` option map); 20 s slices of Strange Dogs at 1 min and 67 min, then the same without the key | **Pass.** With key: 20.0 s each, RMS 2711 and 2709 (16-bit), `end-file` eof, **0** decoder-error lines. Without key: **0 s** of audio, 1508 and 2439 decoder-error lines (one load ended in error). Key hits in the throwaway's argv and log: 0. PCM files deleted. | 2026-10-07 |
| 5 | No key anywhere | While Strange Dogs played; again after the shell restart (step 8) and while the locked Carl played | **Pass, every time:** `ps -eo args` none; `journalctl --user -b` since the load none; `recentEvents`, `playerStatus`, `panelState`, `libraryState` none; `state.json` none; `get_property demuxer-lavf-o` after load **empty**. | 2026-10-07 |
| 6 | Old books still play | Carl as `book.m4b` (before step 3): pick → resumed; skip +120/−120; pause, quit, pick again | **Pass.** `play-info` gave `book.m4b`, `chapters_file` null, no key; 50 embedded chapters; started at 3:34:08; +120/−120 landed at 3:36:09 / 3:34:10; resumed at the saved 3:34:15. | 2026-10-07 |
| 7 | J6 in full | Strange Dogs moved to 40 s before the end (IPC `playAt`), played out → Remove from this device → download again → click | **Pass.** Finished at 8,996,660 of 8,996,938 ms, marked finished, end pushed. `remove` freed 72.8 MB; `get` ok. On the click it **started over without asking**: Audible had it within 30 s of the end, and `LibraryUi.resumeChoice` (SCOPE §6, unchanged by B11) starts a finished book over in that case. The prompt itself was seen in step 2, where the finished book was mid-way. The resume-from-the-account half also ran on Carl (step 3: removed, downloaded again, resumed at 3:34). Side effect: the few seconds played pushed 0:05 for Strange Dogs. | 2026-10-07 |
| 8 | Shell restart during locked playback | `omarchy-restart-shell` while Strange Dogs played | **Pass.** Same mpv PID; the position moved on ~9 s across the restart; the service reattached (connected, 5 chapters, live state) 6.4 s after the restart returned; one `quickshell`, one bar per monitor; Chris heard no break. | 2026-10-07 |
| 9 | B15, `last_updated` is UTC | A real push during step 2: the pushed 4,191,385 ms was current at 04:36:57.5–58 UTC (player log); `position-get` returned `updated_at` `2026-10-07 04:36:58.555` | **Pass:** offset **about +1 s** (the log's resolution); the local clock is UTC−5. Recorded in SPIKE-RESULTS S3. | 2026-10-07 |
| 10 | Fake mode, tests | Fake mode on the same code (`bc73798`; `ad190b4` adds only the STATE row): fake `get` with `OMARCHY_AUDIBLE_FAKE_CHAPTERS=120` → play (120 chapters via `chapters-file`), service `get` → pick → play, races, reattach. On `ad190b4`: `pytest`, `make check-symlinks`, `omarchy plugin validate .` | **Pass.** Details in STATE (B11 desktop). Tests: see the PR. | 2026-10-06 |
| — | Error line (hand check) | IPC `playAt` on a cloud book (Auberon) while Strange Dogs was loaded, then the drawer | **Pass.** Mini showed "Couldn't start playback: no local book for <asin>" in the urgent colour; Strange Dogs stayed loaded. Chris noticed that the line stayed under Strange Dogs until the next play attempt. **Fixed:** it now clears as soon as a book plays again (see the PR). | 2026-10-07 |

### Findings (for Dante)

- **a. Debug `libraryQuery` changes the drawer.** It writes its sort, filter and search into the shared `LibraryModel`, and the search field doesn't show it. After a `libraryQuery … "Dungeon Crawler Carl"` the drawer listed only Carl, and Chris thought the library had stopped loading. This has been the case since M2 and isn't B11's. Make it read-only, or have the field show the search.
- **b. A finished book is easy to misread.** The "You finished … Resume · Start over" question is a one-line banner, and the row's ▶ only asks again. Start over keeps the finished flag, so the banner still says "You finished" at 33%.
- **c. The play error names the ASIN,** not the title (the backend's `not_local` message).
- **d. No 100+ chapter book** in the library; §4.3 ran on Carl's 50 chapters through `chapters-file` (step 3). BEE now has no old `.m4b` left for regression checks.
- **e. Live folder left on `ad190b4`, not `main` (Chris's decision, 2026-10-07).** Every local book is now locked, which `main` can't play, so going back to `main` before `b11` merges would stop Carl. Put the live folder back on `main` once `b11` is in `main`.

## G4 — 2026-10-06, HMSP-OMARCHYBEE (two 1920×1080 monitors, scale 1), `main` at `a6e60a2`

Start state: real mode (no dev-fake flag), one live `quickshell` (two defunct children left from the 14:51 restart crash), one bar per monitor, signed in as Christopher, 91 books, Dungeon Crawler Carl loaded and paused. Theme: Catppuccin.

| Journey | Steps | Result | Date |
|---|---|---|---|
| J1 First run | Drawer → Disconnect → confirm → Connect Audible → browser sign-in → paste redirect URL back | **Pass.** Library back a couple of seconds after the paste (target < 1 min). `logout`, `login-start`, `login-finish` all ok; status `authenticated`, account Christopher; sync back to 91/91; the one local book (Carl, 773 MB) kept. A `position-get` during the signed-out gap failed with `auth_failed` as expected and caused no change. | 2026-10-06 |
| J2 Start a book | Drawer → typed the first letters of "Strange Dogs" (cloud, 34%) → Enter → watched the download → Enter again | **Pass.** Download progress showed; `get` ok (71 MB, `book.m4b`); the row became a play button and did not start on its own; second Enter closed the drawer and the mini player played from the saved 50:18 (remote position matched). | 2026-10-06 |
| J3 Dismiss and keep listening | Carl playing → Esc → bar icon → click away | **Pass.** Audio continued after Esc and after clicking away; the bar icon brought back the mini player. | 2026-10-06 |
| J4 Control it (long real book) | Carl (50 chapters), mini player: ⏪15, ⏩15, ⏭, ⏮, chapter popup jump, speed pill to 1.25× and back | **Pass.** Note: ⏯ is not instant; audio carries on for about a second after pause (Chris: "not terrible"). See finding below. | 2026-10-06 |
| J5 Maximize (long real book) | Mini → Full player; chapter jump from the Full list; 15 min sleep timer with countdown and Mini moon, then Cancel; speed chips and ±0.05; collapse by button and by Backspace | **Pass.** Scrolling Carl's 50-chapter list was fine. | 2026-10-06 |
| J6 Free up space | Strange Dogs moved to 30 s before the end over IPC (`skip`), played to the end, then Remove from this device | **Pass.** `remove` ok, freed 71 MB; only Carl left in `~/Audiobooks/Audible/`; the row is back to cloud at 100% (8,996,864 of 8,996,938 ms); still in the phone app's library. Re-download-and-resume half not run; moved to B11's acceptance (Dante, #56). | 2026-10-06 |
| J7 Switch devices (unplanned) | Listened to Carl in the car on the phone app earlier in the day; at the desktop pressed play on Carl | **Pass.** Local position was 2:24:02 (ch 9/50); on play it resumed at the phone's spot, ~3:41:32 (ch 15/50), which Chris confirmed is right. Local listening then pushed as expected. | 2026-10-06 |
| J7 Switch devices (planned) | Carl paused on the desktop at 3:33:18 → listened on the phone app → paused → pressed play on the desktop | **Pass.** The phone opened at the desktop's spot; the desktop's catch-up read returned the phone's 3:33:38 (`updated_at` 00:43:26 UTC) and resumed there. Chris: "on both devices it picks up exactly where it should." | 2026-10-06 |

### Themes (FR-U6)

Switched with `omarchy-theme-set` from the driving terminal (the same command as the theme menu); Chris looked at each one. The shell stayed up (one live `quickshell`) and the panel stayed open through every switch.

| Theme | Kind | How | Result |
|---|---|---|---|
| Catppuccin Latte | light | **Live switch with the Full view open** (Carl loaded), then Mini and Library | **Pass.** Full view repainted in place, still open in Full; text, chapter list, speed chips, scrub bar and icons readable. |
| Tokyo Night | dark | Live switch with Mini open, then Full and Library | **Pass.** |
| Gruvbox | dark | Live switch with Mini open, then Full and Library | **Pass.** |
| Catppuccin | dark (Chris's own) | Restored at the end | Restored. |

The journeys above ran under Catppuccin; the three-theme pass covered all three views (Mini, Full, Library) with a real book loaded, not a re-run of J1–J7 per theme.

### Findings from this run

- **⏯ lag (J4).** Audio continues for about a second after pressing pause. The pause path is direct (`Service.playPause` → `PlayerController.pause` → one mpv IPC `set pause`), so the lag is probably mpv's or PipeWire's audio buffer, not the plugin's logic. Not chased. A play after a long pause can also wait on purpose for the catch-up read (`Catchup.needsRead`). Left for Dante to decide whether it is worth tuning.
- **No way to reach the Library from the Full view** (Chris, during the theme pass). Full has collapse, ✕ and Backspace but no library button; Mini has one (FR-U3). FR-U4 doesn't list one, so this is not a defect against the spec. Chris wants it on the roadmap. Not added to PLAN.md here; left for the PLAN owner.
- The 14:51 restart-crash leftovers (two defunct `quickshell` children) were still present throughout and had no visible effect.

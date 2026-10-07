# Manual test record

Hand-run journeys from `docs/SCOPE.md` §3, one line per run. Chris does all the clicking; the driving CLI checks state over IPC and writes the line. Real mode unless a line says otherwise.

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

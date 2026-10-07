# Manual test record

Hand-run journeys from `docs/SCOPE.md` §3, one line per run. Chris does all the clicking; the driving CLI checks state over IPC and writes the line. Real mode unless a line says otherwise.

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

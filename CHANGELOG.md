# Changelog

All notable changes to Omaudible. Versions follow `manifest.json`.

## Unreleased

### Documentation

- The README and the plugin description now say up front that Audible has been refusing downloads to some accounts in third-party apps since early September 2026. Books you already downloaded keep playing. The FAQ explains that signing in again is not a reliable fix: on the maintainer's account, Audible refused a freshly registered device's first download within seconds.

### Fixed

- Theme colours now stay correct on Qt 6.12, which Omarchy 4.0.5 and later use. Qt 6.12 adds a `Color` type of its own, which hides the shell's palette from the plugin's screens, so text and bars could turn black or blank once Omarchy stops pinning plugins to Qt 6.11. Omaudible now asks for the palette by its full name (`Commons.Color`); nothing looks different today, and the colours keep working when that temporary pin is removed.

## 0.1.6 (2026-10-14)

### Fixed

- B01: Failed re-download backup/install moves now restore the previous book; if rollback itself fails, recovery files are retained and retry refuses rather than deleting the only copy.
- B02: Interrupted sign-in/import can no longer authorize deregistering an external audible-cli device; Disconnect requires matching plugin-owned device identity.
- B03: Unsafe default and fallback books folders now fail closed, including fake-mode symlink escapes, without touching files outside the safe books root.
- B04: Setup detects broken dependencies, incompatible Python and stale pins, repairs instead of silently succeeding, and restores a previous environment only if it is usable; healthy existing environments are upgraded automatically without another Set up step.
- B05: Malformed catalog identifiers and escaping cover paths are rejected before fetching or writing covers outside the cache.
- R01: Multiline license-denial messages now retain throttling recognition without exposing book details or credentials in diagnostics.
- S01: Disconnect discards held and queued downloads; delayed status replies cannot start them after sign-out or reconnect.
- S02: Stop, replay and book switches invalidate old resume replies so only the latest play intent chooses the start position.
- S03: Expired download pauses clear even with no waiting books; status refreshes are deduplicated and failures back off instead of polling every second.
- S04: Cancelling a download during a throttled completion no longer puts that book back in the waiting list; completed installs still count as successful.
- U01: Removing a book no longer in your Audible library requires a title-specific warning and confirmation in Library and Full; bulk removal and auto-remove preserve it.
- U02: Remove-all and Disconnect confirmations reset on dismissal, view changes and changes to eligible books; Esc dismisses the question first.
- U03: The unresolved position-sync warning now stays visible in Full as well as Mini and clears after a successful push.
- U04: Failed clipboard pastes preserve existing input and explain size, timeout and unavailable-clipboard errors without showing pasted secrets.
- U05: Download-throttle errors and the waiting banner now agree: downloaded books still play, with one deadline-based automatic-retry estimate rather than a contradictory “tomorrow” instruction.
- D01: Current-state, locked-original playback, setup-recovery and device-versus-library mutation documentation now match the implementation; earlier decisions and test logs remain historical.

## 0.1.5 (2026-10-14)

### Added

- Downloads now wait instead of failing when Audible is limiting them for your account. Audible sometimes refuses a download for a day or two — its answer is "throttled" — while the phone app still downloads. Omaudible pauses downloads, says in the Library when it will try again, and shows the books that were waiting as **Waiting**; they carry on by themselves, in the same order, once the pause is over, and their ✕ still cancels one. Your downloaded books play as usual throughout, and everything else — syncing, removing, playback positions — carries on. The backend writes the pause to `download-pause.json` in its data directory, reports the resume time as `downloads_paused_until` in `status`, and starts over at four hours, doubling to a day at most if Audible refuses again. Signing in again clears it; see the FAQ.

### Fixed

- A download Audible refused was reported as a network problem — "check the network and retry" — which sent you looking in the wrong place. The refusal is now recognised (Audible's `CustomerThrottled` reason, which only reaches audible-cli's debug log), so the plugin knows downloads are being held and says so plainly. Only the reason code is logged, never the message, which names the book.

## 0.1.4 (2026-10-13)

### Security

- A download in progress no longer exposes the book's key to other users on the same computer. audible-cli writes the key into a temporary voucher file before the audio finishes, and the staging folder (`.partial/`) used to be created with your normal permissions, so with a books folder other users could open, they could read that voucher until the download completed (marketplace review of 0.1.3). The staging folder is now created fresh as `0700` with any inherited ACL removed, and audible-cli, ffprobe and ffmpeg run with umask `077`, so every file they write there is private from the moment it exists. A leftover staging folder that can't be removed, or a book folder that isn't yours, now stops the download with an `unsafe_path` error instead of being reused; a leftover symlink is removed, never followed. Finished books are unchanged: `key.json` was already `0600`.

## 0.1.3 (2026-10-13)

### Security

- The Library search and sign-in fields no longer let the shell read the clipboard by itself. Qt reads the whole clipboard, with no size limit or deadline, whenever an editable field exists and the clipboard changes, so a program that offered an endless clipboard could freeze the Omarchy shell or use up its memory (marketplace review of 0.1.2). The fields are now read-only to Qt; typing works as before, and pasting (Ctrl+V, Shift+Insert or **Paste from clipboard**) goes through a new helper, `bin/omarchy-audible-paste`, that reads at most 1 KiB for search or 16 KiB for sign-in and gives up after 2 seconds. A paste that is too large or too slow pastes nothing. Middle-click paste and the right-click Paste item no longer paste into these fields.

### Changed

- The marketplace description, bar-widget description and README intro now say "audiobooks", so people searching the marketplace for audiobooks can find the plugin. No code changes.

## 0.1.2 (2026-10-09)

### Fixed

- The shell no longer reloads the plugin (and on Quickshell 0.3.1 sometimes crashed) the first time the backend runs after an install or update. Python's bytecode cache now goes to `$XDG_CACHE_HOME/omarchy-audible/pycache` (by default `~/.cache/…`) instead of next to the plugin's code, where the shell watches every file. Old `__pycache__` folders in the plugin folder are now ignored; if you remove them, do it in one go or with the shell stopped, since deleting files there also makes the shell reload.
- `cancel` finds a download whose `OMARCHY_AUDIBLE_ASIN` has extra spaces, as the rest of the backend already accepts.

## 0.1.1 (2026-10-09)

### Added

- **Cancel download**: a ✕ on a queued or downloading row stops it; the row goes back to its download icon. (0.1.0's notes listed cancel, but only the command line had it.)
- Tests run on Python 3.11 to 3.14 in GitHub Actions for every pull request.

### Security

- No process the plugin starts has a book's title or ASIN on its command line, which other users on the same machine can read. The play-failure notification now just says playback couldn't start and points to the drawer, where the reason (with the title) stays. Backend commands and the audible-cli download take the ASIN from their environment, and ffmpeg/ffprobe run inside the book's staging folder with relative file names. Reported in the marketplace review.
- The download uses the audible-cli that setup installs in the plugin's environment; a system-wide `audible` is no longer used.

### Fixed

- A book file mpv can't open (missing or damaged) now says so with a notification and returns to the Library, instead of leaving an empty mini player.
- `cancel` checks that the download it names is really running before it stops anything, so a leftover record from a crashed download can no longer stop an unrelated program.
- Setup keeps your working Python environment if rebuilding it fails (for example offline after an update), instead of deleting it first.
- `position-push` refuses an `--at` time it can't read, which used to skip the check that protects a newer position from your phone.
- Timestamps like `12:00:00.Z` are read the same way on every supported Python version.
- The sign-in step explains Amazon's "page not found" page before the browser opens, not only after.

## 0.1.0 (2026-10-09)

The first public release.

### Added

- A book icon in the Omarchy bar that opens a library drawer: search, four sorts, filters for downloaded and in-progress books, and a storage line with **Remove all downloads**.
- Sign-in from the drawer through Amazon's own page in your browser, or reuse of an existing audible-cli login; eleven Audible stores. **Disconnect** deregisters a device the plugin registered.
- First-run setup from the drawer: a missing-tools check with a copyable install command, then a private Python environment with pinned `audible-cli` 0.6.0 and `audible` 0.12.0.
- Downloads on demand with progress. Books are kept exactly as Audible sends them (`aaxc`, falling back to `aax`) and unlocked in memory only while playing; no decrypted copy is written.
- A mini player (cover, chapter, skips, speed, scrub, Stop) and a full view (chapter list, fine speed, sleep timer, remove from this device). Keyboard control in both.
- Position sync with Audible in both directions: a newer position from another device is picked up on play, and listening is pushed back about once a minute and on pause or stop; the most recent listening wins.
- Playback that survives closing the panel and restarting the shell.
- Offline use: the saved library and downloaded books stay available. A downloaded book that leaves your Audible library stays playable.
- An IPC target, `latentoperator.audible`, with `toggle`, `openLibrary`, `playPause`, `skip`, `nextChapter`, `prevChapter` and `stop` for your own key bindings.
- Settings in `shell.json`: skip interval, default sort, default speed, auto-remove finished books, title in the bar, sync interval, and the books folder.
- Optional media keys and Omarchy Media widget play/pause through `mpv-mpris`.
- A copyable, redacted diagnostic for unexpected Audible responses.

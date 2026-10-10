# Changelog

All notable changes to Omaudible. Versions follow `manifest.json`.

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

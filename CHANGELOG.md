# Changelog

All notable changes to Omarchy Audible. Versions follow `manifest.json`.

## 0.1.0 (unreleased)

The first public release.

### Added

- A book icon in the Omarchy bar that opens a library drawer: search, four sorts, filters for downloaded and in-progress books, and a storage line with **Remove all downloads**.
- Sign-in from the drawer through Amazon's own page in your browser, or reuse of an existing audible-cli login; eleven Audible stores. **Disconnect** deregisters a device the plugin registered.
- First-run setup from the drawer: a missing-tools check with a copyable install command, then a private Python environment with pinned `audible-cli` 0.6.0 and `audible` 0.12.0.
- Downloads on demand with progress and cancel. Books are kept exactly as Audible sends them (`aaxc`, falling back to `aax`) and unlocked in memory only while playing; no decrypted copy is written.
- A mini player (cover, chapter, skips, speed, scrub, Stop) and a full view (chapter list, fine speed, sleep timer, remove from this device). Keyboard control in both.
- Position sync with Audible in both directions: a newer position from another device is picked up on play, and listening is pushed back about once a minute and on pause or stop; the most recent listening wins.
- Playback that survives closing the panel and restarting the shell.
- Offline use: the saved library and downloaded books stay available. A downloaded book that leaves your Audible library stays playable.
- An IPC target, `latentoperator.audible`, with `toggle`, `openLibrary`, `playPause`, `skip`, `nextChapter`, `prevChapter` and `stop` for your own key bindings.
- Settings in `shell.json`: skip interval, default sort, default speed, auto-remove finished books, title in the bar, sync interval, and the books folder.
- Optional media keys and Omarchy media widget support through `mpv-mpris`.
- A copyable, redacted diagnostic for unexpected Audible responses.

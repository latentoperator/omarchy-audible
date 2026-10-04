# Scope — Omarchy Audible

Status: **planning** · Last updated: 2026-10-04 · Owner: @latentoperator

## 1. One-line pitch

A book icon in the Omarchy bar that opens a themed drawer of your Audible library. Pick a book and a mini player takes over. Dismiss it and the book keeps playing. Only the books you're actually listening to live on the laptop.

## 2. Principles

1. **Dead simple.** One icon, one drawer, one mini player. No settings needed to get started.
2. **Native to Omarchy.** It's a Quickshell plugin using the shell's own theme, bar, and panel machinery. It must follow the current Omarchy theme with zero extra work, including live theme switches.
3. **The laptop is a cache, not a mirror.** The full library is browsable from a small catalog. Audio is downloaded on demand and removed freely. Removing a local copy never touches the Audible account.
4. **Playback outlives the UI.** Closing the panel or restarting the shell must not interrupt a book.
5. **Shareable.** A stranger with an Audible account and a fresh Omarchy install can run `omarchy plugin add …` and be listening within five minutes. Signing in is guided from the drawer (open a link, sign in in the browser, paste the return link back). If that flow proves impractical, a one-time terminal login is an acceptable fallback; in-drawer login is a nice-to-have, not a hard requirement.

## 3. Users and primary journeys

The user is an Omarchy user with an Audible account who works at the computer and wants to listen without keeping a browser tab open.

| # | Journey | Success looks like |
|---|---------|--------------------|
| J1 | **First run** | Click the book icon, click "Connect Audible", sign in in the browser, paste the URL back. The library appears in under a minute. |
| J2 | **Start a book** | Open the drawer, type three letters, press Enter. The book downloads (progress visible), the drawer closes, and the mini player is playing from the right spot. |
| J3 | **Dismiss and keep listening** | Press Esc or click away. The audio continues. Clicking the bar icon brings back the mini player. |
| J4 | **Control it** | Rewind 15s, forward 15s, change chapter, set speed, and set a sleep timer. Optionally bind hotkeys. |
| J5 | **Maximize** | One click expands the mini player into the full view (large cover, chapter list, speed, sleep timer). |
| J6 | **Free up space** | Remove a finished book from the laptop with one action. It stays in the library as a cloud book and re-downloads later, resuming where you were. |
| J7 | **Switch devices** | Listen on the phone, come back to the laptop, and the book resumes at the phone's position. |

## 4. Functional requirements

### 4.1 Account
- **FR-A1** Connect from inside the drawer: choose marketplace, open the sign-in page in the default browser, and paste the redirected URL back (a "Paste from clipboard" button is provided). Handles 2FA/CAPTCHA because the sign-in happens in the user's own browser.
- **FR-A2** Offer "Use existing audible-cli login" if `~/.audible/` has a valid auth file.
- **FR-A3** Show the connected account and marketplace, with a Disconnect action that deletes local credentials.
- **FR-A4** Detect expired or revoked credentials and show a "Reconnect" banner. Never fail silently.

### 4.2 Library
- **FR-L1** Catalog sync pulls the full library metadata (title, authors, narrators, series, runtime, cover, date added, progress) into a local cache. Covers are cached as thumbnails.
- **FR-L2** The catalog is available offline from cache. Sync runs at most once per N hours when the drawer opens, plus a manual refresh.
- **FR-L3** Sorts: **Recently listened** (default), Recently added, Title, Author.
- **FR-L4** Filters: All · On this laptop · In progress.
- **FR-L5** Search is instant and case-insensitive across title, author, narrator, and series. The search field has focus when the drawer opens.
- **FR-L6** Each row shows cover, title, author, runtime, a progress bar, and a state badge: ☁ cloud, ⬇ downloading (with progress), ● on this laptop.

### 4.3 Local storage
- **FR-S1** Selecting a cloud book downloads, converts, and then plays it. Only one download runs at a time, with a queue.
- **FR-S2** "Remove from this laptop" is available on any local book, from the row menu and the full player.
- **FR-S3** Removal deletes only local files. It never calls an Audible delete or return endpoint. Tests must enforce this.
- **FR-S4** The drawer shows total local usage ("3 books · 780 MB") and a "Remove all downloads" action.
- **FR-S5** Setting **Auto-remove finished books**, default **Off**. When on, a book is removed after it is finished (position within 30s of the end, or EOF).
- **FR-S6** Downloads are atomic. A cancelled or failed download leaves no half-files, and an interrupted one can be retried.
- **FR-S7** Check free disk space before downloading and show a clear error if it is short.

### 4.4 Playback
- **FR-P1** Playback is headless and independent of the UI. A detached `mpv` process is controlled over its IPC socket. The shell can restart and reconnect without interrupting audio.
- **FR-P2** Controls: play/pause, back N seconds, forward N seconds (N defaults to 15 and is configurable), previous/next chapter, seek, speed (0.75–3.0×), and a sleep timer (15/30/45/60 min or end of chapter).
- **FR-P3** Chapters come from the m4b. The player shows the chapter title, supports jumping to any chapter, and shows book-level elapsed and remaining time.
- **FR-P4** Resume. Position is saved locally every ~10s and on pause, quit, or book switch. On play, resume from the newest of the local and Audible positions.
- **FR-P5** Position sync to Audible is best-effort: push every ~60s and on pause or stop. A failure never interrupts playback and is retried later.
- **FR-P6** A shell IPC target exposes `toggle`, `playPause`, `skip <±s>`, `nextChapter`, `prevChapter` so users can bind Hyprland hotkeys. Media keys work if MPRIS is enabled (see ARCHITECTURE §7).

### 4.5 UI (all inside one panel, three views)
- **FR-U1 Bar widget:** a book icon. It shows play/pause state when a book is loaded, and an optional title (setting). The tooltip shows "Title — Author · 3h 12m left". Left click opens the panel: the Mini view if a book is loaded, the Library view if not. Middle click toggles play/pause.
- **FR-U2 Library view (drawer):** search, sort, filter, storage line, and the book list. Enter plays the highlighted row. Arrow keys navigate. Esc closes. A now-playing strip is pinned at the bottom when a book is loaded.
- **FR-U3 Mini view:** cover thumbnail, title, author, current chapter (tap for the chapter list), scrub bar with elapsed and remaining time, ⏮ ⏪15 ⏯ ⏩15 ⏭, speed pill, a maximize button, a library button, and a dismiss ✕.
- **FR-U4 Full view:** large cover, chapter list (current highlighted, click to jump), speed presets, sleep timer, book details (narrator, runtime, % complete), Remove from laptop, and a collapse button.
- **FR-U5 Dismissing** (✕, Esc, click-away) hides the panel and never stops playback.
- **FR-U6 Theme:** every color, font, radius, and border comes from the shell's `Style`/theme singletons. No hard-coded colors. It must be checked against at least three Omarchy themes (one light, two dark) and a live theme switch while open.
- **FR-U7 States:** every view has designed empty, loading, offline, and error states (see §6).

### 4.6 Settings
Exposed through the plugin manifest's `schema`, so they appear in Omarchy's settings UI.

| Key | Default | Notes |
|-----|---------|-------|
| `skipSeconds` | 15 | Back and forward skip (one value, 5–120) |
| `defaultSort` | Recently listened | |
| `autoRemoveFinished` | Off | FR-S5 |
| `booksDir` | `~/Audiobooks/Audible` | Where m4b files live |
| `showTitleInBar` | Off | Bar text next to the icon |
| `defaultSpeed` | 1.0 | |
| `syncOnOpenHours` | 6 | Minimum interval between automatic catalog syncs |

## 5. Non-goals (v1)

- Buying, browsing, or discovering books, and Audible Plus catalog browsing.
- Podcasts and other non-book content. They are hidden from the list.
- Multiple Audible accounts or profiles.
- True streaming without downloading. Download and convert takes about 20–30s per book, which is acceptable.
- Bookmarks, clips, and notes (a candidate for v2).
- Kindle/Whispersync for Voice and other ebook features.
- Windows, macOS, or non-Omarchy desktops.
- Distributing any decrypted audio or any keys. See §7.

## 6. Failure and edge cases that must be handled

| Case | Required behavior |
|------|-------------------|
| Offline | Catalog and downloaded books work. Cloud books show "offline". Sync shows "Last synced …". |
| Credentials expired or revoked | Banner "Reconnect Audible". Local playback is unaffected. |
| Download fails or is cancelled | Row shows "Failed — Retry". Partial files are cleaned up. |
| Disk full or low | Pre-flight check and a clear error. |
| Missing dependency (`mpv`, `ffmpeg`, `python`) | The Setup screen lists what's missing with the exact install command. No crash. |
| Audible API change breaks the backend | `doctor` reports it. The UI shows "Audible connection problem" with a copyable diagnostic. |
| Multi-part books (`MultiPartBook`) | Detect and either download all parts as one m4b or mark unsupported with a reason. Decided in spike S4. |
| Book removed from the Audible library while local | Keep the local file playable and mark it "no longer in library". |
| Shell restart during playback | Audio keeps going and the service reconnects to mpv. |
| Two plugin instances or double-click | Single-instance guard on the backend. Idempotent commands. |
| Very long titles and missing covers | Elide text and show a themed placeholder cover. |
| Finished book (100%) selected again | Offer "Start over" or "Resume" if the position is not at the end. |

## 7. Legal, ToS, and security

- **Unofficial.** Audible has no public API for third-party players. This project uses the community libraries `audible` and `audible-cli` (both AGPL-3.0, by mkb79). Audible can change its API at any time and the plugin may break until updated.
- **Personal use only.** The plugin is for listening to books you purchased, on your own machine. It must never include features that share, export in bulk, or upload decrypted audio. The README says this plainly. Decrypting Audible DRM may violate Audible's terms of use and, depending on jurisdiction, anti-circumvention law. Users decide for themselves.
- **No keys in the repo.** Never commit auth files, activation bytes, vouchers, tokens, or a real library catalog. Test fixtures are synthetic.
- **AGPL hygiene.** `audible`/`audible-cli` are installed by the end user's machine at setup (pip into a private venv) and invoked as separate programs. They are **not vendored** into this repo. Keep it that way.
- **Credentials at rest.** The Audible auth file contains a device private key and tokens, and activation bytes are an account-wide secret. Both are stored under the user's config directory with mode `0600`, never logged, and never printed to the UI. The pasted redirect URL contains a one-time code and is never logged or persisted.
- **Plugins are unsandboxed.** Omarchy runs plugins as code inside `omarchy-shell`. Keep the QML free of network access other than loading cached local covers, and keep all Audible traffic in the Python backend.

## 8. Success criteria for v1

1. Fresh Omarchy machine to first audio in ≤5 minutes using only the drawer.
2. Playback survives closing the panel and restarting the shell.
3. All of J1–J7 work from the UI. Sign-in from the drawer is the target; a one-time terminal login is acceptable if S1 fails.
4. Removing a local book never changes anything in the Audible account (verified by test and by manual check against a real account).
5. Visually correct under three themes and under a live theme switch.
6. Backend test suite passes offline, using the fake backend.
7. Idle cost: no polling loops when nothing is playing. Resident memory of the plugin (excluding mpv) is under ~100 MB.

## 9. Open decisions

| ID | Question | Recommendation |
|----|----------|----------------|
| D1 | License | MIT, matching the Spotify plugin. The AGPL libraries are not linked or vendored. |
| D2 | Repo visibility | Private until M3 is done, then public. |
| D3 | Name and id | Repo `omarchy-audible`, plugin id `latentoperator.audible`. |
| D4 | Position write-back to Audible | Spike S3 decides. If it's unreliable, v1 ships read-only sync plus local positions. |
| D5 | Multi-part books | Spike S4 decides. |
| D6 | Encrypt the auth file with a password | No for v1. The file is `0600`. Revisit if sharing widely. |

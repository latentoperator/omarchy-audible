# Architecture — Omaudible

Companion to [SCOPE.md](SCOPE.md). Facts marked ✅ were verified by hand on 2026-10-04 on an Omarchy machine with a real Audible account. Facts marked ❓ are assumptions that a spike in [PLAN.md](PLAN.md) must confirm before building on them.

**Gate G0 passed 2026-10-04.** Spikes S1–S6 are complete. Evidence is in [SPIKE-RESULTS.md](SPIKE-RESULTS.md), and this document has been corrected to match it. Ownership contracts that parallel work depends on are in §4.8.

## 1. Big picture

```
 Bar ── BarWidget.qml ──click──▶ KeyboardPanel drawer (views: Library | Mini | Full)
                                    │  binds to
                                    ▼
                              Service.qml   (kind: service, keepLoaded)
                      ┌─────────────┼────────────────┐
                      ▼             ▼                ▼
              PlayerController   LibraryModel    JobRunner
              (mpv JSON IPC)     (catalog+state)  (spawns backend)
                      │             │                │
                      ▼             │                ▼
          mpv --idle (detached)     │      bin/omarchy-audible  (NDJSON on stdout)
          unix socket               │                │
                                    │      ┌─────────┴──────────┐
                                    │      ▼                    ▼
                                    │  `audible` lib /      ffmpeg (fake audio) /
                                    │  `audible-cli`        ffprobe (duration)
                                    │      │
                                    └──────┴──▶ Audible API / CDN  (Python backend only)
```

**Rules of the road**
- QML never talks to Audible. All network and DRM work happens in the Python backend.
- QML talks to mpv directly over its IPC socket. The backend never plays audio.
- mpv is **detached** from the shell. Panel close, plugin hot-reload, and shell restart do not stop audio. On startup the service looks for a live socket and reattaches.
- Everything the UI shows comes from `catalog.json` + `state.json` + the filesystem. The UI never waits on the network to render.

## 2. Plugin shape (Omarchy shell)

A plugin is a git repo with `manifest.json` at its root. Users install with `omarchy plugin add <git-url>`. Developers link the repo into `~/.config/omarchy/plugins/latentoperator.audible/` (a symlink *to* the repo from outside is fine; a symlink *inside* the repo is not, see below). `omarchy-shell shell rescanPlugins` reloads the bar widget; `Service.qml` changes need `omarchy-restart-shell` (✅ S6). ✅ Confirmed 2026-10-04 (task A0): the shell discovers and lists a plugin whose directory is a symlink to the repo, so `make dev-link` works as written.

```
omarchy-audible/                     (repo root == plugin root)
  manifest.json                      kinds: service, bar-widget  (no `panel` kind, see §6)
  Service.qml                        singleton logic, mpv + backend control; declares the IPC target
  BarWidget.qml                      the book icon + the KeyboardPanel drawer hosting the views
  qml/
    LibraryView.qml  MiniView.qml  FullView.qml  OnboardingView.qml
    BookRow.qml  ChapterList.qml  ScrubBar.qml  Cover.qml  StateBadge.qml
    PlayerController.qml  LibraryModel.qml  JobRunner.qml  Format.js
    ServiceIpc.qml                   the one IpcHandler (`latentoperator.audible`), a child of Service
    Removals.qml                     books waiting to be unloaded before removal, and auto-remove
    CatchupFlow.qml                  ⏯ catching up with other devices: the account reads and the jump note
    SigninFlow.qml                   onboarding and sign-in: setup, Connect, Reconnect, Disconnect, the clipboard
    StateStore.qml                   state.json I/O; applies pure Store.js transitions
    lib/Store.js                     state.json adoption, operation replay and save decisions
    lib/Settings.js                  validation/defaults for manifest-backed widget settings
    lib/PlayerMachine.js             PlayerController's attach, launch, reconnect, quit and relaunch decisions
  bin/omarchy-audible                stdlib-only Python launcher (bootstraps venv, dispatches)
  backend/omarchy_audible/           Python package (runs inside the venv)
  tests/  fixtures/
  docs/
```

Reference implementations to read before writing QML, all on this machine:
- `/usr/share/omarchy/shell/README.md` and `plugins/README.md` (manifest, kinds, IPC, install)
- `~/.config/omarchy/plugins/quickshell.spotify/` (service + bar widget + panel + mini player; the closest analogue)
- `~/.config/omarchy/plugins/chrisgray.kanban/` (smallest possible bar widget)
- `/usr/share/omarchy/shell/plugins/panels/audio/` (first-party panel using the shared `Ui` components)
- `/usr/share/omarchy/shell/Ui/` and `Commons/` (theme singletons and components)

Marketplace/validator rules (from plugins.omarchy.org/develop): run `omarchy plugin validate .` before every release. Third-party ids cannot start with `omarchy.`. **The plugin folder (this repo) may not contain symlinks.** Never start a second Quickshell process. Manifest fields must be ones the shell supports; do not invent new ones.

Theming rule: import `qs.Commons` and `qs.Ui` and use `Style`/theme tokens only. Never hard-code a color.

## 3. On-disk layout

| Path | Contents | Mode |
|------|----------|------|
| `~/.config/omarchy-audible/auth.json` | Audible auth (device key, tokens) | 0600 |
| `~/.config/omarchy-audible/activation_bytes` | Account-wide decrypt key for legacy AAX | 0600 |
| `~/.config/omarchy-audible/config.toml` | audible-cli profile pointing at `auth.json` (generated) | 0600 |
| `~/.local/share/omarchy-audible/venv/` | Python venv: pinned `audible-cli`, `audible[cryptography]`, and this repo's `backend/` package | |
| `~/.local/share/omarchy-audible/catalog.json` | Library metadata cache. **Written only by the backend** (`sync`) | |
| `~/.local/share/omarchy-audible/remote.json` | Remote positions cache `{asin: {ms, updated_at}}`. **Written only by the backend** (`sync`, `position-get`) | |
| `~/.local/share/omarchy-audible/pushed.json` | This device's own recent pushes `{asin: {ms, at}}`, so its own echo is never mistaken for a newer position (P6, F1). **Written only by the backend** (`position-push`) | |
| `~/.local/share/omarchy-audible/state.json` | Local positions, last-played times, push queue. **Written only by `StateStore.qml`** | |
| `~/.local/share/omarchy-audible/books-location.json` | `{books_dir: "<absolute path>"}` acknowledged as the current books folder; written atomically by `books-location-ack` | |
| `~/.local/share/omarchy-audible/covers/<asin>.jpg` | Cover thumbnails | |
| `<booksDir>/<asin>/book.m4b` | Decrypted audio, chapters embedded — **old downloads only**, before B11 | |
| `<booksDir>/<asin>/book.aaxc` \| `book.aax` | The file exactly as Audible sent it, unlocked in memory at play time (B11, D7) | |
| `<booksDir>/<asin>/key.json` | Decryption material: `{format:"aaxc",key,iv}` from the voucher, or `{format:"aax"}` as a **reference** to the account's activation bytes, not a copy (D7) | 0600 |
| `<booksDir>/<asin>/chapters.txt` | ffmetadata chapter list built from Audible's `chapters.json` (absent when Audible sent no list) | |
| `<booksDir>/<asin>/meta.json` | Title, author, duration, size, downloaded_at, `format`, `locked` | |
| `$XDG_RUNTIME_DIR/omarchy-audible/mpv.sock` | mpv IPC socket | |
| `$XDG_RUNTIME_DIR/omarchy-audible/job.lock` | Exclusive lock held by the running job command (§4.8) | |
| `$XDG_RUNTIME_DIR/omarchy-audible/job.json` | `{pid, command, asin}` of the running job, for `cancel` | |
| `$XDG_RUNTIME_DIR/omarchy-audible/login-<id>.json` | Login session `{verifier, serial, marketplace, created}`, 10-minute TTL, tmpfs | 0600 | |

Books are keyed by **ASIN directory**, not by title. That makes removal a single `rm -r` of one directory, avoids filename-encoding problems, and makes "what is local?" a directory scan. The filesystem is the source of truth for "is this book local": a directory holding `book.m4b`, or a locked `book.aaxc`/`book.aax` **plus a readable `key.json`** (B11). A locked file with no key file is not local.

Fake mode's default books directory is `<fake data dir>/books`; it never scans the real `~/Audiobooks/Audible`. Fake mode honors an override only when the resolved target is strictly inside its data directory, and ignores a recorded folder outside that tree. The real mode default remains the unresolved `$HOME/Audiobooks/Audible` path string, so reported and playback paths keep their original spelling even when a symlink is present.

`state.json` (schema v1, written **only** by `StateStore.qml` (§4.8), with adoption decisions in `qml/lib/Store.js` and parsing/serialization in `qml/lib/Library.js`):

```json
{ "schema": 1,
  "books": { "<asin>": { "ms": 0, "updated_at": null, "last_played_at": null,
                         "played_since_download": false, "finished": false } },
  "push_queue": [ { "asin": "<asin>", "ms": 0, "at": null } ],
  "volume": null, "speed": null, "default_speed_setting": null }
```

- `ms` is the local position; `updated_at` is when it was written. The newest-wins merge (§4.6) chooses between this entry and `remote.json`.
- `last_played_at` is the "recently listened" key (§4.6); `played_since_download` gates position write-back; `finished` is the local finished flag.
- `push_queue` holds pending position write-backs, `at` being the local listening time (§4.6).
- `default_speed_setting` is optional. `StateStore` records the last default-speed setting it applied; a changed setting replaces the saved speed, while an unchanged setting preserves a speed selected with the pill.
- Unknown keys are kept across a parse/serialize round trip. A missing file, garbage, or a `schema` other than 1 recovers to an empty v1; `parseState` reports that with a `recovered` flag (which is not part of the file) so the service can start over.

The audible-cli profile is created programmatically in a plugin-owned config dir by setting `AUDIBLE_CONFIG_DIR` for every backend subprocess, so it never touches or conflicts with a user's own `~/.audible`.

## 4. Backend

### 4.1 Launcher and bootstrap
`bin/omarchy-audible` uses **only the Python standard library** so it runs on a fresh machine. It:
1. Handles `status`, `doctor`, and `setup` itself (these must work before any dependency exists).
2. For everything else, re-execs `venv/bin/python -m omarchy_audible …`.

   It sets `PYTHONPYCACHEPREFIX` to `~/.cache/omarchy-audible/pycache` (unless already set), so no `__pycache__` is ever written into the plugin folder. The shell watches `~/.config/omarchy/plugins` with `inotifywait -r`; every `.pyc` written there makes it reload the plugin, and on Quickshell 0.3.1 those reloads could crash the shell.
3. `setup` moves an existing ready venv (one with a marker, even for older pins) aside to `venv.previous` and restores it if the rebuild fails, so an update run offline never leaves no venv (F43); a venv without a marker is a killed run and is deleted. It then creates the venv with `python -m venv`, then `pip install` of the pinned `audible-cli` and `audible[cryptography]` (without the extra, `audible` warns on stderr about legacy crypto) **and of this repo's `backend/` package**, so that `venv/bin/python -m omarchy_audible` resolves. Progress is streamed as events.

The shell's plugin installer never runs plugin code, so the first-run Setup button in the drawer triggers `setup`. System packages the backend needs but cannot install: `mpv`, `ffmpeg`, `python`. `status` reports what is missing and the exact `pacman`/`omarchy-pkg-add` command to fix it.

### 4.2 Protocol
Every subcommand writes **one JSON object per line (NDJSON)** to stdout and exits 0 on success, nonzero on failure. Human logs go to stderr and are scrubbed of secrets. Every event has a `type`; the last event of a successful run is `{"type":"done"}`; on failure it is `{"type":"error","code":"…","message":"…","hint":"…"}`.

```
status                      → {"type":"status","ready":bool,"missing":["mpv"],"authenticated":bool,
                                "venv_ready":bool,"marketplace":"us","account":"j***@gmail.com",
                                "catalog_age_s":1234,"books_dir_problem":string|null,
                                "old_books":{"dir":"<absolute path>","count":N}|null,
                                "books_location_recorded":bool,"mpris_script":string|null}
books-location-ack [--if-no-old-books]
                            → records the current effective folder; conditional form rechecks old_books
                              and writes nothing when books remain there, then done(acked: bool)
setup                       → progress events, then done
login-start --marketplace us→ {"type":"login_url","url":"https://www.amazon.com/ap/signin?…","session":"<id>"}
login-finish --session <id>  (pasted URL on stdin) → done (warning="activation_bytes" when the
                              account AAX key could not be fetched) | error(code=bad_url|expired|auth_failed)
login-import-cli [--dir ~/.audible]          → done | error(code=no_auth_file)
logout                      → done (deregisters this device only, then deletes auth.json, activation_bytes, config.toml; keeps books)
sync [--full]               → progress {"type":"progress","stage":"library","n":40,"of":91}, then done
                              (writes catalog.json atomically, fetches missing covers)
get <asin>                  → {"type":"progress","stage":"download","bytes":123,"total":456}
                              … then {"type":"done","path":".../book.aaxc"}  (the locked original)
play-info <asin>            → {"type":"play_info","path":".../book.aaxc","chapters_file":"..."|null,
                               "lavf_options":"audible_key=…,audible_iv=…"}   then done
                              (for a legacy aax it may fetch the account AAX key once, §4.7)
cancel <asin>               → done | error(code=not_running)   (signals the running `get`, see §4.8)
remove <asin>               → {"type":"done","freed_bytes":N}      (LOCAL ONLY — see §4.4)
local                       → {"type":"local","books":[{"asin":…,"size":N,"downloaded_at":…,"title":…|null,"duration_ms":N|null,"authors":[…]}]}
position-get <asin…>        → {"type":"positions","items":{"<asin>":{"ms":N,"updated_at":"…"|null,"own":true?}}}
position-push <asin> <ms> --at <iso-8601> → done | error(code=invalid_args|stale|unsupported|network)
doctor                      → {"type":"doctor","checks":[{"name":…,"ok":bool,"detail":…}]}
```

`status.mpris_script` is the first readable mpv-mpris script at `/usr/lib/mpv-mpris/mpris.so`, `/etc/mpv/scripts/mpris.so`, or `$XDG_CONFIG_HOME/mpv/scripts/mpris.so` (default `~/.config/mpv/scripts/mpris.so`), else `null`. It is reported in fake mode too. `doctor` includes the same optional check; its `ok` is always true and `detail` is the installed path or `not installed (optional)`. The plugin starts mpv with this script only when detected; MPRIS support is optional and never affects readiness.

The first settings object causes Service to re-read `status`; before settings arrive, the UI does not show books-folder notices or silently acknowledge a folder. The silent acknowledgement runs only when `old_books` is null, the current folder is not recorded, and no `get` is active or queued. Service re-runs `status` after each `get` and `remove`, so a download that finishes in the prior folder is counted before an acknowledgement can hide it.

`--fake` (or env `OMARCHY_AUDIBLE_FAKE=1`) runs the same protocol against `fixtures/` with no network and no account. This lets UI work and tests proceed without credentials, and is what CI runs. Fake `get` produces the same layout as real mode — a short sine served as `book.aaxc`, a fake-hex `key.json`, `chapters.txt` and `meta.json` — and simulates progress and failures (`--fake-fail <code>`). `OMARCHY_AUDIBLE_FAKE_CHAPTERS=<n>` (1–500) or `--fake-chapters <n>` on a fake `get` gives the fake book `n` evenly spaced chapters, for UI checks on 100+ chapter books; real mode ignores it.

Fake-mode UI development also supports `sync --fake-fail network|internal` for controlled sync errors and `sync --fake-hide <asin>` to persistently omit a fixture book in `<fake config>/fake-hidden-asins.json`. These controls are rejected outside fake mode.

**No ASIN or title in any argv.** A process's command line is readable by every local user through `/proc/<pid>/cmdline`; its environment only by the same user. So the shell never puts an ASIN on a backend command line: a job keeps its ASINs in `args` (the queue, drawer and removal list match on them), and `qml/JobRunner.qml` takes them out at spawn time (`qml/lib/Launch.js`) and passes them in `OMARCHY_AUDIBLE_ASIN`, space-separated. The backend puts them back in front of the other arguments before dispatch (`cli.py`; for fake mode's `sync` it appends `--fake-hide <asin>`), so the forms above still work by hand, and refuses a call that names a book both ways (a variable left in a terminal must not pick the book a typed `remove` deletes); `get`, `remove`, `cancel`, `play-info` and `position-push` take exactly one, `position-get` several, and fake mode's `sync --fake-hide` one. The other processes follow the same rule: the audible-cli download (§4.3), ffmpeg and ffprobe (§4.3), mpv (no book in its argv; files load over the socket, §5.1), and the play-failure notification, whose text is generic (the reason, which can name the book, stays in the drawer). `tests/test_argv_privacy.py` fails if any launch names a book.

`play-info` is the only event that carries a key. Its `lavf_options` value is a secret: never log it, never store it (the service redacts it in `recentEvents`, `qml/lib/EventLog.js`), and clear it from mpv as soon as the file is loaded. PlayerController holds it only in `pendingLoad` until the load is sent; its connection machine (`PlayerMachine.step`, §5.2) is told only that a load is waiting. Since B13 it is also the only non-job command that may make a network call: a legacy aax book with no `activation_bytes` on disk and a saved login makes **one** fetch for the account-wide key, writes it `0600`, and continues; if that fetch fails it stays `error(code=decrypt)` with a retry hint, and aaxc/old-`.m4b` books never go near the network. There is no key value in any log line or error — on failure `play-info` emits `error(decrypt)`.

Fake mode carries its own onboarding state so the sign-in and setup screens can be exercised without a real account. A fresh fake tree **starts signed in**; `logout --fake` writes a `fake-signed-out` marker in the fake config dir and `login-finish --fake` / `login-import-cli --fake` remove it, so `status --fake` flips `authenticated` (and `ready`) accordingly. An optional `<fake config dir>/fake-status.json` — `{"missing": ["mpv"], "venv_ready": false}`, both keys optional — overrides those two `status` fields, and `setup --fake` drops the `venv_ready` override so the UI can return to the ready state. Real mode reads neither file.

### 4.3 Download pipeline ✅ (S2) — locked layout (B11, D7)
S2 verified the old decrypt path by hand:
- `audible download --asin <ASIN> --aax-fallback --cover --chapter -y -o <dir>` produced `*.aax` (264 MB for a 9-hour book, ~18 s), a 500px cover, and a chapters JSON.
- `audible activation-bytes` returned the 8-hex-character account key.
- `ffmpeg -activation_bytes <hex> -i book.aax -c copy book.m4b` is a lossless stream copy, **preserved all 20 chapters**, and ran in a few seconds. ffmpeg prints `Application provided duration … in stream 2 is invalid` warnings for the embedded cover stream; they are harmless.

**B11 dropped that conversion.** The plugin no longer writes a decrypted copy (D7), so those commands are history, not the pipeline: the file stays exactly as Audible sent it and mpv unlocks it in memory (§5.1).

Pipeline for `get <asin>`:
1. Pre-flight: content metadata gives `content_size_in_bytes` before download; require ≥ 1.1× that in free space (B11: without the decrypt pass the peak is the book itself, not twice it). A re-download counts an abandoned `.partial/` only — it is `rmtree`'d before the fetch, so those bytes really are reclaimable — and **not** the old copy, which stays on disk until the commit runs after the fetch (B14, F10, F34). The peak for a re-download is therefore the old copy plus 1.1× the new one.
2. Create `<booksDir>/<asin>/.partial/` and build the whole book **there**: `key.json` (`0600` at creation), `chapters.txt` and the audio renamed to its final `book.aaxc`/`book.aax` name. The book directory is untouched until the download has been verified (B14).
3. Download via `audible-cli` with `--aaxc --chapter -q best`, no progress bars. It runs as `<venv python> -P -m omarchy_audible.audible_download <options> -o .` inside `.partial/` (`-P` keeps that directory off the import path): that small wrapper reads the ASIN from `OMARCHY_AUDIBLE_ASIN` and calls audible-cli in-process with `download -a <asin>`, so neither the ASIN nor the book's folder is in any argv (§4.2). **Prefer aaxc; if no voucher is offered, retry with `--aax`** (G0 decision) — and only then: any other aaxc failure is the real error (F8). Note that audible-cli's own `--aax-fallback` goes the other way (aax first), so don't use it. Its stderr is staged as `.partial/audible.stderr`; on failure only its scrubbed last line is logged, and the file disappears with `.partial/` (F9). Report progress by polling the partial file size.
4. Write into `.partial/`: `key.json` `0600` — for aaxc `{"format":"aaxc","key":"<hex>","iv":"<hex>"}` from the voucher's `content_license.license_response.key`/`.iv`; for aax `{"format":"aax"}` only, a **reference** to the account's activation bytes, not a copy (D7). Write `chapters.txt`, the ffmetadata built from Audible's `chapters.json` (flat) with the shared `build_ffmetadata`; no JSON means no file.
5. Move the original audio onto its final `book.aaxc`/`book.aax` name **inside `.partial/`**, through a temp name in the same directory and one atomic rename. **Chapters come from Audible's list, not the file** (G0 decision; one book had 20 embedded chapters vs 46 in the API) — they are carried by `chapters.txt`, not baked into the audio.
6. A key-free sanity check, still in `.partial/`: `ffprobe` duration against the catalog runtime, within 1% (S7: the header opens without a key). If ffprobe cannot read an aax without activation bytes, skip the check and say so in the log.
7. Commit, only once everything in `.partial/` checks out: move the directory's previous audio, `key.json`, `chapters.txt` and `meta.json` aside **inside `.partial/`**, then move the new files in — the audio last, through `os.replace`, so "local" flips at one moment — and write `meta.json` (`format`, `locked: true`, the cached `acr`). SIGTERM is blocked for the whole commit, so a cancel that lands in it is delivered only once the book is whole and counts as a success, not a cancel; if the commit fails partway the files moved aside are put back, leaving the old copy byte-identical (B14, F35). An old `book.m4b` never sits beside a locked file (B14).
8. On failure or cancel, delete `.partial/` and every temp file; any previous copy in the book directory is left exactly as it was — a failure inside the commit first moves the files it took aside back — so a failed or cancelled re-download never costs the user a playable book (B14, F35). Nothing in `.partial/` counts as local (ARCHITECTURE §4.8).

Every child of `get` (the audible-cli wrapper, ffprobe, fake mode's ffmpeg) runs with `.partial/` as its working directory and relative file names (`./book.audio.tmp`, never a bare name that could read as an option or protocol), so no argv contains `<booksDir>/<asin>/`; fake mode's raw file is `fake-raw.<ext>`, not named after the ASIN.

**No `ffmpeg` or `ffprobe` argv in `get` may contain a key, iv or activation bytes**: the key is written to `key.json` and only read again by `play-info`, and it reaches mpv over the IPC socket, never as an argument (§5.1, D7).

### 4.4 Removal safety (hard requirement)
`remove <asin>` only deletes `<booksDir>/<asin>/`. It must verify the resolved path is inside `booksDir` and refuse otherwise. The backend has no code path that calls an Audible endpoint with a mutating method except position write-back (§4.6). A test greps the package for `delete`, `remove`, and `return` calls to the API and fails if any is found.

### 4.5 Catalog ✅ (S4)
`audible library export --format json` ✅ returned 91 items with: `asin`, `title`, `authors`, `narrators`, `genres`, `cover_url`, `runtime_length_min`, `date_added`, `purchase_date`, `release_date`, `rating`, `is_finished`, `percent_complete`.

Missing from the export and needed by the UI: **subtitle, series name and part number, content type (to hide podcasts), content delivery type (multi-part)**. These are in the raw `1.0/library` endpoint ✅ S4: request `product_desc,media,contributors,series,product_attrs,listening_status,percent_complete,is_finished` with `num_results=50` and page (91 items in 0.9 s; a much larger group list timed out). Covers: these groups give only a 500 px URL; try `image_sizes=252` or downscale.

Filtering: drop only podcast content types (`Podcast*`). **Keep `Lecture`**, which is a real content type in the test library.

Multi-part books (D5, G0 decision): `content_delivery_type: MultiPartBook` downloads, decrypts, and plays as one file with normal chapters. **No special handling.** `multipart` stays in the catalog for information only.

`catalog.json` (written atomically, `schema` versioned):
```json
{ "schema": 1, "synced_at": "2026-10-04T12:00:00Z", "marketplace": "us",
  "books": [ { "asin": "…", "title": "…", "subtitle": null, "authors": ["…"], "narrators": ["…"],
               "series": {"name": "…", "part": "2"}, "cover": "covers/<asin>.jpg",
               "runtime_min": 540, "date_added": "…", "percent_complete": 12.5,
               "is_finished": false, "multipart": false } ] }
```

### 4.6 Positions
Read ✅: `audible api 1.0/annotations/lastpositions -p asins=A,B` returns, per asin, `last_position_heard` with `status` (`Exists`|`DoesNotExist`), `position_ms`, `last_updated`. The API limit is **25 asins per call** ✅ S3.

Write ✅ S3: `PUT 1.0/lastpositions/{asin}` with `{acr, asin, position_ms}`; `acr` comes from `1.0/content/{asin}/metadata?response_groups=content_reference` and is cached in `meta.json`. The round trip is exact, and the phone app follows it (D4: **ship write-back**, G0 decision).

**The phone moves to a pushed position by itself** (it shows a notice with undo, it does not ask). So a wrong push silently moves the user's phone. Push rules:
- Push only positions produced by **listening on this machine**: on pause, stop, book switch, quit, and every ~60 s while playing. A seek, skip or chapter jump made here while paused counts too (F38, `Playback.positionCounts`; the snapshot takes where it lands, `Mpv.moveTargetMs`, until mpv reports it; a move sent while a load is still on its way, `Mpv.moveHitsPath`, isn't the showing book's); the position a reattach reports after a shell restart does not.
- Never push from `sync`, from the merge, or for a book not played locally since it was downloaded.
- Never push a position older than the remote `updated_at` (the user listened elsewhere since). Re-read the remote position immediately before a push. This device's own echo is never "newer" — see below.
- `position-push` **requires** `--at` (the local listening time the position came from). Without it the stale check cannot fire, so the command is `error(code=invalid_args)` with the usage exit code (F3).

`last_updated` has no timezone (`YYYY-MM-DD HH:MM:SS.f`). It looks like UTC; B6 confirms against a write at a known time.

**Own echo (P6, F1).** The account stamps a push with the **server** clock, so this device's own previous push can look newer than the next listening time whenever the computer's clock runs behind the server by more than the push interval. `position-push` therefore remembers its own writes: after every successful `port.push` it records `{ms, at}` for that ASIN in `<data dir>/pushed.json` (atomic tmp + rename; only the backend writes it, and a failed push records nothing). A re-read remote entry whose `ms` **equals** the recorded `ms` for that ASIN is this device's own echo and is never newer, whatever its `updated_at`; every other entry keeps the newest-wins rule, so a phone position with a different `ms` and a newer stamp is still `stale`. `position-get` marks the same exact match with `"own": true` in its `positions` event so the service can tell an echo from another device's listening (`qml/lib/Positions.js` `flushPlan` never drops a queued push whose remote item is `own`).

Merge rule: take the entry with the newest `updated_at` between local `state.json` and remote. If remote is newer, resume there (the user listened elsewhere).

`qml/PositionSync.qml` owns the in-memory flush state and applies the effects from `qml/lib/Sync.js` `Sync.step(state, event)`. The reducer sequences the `position-get`, drops and sends, stale count, offline retry count, refused runs and deferred next batch; `PositionSync` applies `run`, `setQueue`, `flush_later` and `finish` effects. The state queue remains written only through `StateStore`.

When the rule runs: a Library pick always reads the account (`position-get`, purpose `resume`) before loading. ⏯ on a book already loaded and paused (Mini, Space, middle-click, IPC `playPause`, all through `Service.playPause`) reads it only after a pause of 30 s or more, or when the pause time is unknown after a shell restart; opening the drawer on such a book starts the read early (purpose `catchup`, a result is used for 60 s). ⏯ waits up to 3 s for it, showing "Checking Audible…", then resumes locally. It seeks only when the account entry is newer than the local one, at least 2 s from the player, and not exactly a position this laptop wrote (its last push or its saved pause position: the account stamps the laptop's own push with the server's later clock and keeps the value to the millisecond), so a skip made while paused is kept. A second ⏯ while it waits cancels the resume. The thresholds live in `qml/lib/Catchup.js` (G3 finding 5). The reads, the waiting ⏯ and the note are `qml/CatchupFlow.qml`, a child of the service that `Service.playPause` asks; when a read finishes, `Catchup.finishRead` decides what is kept (only that read's own result, so a failed read of one book never clears another's) and whether the waiting ⏯ resumes (P9).

Fake mode keeps its own positions in its own tree: `position-push --fake` writes `{ms, updated_at}` (`updated_at` is the `--at` value) to `<fake data dir>/fake-account-positions.json`, and `position-get --fake` and `sync --fake` read it back, so the stale check and resume-from-the-account can be exercised with no account; real mode is unchanged and the file never exists in the real tree. `pushed.json` follows the same rule: fake mode writes it under the fake data dir.

"Recently listened" sort key = `max(local last_played_at, remote last_updated)`. Fetch remote positions for all catalog asins in batches during `sync` and cache them in `state.json`.

### 4.7 Auth and login ✅ (S1)
In-drawer login works (tested on the US store with a passkey sign-in; captcha, 2FA, and passkeys all happen in the user's browser, so the backend never sees them). The terminal fallback is not needed. Working code: `spikes/s1_login.py`.
- `login-start`: `audible.login.create_code_verifier()` and `build_oauth_url(country_code, domain, market_place_id, code_verifier)` → `(url, serial)`. No network call. Store `{verifier, serial, marketplace, created}` in `$XDG_RUNTIME_DIR/omarchy-audible/login-<id>.json` (0600, 10-minute TTL).
- `login-finish --session <id>`: **reads the pasted URL from stdin**, never argv (argv is visible to every local user in `/proc`). Extract `openid.oa2.authorization_code`, call `audible.register.register(authorization_code, code_verifier, domain, serial)`, build an `Authenticator` (`locale`, `_update_attrs(with_username=False, **reg)`), then **persist `auth.json`, `config.toml` and `account.json` first** — all `0600` (umask 077; `Authenticator.to_file` uses the umask) — and only **then** fetch the account-wide activation bytes, best effort (B13, F5). If that fetch fails the login still succeeds: the `done` event carries `{"warning":"activation_bytes"}`, only the exception type is logged, the device is **not** deregistered, and the advice is never "start the login again" (a retry registers another device) — `play-info` retries the fetch lazily at play time (below). Delete the session file on success and on failure. Drop the URL and code from memory as soon as they are used.
- **The activation bytes are lazy (B13).** They are only needed for a legacy aax book. `play-info` with a saved login fetches them once when the file is missing, writes it `0600`, and continues (§4.2); the aaxc and old-`.m4b` paths never call the network. The fetch is one call, only in real mode, and a failure is reported as `error(code=decrypt)` with a retry hint — never a key value, and never a request to sign in again.
- The UI opens the URL with `xdg-open` (never in fake mode, whose link is a dummy Amazon address) and offers a paste field plus "Paste from clipboard" (`wl-paste`). The sign-in state, these processes and the `login-*` handling are `qml/SigninFlow.qml`, a child of the service; the views keep calling the service, which forwards to it (P9). The pasted text goes from the view's field to `SigninFlow.finishLogin` as an argument and on to the backend's stdin, never into a property, argv or the event log.
- **Clipboard history is a leak path.** Omarchy's clipboard plugin saves every copied text to `~/.local/state/omarchy/clipboard-history.json` (mode 644), so the redirect URL lands there when the user copies it. After a successful `login-finish`, the backend checks that file for the code and, if it's there, returns `{"clipboard_history_contains_code": true}` in `done` so the UI can tell the user to clear it (Omarchy's clipboard menu). The plugin never edits the shell's file. The code is single-use and already redeemed, so the residual risk is low; the notice is about hygiene.
- `logout`: if the login was created by `login-finish`, call `deregister_device(deregister_all=False)` first (keeps Amazon's device list clean; best effort if offline), then delete the files. **If the login was imported, never deregister**: an imported auth file is the *same device* as the user's `~/.audible` login, and deregistering it would break their audible-cli. Record the origin (`"origin": "login"|"import"`) in a plugin-owned `account.json` next to `auth.json`; a missing or unknown origin means do not deregister. **Never** pass `deregister_all=True`.
- Never log or persist the pasted URL. A test asserts it appears in no log line, event, or file.

**The account label** in `status.account` comes from `account.json` when it holds one (a masked email such as `j***@gmail.com`). `login-finish` registers with `with_username=False`, so Amazon may return no email; `login-finish` and `login-import-cli` then fall back to the first name in the login's `customer_info` (`given_name`, then `name`) and store it in `account.json`. When `account.json` has no account, `status` reads the same `customer_info` from `auth.json` as plain JSON — no network and no `audible` import. A masked email always wins when there is one, and `user_id` is never used as the account label.

Existing-login import (`login-import-cli`) validates `~/.audible/<primary profile>.json` with `Authenticator.from_file`, then copies it and its marketplace into the plugin config dir, written `0600` **regardless of the source mode** (audible-cli leaves it 644). The copy is independent of audible-cli afterward ✅ S1.

### 4.8 Ownership contracts (G0)

**Files: one writer each.**

| File | Writer | Readers |
|---|---|---|
| `catalog.json`, covers | backend `sync` | Service/LibraryModel |
| `remote.json` | backend `sync`, `position-get` | Service/LibraryModel |
| `pushed.json` | backend `position-push` | backend `position-get`, `position-push` |
| `state.json` | `StateStore.qml` only (atomic `FileView` write) | Service; backend never reads it |
| `<booksDir>/<asin>/` | backend `get`, `remove` | LibraryModel (directory scan) |
| auth files | backend `login-*`, `logout` | backend |

`StateStore.qml` is the only `state.json` writer. It applies `qml/lib/Store.js` transitions for adoption, corrupt-file backup, pending-op replay and save decisions, while retaining `FileView`, backup `Process`, retry timers and synchronous shutdown flushing. `Store.step(state, event)` is pure; its `backup`, `write`, `save_now`, `retry_read`, `retry_backup` and `wait_file` effects are performed by the QML owner. After each transition, `publish()` copies the reducer state to the public properties in order, with `loaded` last so its reactions see the replayed document. Re-entrant events apply immediately. `save_now` applies a `save` event after the current transition, so nested queue or player-setting changes are serialized from the latest state; `flush` writes and waits before returning. `Library.js` still owns parsing and serialization, and `Playback.js` still owns position, finished, queue and player-setting document copies. The timestamp for a recorded operation is supplied by QML.

The merge rule (§4.6) runs in the service: it reads `state.json` and `remote.json` and picks the newest. The backend has a pure `merge()` helper with the unit tests (B6), and the QML port must match it.

**Jobs: one at a time, owned by the service.**
- `JobRunner.qml` is the only thing that spawns backend commands from the UI. It keeps a queue and runs one **job command** at a time.
- Job commands (`setup`, `sync`, `get`, `remove`, `login-finish`, `login-import-cli`, `logout`) take an exclusive `flock` on `job.lock` **without waiting**. If it is held they exit with `error(code=busy)`. That guards against a second shell, a hotkey, or a user running the CLI.
- Non-job commands never take the lock: `status`, `doctor`, `local`, `play-info`, `position-get`, `position-push`, `login-start`, and `cancel`. Pushes, status checks and `play-info` therefore work during a download.
- `books-location-ack` is also non-job. The user acknowledgement takes no arguments; the silent form may pass `--if-no-old-books`, which rechecks `old_books` immediately before writing and returns `done(acked:false)` without a write if books remain. Otherwise it returns `done(acked:true)`. In fake mode it writes under the fake data directory.
- `get` writes `job.json` `{pid, command, asin}` after taking the lock and removes it on exit. `cancel <asin>` reads `job.json`; it sends SIGTERM to that pid only when the asin matches, `job.lock` is held, and the pid is that book's `get`: `/proc/<pid>/cmdline` is a backend `get`, and the ASIN is in `/proc/<pid>/environ` as `OMARCHY_AUDIBLE_ASIN` (the shell's launch) or in its argv (a `get <asin>` typed by hand) (F41: a record left by a killed `get` names a pid that may since belong to anything); otherwise it returns `error(code=not_running)` and leaves the record to its owner (a new `get` may have just written it). The Library row's ✕ calls it for a running download and drops a queued one (UX1); a `cancelled` outcome is not shown as a failure. `get` handles SIGTERM by stopping its children, deleting `.partial/`, and emitting `error(code=cancelled)`; a second SIGTERM is ignored so it cannot abort that cleanup (F6). The UI can also just kill the process it spawned; both paths must clean up.

## 5. Player (QML)

### 5.1 mpv
Started by the service when a book is first played, as a detached process:
```
mpv --no-config --no-video --idle=yes --keep-open=yes --no-terminal --audio-display=no \
    --force-window=no --volume=<saved> --speed=<saved> \
    --input-ipc-server=$XDG_RUNTIME_DIR/omarchy-audible/mpv.sock [--script=<mpris_script>]
```
`<saved>` is `state.json`'s `volume` and `speed`, written a second after either changes (the volume from before a sleep fade, never the faded one) and range-checked on start (`Mpv.startVolume`, `Mpv.startSpeed`); without one, volume 100 (15 in fake mode) and speed 1. Until P8 (F21) neither was ever saved, so mpv always started at those defaults and this line did not match the code.
Launched as `systemd-run --user --scope --quiet --collect --unit=omarchy-audible-mpv mpv …` (fake mode: `--unit=omarchy-audible-fake-mpv`, so a fake player never blocks the real one; real mode stops a leftover fake scope when it starts, fake mode never touches the real one) through `Quickshell.execDetached` ✅ S5 (own cgroup, survives `omarchy-restart-shell`; the fixed unit name refuses a second mpv). A player that fails to start shows a desktop notification ("Couldn't start playback") and a line in Mini. Fall back to plain `execDetached` if `systemd-run` is missing. Never use `Process`, whose child dies with the shell. P2 must handle the pitfalls listed in SPIKE-RESULTS S5. When to probe, launch, connect, retry, give up, quit and relaunch is `PlayerMachine.step(state, event)` in `qml/lib/PlayerMachine.js` (P9); `PlayerController.qml` keeps the `Socket`, the processes, the timers and `execDetached`, and applies its effects (§5.2).

The service connects with Quickshell's unix-socket client (`Quickshell.Io` `Socket`) and speaks mpv's JSON IPC (`{"command":[…],"request_id":n}`; events as JSON lines). Observed properties: `time-pos`, `duration`, `pause`, `speed`, `chapter`, `chapter-list`, `path`, `idle-active`, `eof-reached`, `volume`.

Commands (B11 and R3: the first form is used only when there is no key, no chapters file and no title; since R3 the service always sends the catalog title, so every book from the drawer uses the second):
- `loadfile <path> replace 0 start=<seconds>` — no options.
- `loadfile <path> replace -1 {"start": "<s>", "demuxer-lavf-o": "<key options>", "chapters-file": "<chapters.txt>", "force-media-title": "<catalog title>"}` — mpv ≥ 0.38 takes the index argument **before** the options map (the desktop has mpv 0.41); `-1` means "no playlist index". Empty or absent options are left out of the map. `demuxer-lavf-o` carries the `play-info` value (`audible_key=…,audible_iv=…`, or `activation_bytes=…`), so the key travels over the IPC socket and never in mpv's argv. Once the file is loaded the service sends `set_property demuxer-lavf-o ""` so the key no longer sits in a readable property (S7).
- `set pause yes|no`, `seek ±N relative`, `seek <s> absolute`, `add chapter ±1`, `set chapter <i>`, `set speed <x>`.

### 5.2 PlayerController (QML object)
Exposes: `connection`, `lastError`, `connected`, `loaded`, `playing`, `positionMs`, `durationMs`, `chapters[]`, `chapterIndex`, `speed`, `volume`, `path`, `pendingLoad`, `restarts`, `sleepTimer`, the `userMoved` signal, and functions `play(path, startSec, options)`, `pause()`, `resume()`, `toggle()`, `skip(seconds)`, `seekMs()`, `jumpToMs()`, `setChapter()`, `nextChapter()`, `prevChapter()`, `setSpeed()`, `setVolume()`, `setSleepTimer()`, `setSleepEndOfChapter()`, `cancelSleep()`, `attach()`, `quit()`. The service maps an ASIN to a path; the player never sees an ASIN.

- Position persistence: write `state.json` every 10 s while playing and on pause/switch/quit; a move made while paused is written at the next stop, switch or quit (F38). `StateStore.qml` is the only writer, applies `Store.step` from `qml/lib/Store.js`, and uses `FileView` with atomic writes (§4.8).
- Remote push: every ~60 s while playing and on pause/stop/switch/quit, through `position-push`, following the push rules in §4.6. `PositionSync` applies the sequencing effects from `Sync.step(state, event)` in `qml/lib/Sync.js`; failed pushes remain queued in `state.json` and retry with the reducer's backoff.
- A load mpv cannot open (`end-file` with `reason: "error"` while `loadArrived` is false) is a failed play (F40): PlayerMachine's `load_failed` clears `wanted`, drops the load and sends `clear_key`; the controller emits `loadFailed(path)`, and Service reports it through `failPlay` (notification, play error) and returns to the Library.
- Finished detection: `eof-reached` or position ≥ duration − 30 s (`Positions.FINISH_TRAILING_MS`, its one home; `Playback.js` and `LibraryUi.js` import it) ⇒ mark finished and, if `autoRemoveFinished`, call `remove` (`qml/Removals.qml`). A loaded book is unloaded first and removed once mpv lets go, the same way as the user's Remove (F17). The pending-unload list is `qml/lib/Unload.js`'s reducer, and an auto-remove keeps its purpose after the unload: the event log says so, and it is cancelled if `autoRemoveFinished` is off by then (P8 nit 3).
- Sleep timer lives in QML (a `Timer`; "end of chapter" watches `chapter`). It pauses and fades over 5 s.
- Reattach: on service start, if the socket exists and answers, subscribe and restore state instead of spawning a new mpv (`PlayerMachine.step`: `attach`, `probe_result`, then `connected`).
- Connection machine (P9): `PlayerMachine.step(state, event)` in `qml/lib/PlayerMachine.js` is pure and returns the next state (`wanted`, `attaching`, `launching`, `quitting`, `quitPending`, `relaunchPending`, `scopeChecks`, `attempt`, `connection`, `lastError`, and `loadPending`, a flag) and its effects, documented at the top of the file. `PlayerController.apply` assigns that state once, `publish()` copies it to the public properties of the same names, then the effects run in order. An effect whose handlers call back in (a `Socket` that connects at once, a write that finds mpv gone and disconnects inside `send()`) is applied there and then, on top of the new state; nothing is queued. For that reason `quit()` is three steps (`quit`, then `quit_sent` with whether its `quit` went out, then `quit_closed` after the Socket is dropped), so a disconnect fired by one of its writes sees what it had set by then. The book's key never enters the machine: the load stays in `pendingLoad` (`Service.busyAsins` reads its path).

### 5.3 Book state machine (per ASIN, in `LibraryModel`)
```
cloud ──play/get──▶ queued ──▶ downloading ──▶ converting ──▶ local
  ▲                     │            │              │            │
  │                     └────────────┴──── error ◀──┘            │
  └────────────────────────── remove ◀───────────────────────────┘
```
`local` is derived from the filesystem scan. `queued/downloading/converting/error` are in-memory job state. Exactly one job runs at a time.

## 6. UI

The bar widget owns a `qs.Ui` `KeyboardPanel` anchored under the book icon (✅ S6), hosting a `StackLayout` of the views. Full view grows the same drawer; there is no separate window and no `panel` manifest kind (a `panel` kind would make `omarchy-shell shell summon` open a second, unanchored surface). Bar widgets exist once per monitor, so all UI and player state lives in `Service.qml`; widgets are views that register with the service. View rules:
- Select a book in Library → hide the panel, start playback, and reopen on the **Mini** view when playback begins (so the user sees it work).
- ✕ / Esc / click-away → hide the panel; audio continues.
- Bar click → **Mini** if a book is loaded, otherwise **Library**.
- Mini has a library button (→ Library) and a maximize button (→ Full). Full has the same library button (U8) and a collapse button (→ Mini).
- Stop in Mini or Full ends playback through `Service.quitPlayer`; an open Mini or Full panel returns to Library after a true unload, while a switch or reconnect that temporarily clears the path preserves the current view. A closed panel stays closed. The bar glyph follows `player.loaded` and returns to the book.
- Onboarding view replaces Library when `status.authenticated` is false or setup is incomplete. The step and the Connect phase come from `qml/SigninFlow.qml` through the service's `onboardingStep` and `loginPhase` (P9).
- A loaded catalog stays listed after sync errors; Reconnect outranks the connection-problem banner, which appears for unexpected sync failures and runs `doctor` only after such a failed sync, while a catalog that has not loaded shows the full connection diagnostic state.

Manifest settings are declared under `barWidget.schema` and their defaults under `barWidget.defaults`. Values are plain JSON keys on the plugin's `bar.layout.<section>` entry in `~/.config/omarchy/shell.json`. Each live widget passes its injected `settings` object to `Service.applySettings`; `qml/lib/Settings.js` validates values and supplies defaults, and Service owns the effective setting properties read by the views and library. The widget forwards settings only after the shell injects its `moduleName`, so the base-class default `{}` never reaches Service. The shell updates the widget's `settings` property in place when the bar layout entry changes, so saving shell.json applies settings without restarting the shell. A changed `booksDir` is passed to each newly started backend command and causes a fresh `status`/local scan; a running download finishes in its starting folder, and a loaded book keeps playing from its open file. The backend alone validates the path and returns the default with `books_dir_problem` when invalid. On status, `old_books` reports books found in the last acknowledged folder (or the default folder when no record exists); the UI asks the user to acknowledge the notice, and nothing moves automatically. An empty old folder is acknowledged silently. Omarchy 4.0.4 has no settings UI that renders `barWidget.schema`. With no widget instance, Service keeps the library defaults and does not record or apply a default-speed marker. `autoRemoveFinished` IPC remains a fake-mode development override; a later settings apply, widget creation or rebuild, or store load can set it from shell.json again (last write wins).

Keyboard: search field focused on open; ↑/↓ move; Enter plays the selected row, or the first match once something is typed (with nothing selected or typed it does nothing, so a stray Enter cannot start a download); Esc close; Space play/pause when the search field is empty; ←/→ skip in Mini/Full; Backspace in Full collapses to Mini. In the Mini chapter popup, ↑/↓ move, Enter jumps to the chapter and Esc closes only the popup. Player and store state live in service-owned child objects (`PlayerController.qml` and `StateStore.qml`, whose decisions are `PlayerMachine.step` and `Store.step`); views continue to use the service-facing names.

Shell IPC target `latentoperator.audible`, registered by the one `IpcHandler`, in `qml/ServiceIpc.qml`, which `Service.qml` declares once as its child (P9; a handler in the per-monitor widget would be ignored as a duplicate) ✅ S6:
`toggle`, `playPause`, `skip <seconds>`, `nextChapter`, `prevChapter`, `openLibrary`, `stop`. Arguments and return values are strings. `stop` returns `error: nothing loaded` only if no book is loaded or wanted and no load, resume, or play-info request is pending; otherwise it uses `Service.quitPlayer` to clear pending playback, the play error and persist player settings. `PlayerMachine.step` sets `wanted` on play, clears it on quit, when retries give up and when the relaunch's scope wait gives up ("the previous mpv did not exit"), and publishes it through `PlayerController.publish()`.
Call syntax ✅: `omarchy-shell latentoperator.audible toggle`. Example Hyprland binding (Omarchy 4, `~/.config/hypr/bindings.lua`): `o.bind("SUPER + ALT + A", "Audible", "omarchy-shell latentoperator.audible toggle")`.

Which methods work in real mode (H1 F27) is listed in `qml/lib/Ipc.js`, and a test checks `qml/ServiceIpc.qml` against it:
- **Public**, for keybindings and users: the seven above.
- **Status**, read-only, kept so a session can confirm the mode and that the service is attached: `playerStatus`, `libraryState`, `onboardingState`, `panelState`, `pushState`, `events`.
- **Test-only**, everything else (`play`, `pause`, `quitPlayer`, `removeBook`, `syncNow`, `libraryQuery`, `view`, …): each returns `error: dev only` unless the dev-fake flag was present when the service loaded. `libraryQuery` computes its rows from a copy (`Library.queryRows`) and never changes the drawer's sort, filter or search.

## 7. Media keys / MPRIS (optional, M5)
mpv does not export MPRIS by itself. `status` checks `/usr/lib/mpv-mpris/mpris.so`, `/etc/mpv/scripts/mpris.so`, then `$XDG_CONFIG_HOME/mpv/scripts/mpris.so` (default `~/.config/mpv/scripts/mpris.so`). When found, a new player receives `--script=<path>`; the script is never required and existing mpv processes are not relaunched to add it. `doctor` reports it as an optional check whose `ok` is always true. mpv-mpris 1.2 names the bus after `audio-client-name`: the first mpv takes `org.mpris.MediaPlayer2.mpv` and a later one (e.g. a fake player beside a real one) gets `org.mpris.MediaPlayer2.mpv.instance-<random>`.

With `mpv-mpris` installed, MPRIS clients (media keys, `playerctl`, KDE Connect) can control play/pause, seek and Stop; Omarchy 4.0.4's Media bar widget offers play/pause, next and previous only. Next/Previous remain mpv playlist commands and do not navigate audiobook chapters. Catalog title is sent as `force-media-title` in each load's options so the MPRIS title is useful; author is not overridden. mpv-mpris 1.2 reads `mpris:artUrl` from mpv's embedded cover or recognized artwork beside the audio file; this plugin's cached cover is stored elsewhere, so it is not wired as MPRIS art. An MPRIS pause follows the ordinary pause path and saves/pushes the position. Resuming through MPRIS does not run the UI's long-pause catch-up read; the next position push remains protected by the existing stale-position rules. MPRIS Stop unloads mpv's file while leaving its process connected; for a book this shell started, the controller treats that unload as Stop (`PlayerController.externalUnload`, `Playback.externalUnload`): it saves and pushes once, clears the wanted book, and exits the player through the normal cleanup. Any other unload of a wanted, loaded book that we did not ask for takes the same path: mpv-mpris `OpenUri` (a `loadfile`) and a mid-playback `end-file` error. An mpv reattached after a shell restart is not `wanted` (only a play sets that), so an MPRIS Stop there saves and pushes through the ordinary pause/switch path and returns to Library, but leaves the idle mpv running; the next play reuses it. A paused seek through MPRIS is not marked as a user move and can be lost on a later Stop; see R3's manual record.

## 8. Testing strategy

| Layer | How |
|-------|-----|
| Backend unit | `pytest`, no network. Fixtures in `fixtures/` (synthetic catalog JSON, fake `audible` responses). |
| Backend pipeline | `--fake` mode: ffmpeg-generated sine served as `book.aaxc` (with a fake key) or `book.aax`, plus `chapters.txt`; assert atomicity, cleanup on failure, `remove` path safety, the free-space check, and that no argv carries key material. |
| Protocol contract | JSON-schema per event type in `tests/schemas/`; both fake and real backends are validated against them. |
| QML | Run inside the real shell with the repo symlinked and `OMARCHY_AUDIBLE_FAKE=1`. A `docs/MANUAL-TEST.md` checklist covers J1–J7 and three themes. |
| Real account | A short manual checklist run by the maintainer before each release. Not automated. |

Never commit real library data, auth files, or activation bytes. Fixtures use invented titles.

## 9. Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Audible changes API/DRM | Plugin stops syncing or downloading | Pin `audible-cli`; `doctor`; clear error UI; fast-follow releases |
| Programmatic login breaks (Amazon changes the flow) | In-drawer login fails | ✅ S1 works today. Fallback: the drawer shows a one-line `audible quickstart`-style command, plus import of an existing audible-cli login |
| `.aaxc` books need a different decrypt path | Some books fail | ✅ S2 proved both paths; aaxc first, aax fallback |
| A wrong position push | The phone silently jumps (it has undo) | §4.6 push rules: only push local listening, never older than remote |
| Pasted login URL lingers in clipboard history | Single-use code readable locally | §4.7: detect it and tell the user |
| Quickshell `Socket`/detached-process API limits | Player design changes | Spike S5 early. Fallback: a tiny helper script that owns mpv and exposes a simpler stdio protocol |
| Third-party plugin capability facades block something needed | UI limits | Spike S6; follow the Spotify plugin, which solves the same problems |
| AGPL dependency licensing | Distribution problems | D1: the plugin is AGPL-3.0-only, matching `audible`. Dependencies are still installed at runtime from PyPI, never vendored |

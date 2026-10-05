# Architecture — Omarchy Audible

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
                                    │  `audible` lib /      ffmpeg (decrypt → m4b)
                                    │  `audible-cli`
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
  Service.qml                        singleton logic, mpv + backend control, IPC target
  BarWidget.qml                      the book icon + the KeyboardPanel drawer hosting the views
  qml/
    LibraryView.qml  MiniView.qml  FullView.qml  OnboardingView.qml
    BookRow.qml  ChapterList.qml  ScrubBar.qml  Cover.qml  StateBadge.qml
    PlayerController.qml  LibraryModel.qml  JobRunner.qml  Format.js
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
| `~/.local/share/omarchy-audible/state.json` | Local positions, last-played times, push queue. **Written only by `Service.qml`** | |
| `~/.local/share/omarchy-audible/covers/<asin>.jpg` | Cover thumbnails | |
| `<booksDir>/<asin>/book.m4b` | Decrypted audio, chapters embedded | |
| `<booksDir>/<asin>/meta.json` | Title, author, duration, size, downloaded_at | |
| `$XDG_RUNTIME_DIR/omarchy-audible/mpv.sock` | mpv IPC socket | |
| `$XDG_RUNTIME_DIR/omarchy-audible/job.lock` | Exclusive lock held by the running job command (§4.8) | |
| `$XDG_RUNTIME_DIR/omarchy-audible/job.json` | `{pid, command, asin}` of the running job, for `cancel` | |
| `$XDG_RUNTIME_DIR/omarchy-audible/login-<id>.json` | Login session `{verifier, serial, marketplace, created}`, 10-minute TTL, tmpfs | 0600 | |

Books are keyed by **ASIN directory**, not by title. That makes removal a single `rm -r` of one directory, avoids filename-encoding problems, and makes "what is local?" a directory scan. The filesystem is the source of truth for "is this book local".

`state.json` (schema v1, written **only** by `Service.qml`, §4.8; parsed and serialized by `qml/lib/Library.js`):

```json
{ "schema": 1,
  "books": { "<asin>": { "ms": 0, "updated_at": null, "last_played_at": null,
                         "played_since_download": false, "finished": false } },
  "push_queue": [ { "asin": "<asin>", "ms": 0, "at": null } ],
  "volume": null, "speed": null }
```

- `ms` is the local position; `updated_at` is when it was written. The newest-wins merge (§4.6) chooses between this entry and `remote.json`.
- `last_played_at` is the "recently listened" key (§4.6); `played_since_download` gates position write-back; `finished` is the local finished flag.
- `push_queue` holds pending position write-backs, `at` being the local listening time (§4.6).
- Unknown keys are kept across a parse/serialize round trip. A missing file, garbage, or a `schema` other than 1 recovers to an empty v1; `parseState` reports that with a `recovered` flag (which is not part of the file) so the service can start over.

The audible-cli profile is created programmatically in a plugin-owned config dir by setting `AUDIBLE_CONFIG_DIR` for every backend subprocess, so it never touches or conflicts with a user's own `~/.audible`.

## 4. Backend

### 4.1 Launcher and bootstrap
`bin/omarchy-audible` uses **only the Python standard library** so it runs on a fresh machine. It:
1. Handles `status`, `doctor`, and `setup` itself (these must work before any dependency exists).
2. For everything else, re-execs `venv/bin/python -m omarchy_audible …`.
3. `setup` creates the venv with `python -m venv`, then `pip install` of the pinned `audible-cli` and `audible[cryptography]` (without the extra, `audible` warns on stderr about legacy crypto) **and of this repo's `backend/` package**, so that `venv/bin/python -m omarchy_audible` resolves. Progress is streamed as events.

The shell's plugin installer never runs plugin code, so the first-run Setup button in the drawer triggers `setup`. System packages the backend needs but cannot install: `mpv`, `ffmpeg`, `python`. `status` reports what is missing and the exact `pacman`/`omarchy-pkg-add` command to fix it.

### 4.2 Protocol
Every subcommand writes **one JSON object per line (NDJSON)** to stdout and exits 0 on success, nonzero on failure. Human logs go to stderr and are scrubbed of secrets. Every event has a `type`; the last event of a successful run is `{"type":"done"}`; on failure it is `{"type":"error","code":"…","message":"…","hint":"…"}`.

```
status                      → {"type":"status","ready":bool,"missing":["mpv"],"authenticated":bool,
                                "marketplace":"us","account":"j***@gmail.com","catalog_age_s":1234}
setup                       → progress events, then done
login-start --marketplace us→ {"type":"login_url","url":"https://www.amazon.com/ap/signin?…","session":"<id>"}
login-finish --session <id>  (pasted URL on stdin) → done | error(code=bad_url|expired|auth_failed)
login-import-cli [--dir ~/.audible]          → done | error(code=no_auth_file)
logout                      → done (deregisters this device only, then deletes auth.json, activation_bytes, config.toml; keeps books)
sync [--full]               → progress {"type":"progress","stage":"library","n":40,"of":91}, then done
                              (writes catalog.json atomically, fetches missing covers)
get <asin>                  → {"type":"progress","stage":"download|convert","bytes":123,"total":456}
                              … then {"type":"done","path":".../book.m4b"}
cancel <asin>               → done | error(code=not_running)   (signals the running `get`, see §4.8)
remove <asin>               → {"type":"done","freed_bytes":N}      (LOCAL ONLY — see §4.4)
local                       → {"type":"local","books":[{"asin":…,"size":N,"downloaded_at":…}]}
position-get <asin…>        → {"type":"positions","items":{"<asin>":{"ms":N,"updated_at":"…"|null}}}
position-push <asin> <ms>   → done | error(code=unsupported|network)
doctor                      → {"type":"doctor","checks":[{"name":…,"ok":bool,"detail":…}]}
```

`--fake` (or env `OMARCHY_AUDIBLE_FAKE=1`) runs the same protocol against `fixtures/` with no network and no account. This lets UI work and tests proceed without credentials, and is what CI runs. Fake `get` produces a short synthetic m4b with chapters using `ffmpeg -f lavfi` and simulates progress and failures (`--fake-fail <code>`).

### 4.3 Download and decrypt pipeline ✅ (S2)
Verified manually:
- `audible download --asin <ASIN> --aax-fallback --cover --chapter -y -o <dir>` produced `*.aax` (264 MB for a 9-hour book, ~18 s), a 500px cover, and a chapters JSON.
- `audible activation-bytes` returned the 8-hex-character account key.
- `ffmpeg -activation_bytes <hex> -i book.aax -c copy book.m4b` is a lossless stream copy, **preserved all 20 chapters**, and ran in a few seconds. ffmpeg prints `Application provided duration … in stream 2 is invalid` warnings for the embedded cover stream; they are harmless.

Pipeline for `get <asin>`:
1. Pre-flight: content metadata gives `content_size_in_bytes` before download; require ≥ 2.1× that in free space (S2 measured a 2.0× peak).
2. Create `<booksDir>/<asin>/.partial/`.
3. Download via `audible-cli` with `--aaxc --chapter -q best`, no progress bars. **Prefer aaxc; if no voucher is offered, retry with `--aax`** (G0 decision). Note that audible-cli's own `--aax-fallback` goes the other way (aax first), so don't use it. Report progress by polling the partial file size.
4. Decrypt: `.aaxc` uses the voucher `content_license.license_response.key`/`.iv` (`-audible_key`, `-audible_iv`); `.aax` uses `-activation_bytes` ✅ S2 proved both paths. ffmpeg offers no other input for the aaxc key/iv, so they are passed as argv and are visible to same-user processes in `/proc/<pid>/cmdline` for the few seconds the conversion runs; that is accepted.
5. **Chapters come from Audible's list, not the file** (G0 decision; one book had 20 embedded chapters vs 46 in the API). Build an ffmetadata chapter file from `<ASIN>-chapters.json` (flat) and apply it in the same `-c copy` pass (`-i chapters.txt -map_metadata 1 -map_chapters 1`). Fall back to the embedded chapters if the JSON is missing. Write to `book.m4b.tmp`, then `ffprobe` sanity check (duration within 1% of catalog runtime; chapter count equals the flat list), then atomic rename to `book.m4b`.
6. Write `meta.json`, delete `.partial/` and the raw `.aax`/`.aaxc` (**the raw file is never kept**).
7. On failure or cancel at any step, delete `.partial/` and emit `error`.

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
- Push only positions produced by **listening on this machine**: on pause, stop, book switch, quit, and every ~60 s while playing.
- Never push from `sync`, from the merge, or for a book not played locally since it was downloaded.
- Never push a position older than the remote `updated_at` (the user listened elsewhere since). Re-read the remote position immediately before a push.

`last_updated` has no timezone (`YYYY-MM-DD HH:MM:SS.f`). It looks like UTC; B6 confirms against a write at a known time.

Merge rule: take the entry with the newest `updated_at` between local `state.json` and remote. If remote is newer, resume there (the user listened elsewhere).

"Recently listened" sort key = `max(local last_played_at, remote last_updated)`. Fetch remote positions for all catalog asins in batches during `sync` and cache them in `state.json`.

### 4.7 Auth and login ✅ (S1)
In-drawer login works (tested on the US store with a passkey sign-in; captcha, 2FA, and passkeys all happen in the user's browser, so the backend never sees them). The terminal fallback is not needed. Working code: `spikes/s1_login.py`.
- `login-start`: `audible.login.create_code_verifier()` and `build_oauth_url(country_code, domain, market_place_id, code_verifier)` → `(url, serial)`. No network call. Store `{verifier, serial, marketplace, created}` in `$XDG_RUNTIME_DIR/omarchy-audible/login-<id>.json` (0600, 10-minute TTL).
- `login-finish --session <id>`: **reads the pasted URL from stdin**, never argv (argv is visible to every local user in `/proc`). Extract `openid.oa2.authorization_code`, call `audible.register.register(authorization_code, code_verifier, domain, serial)`, build an `Authenticator` (`locale`, `_update_attrs(with_username=False, **reg)`), fetch activation bytes, and write `auth.json`, `activation_bytes`, and `config.toml` created `0600` (umask 077; `Authenticator.to_file` uses the umask). Delete the session file on success and on failure. Drop the URL and code from memory as soon as they are used.
- The UI opens the URL with `xdg-open` and offers a paste field plus "Paste from clipboard" (`wl-paste`).
- **Clipboard history is a leak path.** Omarchy's clipboard plugin saves every copied text to `~/.local/state/omarchy/clipboard-history.json` (mode 644), so the redirect URL lands there when the user copies it. After a successful `login-finish`, the backend checks that file for the code and, if it's there, returns `{"clipboard_history_contains_code": true}` in `done` so the UI can tell the user to clear it (Omarchy's clipboard menu). The plugin never edits the shell's file. The code is single-use and already redeemed, so the residual risk is low; the notice is about hygiene.
- `logout`: if the login was created by `login-finish`, call `deregister_device(deregister_all=False)` first (keeps Amazon's device list clean; best effort if offline), then delete the files. **If the login was imported, never deregister**: an imported auth file is the *same device* as the user's `~/.audible` login, and deregistering it would break their audible-cli. Record the origin (`"origin": "login"|"import"`) in a plugin-owned `account.json` next to `auth.json`; a missing or unknown origin means do not deregister. **Never** pass `deregister_all=True`.
- Never log or persist the pasted URL. A test asserts it appears in no log line, event, or file.

Existing-login import (`login-import-cli`) validates `~/.audible/<primary profile>.json` with `Authenticator.from_file`, then copies it and its marketplace into the plugin config dir, written `0600` **regardless of the source mode** (audible-cli leaves it 644). The copy is independent of audible-cli afterward ✅ S1.

### 4.8 Ownership contracts (G0)

**Files: one writer each.**

| File | Writer | Readers |
|---|---|---|
| `catalog.json`, covers | backend `sync` | Service/LibraryModel |
| `remote.json` | backend `sync`, `position-get` | Service/LibraryModel |
| `state.json` | `Service.qml` only (atomic `FileView` write) | Service; backend never reads it |
| `<booksDir>/<asin>/` | backend `get`, `remove` | LibraryModel (directory scan) |
| auth files | backend `login-*`, `logout` | backend |

The merge rule (§4.6) runs in the service: it reads `state.json` and `remote.json` and picks the newest. The backend has a pure `merge()` helper with the unit tests (B6), and the QML port must match it.

**Jobs: one at a time, owned by the service.**
- `JobRunner.qml` is the only thing that spawns backend commands from the UI. It keeps a queue and runs one **job command** at a time.
- Job commands (`setup`, `sync`, `get`, `remove`, `login-finish`, `login-import-cli`, `logout`) take an exclusive `flock` on `job.lock` **without waiting**. If it is held they exit with `error(code=busy)`. That guards against a second shell, a hotkey, or a user running the CLI.
- Non-job commands never take the lock: `status`, `doctor`, `local`, `position-get`, `position-push`, `login-start`, and `cancel`. Pushes and status checks therefore work during a download.
- `get` writes `job.json` `{pid, command, asin}` after taking the lock and removes it on exit. `cancel <asin>` reads `job.json`; if the asin matches it sends SIGTERM to that pid, otherwise `error(code=not_running)`. `get` handles SIGTERM by stopping its children, deleting `.partial/`, and emitting `error(code=cancelled)`. The UI can also just kill the process it spawned; both paths must clean up.

## 5. Player (QML)

### 5.1 mpv
Started by the service when a book is first played, as a detached process:
```
mpv --no-config --no-video --idle=yes --keep-open=yes --no-terminal --audio-display=no \
    --input-ipc-server=$XDG_RUNTIME_DIR/omarchy-audible/mpv.sock \
    --force-window=no --volume=<saved> --speed=<default>
```
Launched as `systemd-run --user --scope --quiet --collect --unit=omarchy-audible-mpv mpv …` through `Quickshell.execDetached` ✅ S5 (own cgroup, survives `omarchy-restart-shell`; the fixed unit name refuses a second mpv). Fall back to plain `execDetached` if `systemd-run` is missing. Never use `Process`, whose child dies with the shell. P2 must handle the pitfalls listed in SPIKE-RESULTS S5.

The service connects with Quickshell's unix-socket client (`Quickshell.Io` `Socket`) and speaks mpv's JSON IPC (`{"command":[…],"request_id":n}`; events as JSON lines). Observed properties: `time-pos`, `duration`, `pause`, `speed`, `chapter`, `chapter-list`, `path`, `idle-active`, `eof-reached`, `volume`.

Commands: `loadfile <path> replace 0 start=<seconds>`, `set pause yes|no`, `seek ±N relative`, `seek <s> absolute`, `add chapter ±1`, `set chapter <i>`, `set speed <x>`.

### 5.2 PlayerController (QML object)
Exposes: `loaded`, `playing`, `positionMs`, `durationMs`, `chapters[]`, `chapterIndex`, `speed`, `asin`, and functions `play(asin)`, `pause()`, `toggle()`, `skip(seconds)`, `nextChapter()`, `prevChapter()`, `seekMs()`, `setSpeed()`, `setSleepTimer()`.

- Position persistence: write `state.json` every 10 s while playing and on pause/switch/quit. The service is the only writer, using `FileView` with atomic writes (§4.8).
- Remote push: every ~60 s while playing and on pause/stop/switch/quit, through `position-push`, following the push rules in §4.6. Failed pushes are queued in `state.json` and retried.
- Finished detection: `eof-reached` or position ≥ duration − 30 s ⇒ mark finished and, if `autoRemoveFinished`, call `remove`.
- Sleep timer lives in QML (a `Timer`; "end of chapter" watches `chapter`). It pauses and fades over 5 s.
- Reattach: on service start, if the socket exists and answers, subscribe and restore state instead of spawning a new mpv.

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
- Mini has a library button (→ Library) and a maximize button (→ Full). Full has a collapse button (→ Mini).
- Onboarding view replaces Library when `status.authenticated` is false or setup is incomplete.

Keyboard: search field focused on open; ↑/↓ move; Enter play; Esc close; Space play/pause when the search field is empty; ←/→ skip in Mini/Full.

Shell IPC target `latentoperator.audible`, registered by an `IpcHandler` in `Service.qml` (a handler in the per-monitor widget would be ignored as a duplicate) ✅ S6:
`toggle`, `playPause`, `skip <seconds>`, `nextChapter`, `prevChapter`, `openLibrary`. Arguments and return values are strings.
Call syntax ✅: `omarchy-shell latentoperator.audible toggle`. Example Hyprland binding: `bind = SUPER, A, exec, omarchy-shell latentoperator.audible toggle`.

## 7. Media keys / MPRIS (optional, M5)
mpv does not export MPRIS by itself. The AUR/Arch package `mpv-mpris` provides it, which would make hardware media keys, `playerctl`, and Omarchy's stock media widget see the book. Make it **optional**: if the script is installed, pass it to mpv with `--script=`; otherwise skip. Do not make it a hard dependency.

## 8. Testing strategy

| Layer | How |
|-------|-----|
| Backend unit | `pytest`, no network. Fixtures in `fixtures/` (synthetic catalog JSON, fake `audible` responses). |
| Backend pipeline | `--fake` mode: ffmpeg-generated sine-wave m4b with 3 chapters; assert atomicity, cleanup on failure, `remove` path safety, free-space check. |
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

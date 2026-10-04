# Architecture — Omarchy Audible

Companion to [SCOPE.md](SCOPE.md). Facts marked ✅ were verified by hand on 2026-10-04 on an Omarchy machine with a real Audible account. Facts marked ❓ are assumptions that a spike in [PLAN.md](PLAN.md) must confirm before building on them.

## 1. Big picture

```
 Bar ── BarWidget.qml ──click──▶ Panel.qml   (views: Library | Mini | Full)
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

A plugin is a git repo with `manifest.json` at its root. Users install with `omarchy plugin add <git-url>`. Developers symlink the repo into `~/.config/omarchy/plugins/latentoperator.audible/`. Saving a file there hot-reloads it.

```
omarchy-audible/                     (repo root == plugin root)
  manifest.json                      kinds: service, bar-widget, panel
  Service.qml                        singleton logic, mpv + backend control, IPC target
  BarWidget.qml                      the book icon
  Panel.qml                          hosts the three views
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

Theming rule: import `qs.Commons` and `qs.Ui` and use `Style`/theme tokens only. Never hard-code a color.

## 3. On-disk layout

| Path | Contents | Mode |
|------|----------|------|
| `~/.config/omarchy-audible/auth.json` | Audible auth (device key, tokens) | 0600 |
| `~/.config/omarchy-audible/activation_bytes` | Account-wide decrypt key for legacy AAX | 0600 |
| `~/.config/omarchy-audible/config.toml` | audible-cli profile pointing at `auth.json` (generated) | 0600 |
| `~/.local/share/omarchy-audible/venv/` | Python venv with `audible-cli` (pinned) | |
| `~/.local/share/omarchy-audible/catalog.json` | Library metadata cache | |
| `~/.local/share/omarchy-audible/state.json` | Positions, last-played times, sync queue | |
| `~/.local/share/omarchy-audible/covers/<asin>.jpg` | Cover thumbnails | |
| `<booksDir>/<asin>/book.m4b` | Decrypted audio, chapters embedded | |
| `<booksDir>/<asin>/meta.json` | Title, author, duration, size, downloaded_at | |
| `$XDG_RUNTIME_DIR/omarchy-audible/mpv.sock` | mpv IPC socket | |
| `$XDG_RUNTIME_DIR/omarchy-audible/backend.lock` | Single-instance lock | |

Books are keyed by **ASIN directory**, not by title. That makes removal a single `rm -r` of one directory, avoids filename-encoding problems, and makes "what is local?" a directory scan. The filesystem is the source of truth for "is this book local".

The audible-cli profile is created programmatically in a plugin-owned config dir by setting `AUDIBLE_CONFIG_DIR` for every backend subprocess, so it never touches or conflicts with a user's own `~/.audible`.

## 4. Backend

### 4.1 Launcher and bootstrap
`bin/omarchy-audible` uses **only the Python standard library** so it runs on a fresh machine. It:
1. Handles `status`, `doctor`, and `setup` itself (these must work before any dependency exists).
2. For everything else, re-execs `venv/bin/python -m omarchy_audible …`.
3. `setup` creates the venv with `python -m venv`, then `pip install` of pinned `audible-cli` (which brings the `audible` library), streaming progress events.

The shell's plugin installer never runs plugin code, so the first-run Setup button in the drawer triggers `setup`. System packages the backend needs but cannot install: `mpv`, `ffmpeg`, `python`. `status` reports what is missing and the exact `pacman`/`omarchy-pkg-add` command to fix it.

### 4.2 Protocol
Every subcommand writes **one JSON object per line (NDJSON)** to stdout and exits 0 on success, nonzero on failure. Human logs go to stderr and are scrubbed of secrets. Every event has a `type`; the last event of a successful run is `{"type":"done"}`; on failure it is `{"type":"error","code":"…","message":"…","hint":"…"}`.

```
status                      → {"type":"status","ready":bool,"missing":["mpv"],"authenticated":bool,
                                "marketplace":"us","account":"j***@gmail.com","catalog_age_s":1234}
setup                       → progress events, then done
login-start --marketplace us→ {"type":"login_url","url":"https://www.amazon.com/ap/signin?…","session":"<id>"}
login-finish --session <id> --url <pasted>   → done | error(code=bad_url|expired|auth_failed)
login-import-cli [--dir ~/.audible]          → done | error(code=no_auth_file)
logout                      → done (deletes auth.json, activation_bytes, config.toml; keeps books)
sync [--full]               → progress {"type":"progress","stage":"library","n":40,"of":91}, then done
                              (writes catalog.json atomically, fetches missing covers)
get <asin>                  → {"type":"progress","stage":"download|convert","bytes":123,"total":456}
                              … then {"type":"done","path":".../book.m4b"}
cancel <asin>               → done
remove <asin>               → {"type":"done","freed_bytes":N}      (LOCAL ONLY — see §4.4)
local                       → {"type":"local","books":[{"asin":…,"size":N,"downloaded_at":…}]}
position-get <asin…>        → {"type":"positions","items":{"<asin>":{"ms":N,"updated_at":"…"|null}}}
position-push <asin> <ms>   → done | error(code=unsupported|network)
doctor                      → {"type":"doctor","checks":[{"name":…,"ok":bool,"detail":…}]}
```

`--fake` (or env `OMARCHY_AUDIBLE_FAKE=1`) runs the same protocol against `fixtures/` with no network and no account. This lets UI work and tests proceed without credentials, and is what CI runs. Fake `get` produces a short synthetic m4b with chapters using `ffmpeg -f lavfi` and simulates progress and failures (`--fake-fail <code>`).

### 4.3 Download and decrypt pipeline ✅
Verified manually:
- `audible download --asin <ASIN> --aax-fallback --cover --chapter -y -o <dir>` produced `*.aax` (264 MB for a 9-hour book, ~18 s), a 500px cover, and a chapters JSON.
- `audible activation-bytes` returned the 8-hex-character account key.
- `ffmpeg -activation_bytes <hex> -i book.aax -c copy book.m4b` is a lossless stream copy, **preserved all 20 chapters**, and ran in a few seconds. ffmpeg prints `Application provided duration … in stream 2 is invalid` warnings for the embedded cover stream; they are harmless.

Pipeline for `get <asin>`:
1. Pre-flight: free-space check (need ≈ 2.2× the expected size during conversion).
2. Create `<booksDir>/<asin>/.partial/`.
3. Download via `audible-cli` (`--aax-fallback`), no progress bars. Report progress by polling the partial file size.
4. Decrypt: `.aax` uses `-activation_bytes`; `.aaxc` uses the voucher `key`/`iv` (`-audible_key`, `-audible_iv`) ❓ spike S2 must prove the aaxc path with a book that is not offered as aax.
5. `ffmpeg -c copy` to `book.m4b.tmp`, then `ffprobe` sanity check (duration within 1% of catalog runtime; chapters present), then atomic rename to `book.m4b`.
6. Write `meta.json`, delete `.partial/` and the raw `.aax`/`.aaxc` (**the raw file is never kept**).
7. On failure or cancel at any step, delete `.partial/` and emit `error`.

### 4.4 Removal safety (hard requirement)
`remove <asin>` only deletes `<booksDir>/<asin>/`. It must verify the resolved path is inside `booksDir` and refuse otherwise. The backend has no code path that calls an Audible endpoint with a mutating method except position write-back (§4.6). A test greps the package for `delete`, `remove`, and `return` calls to the API and fails if any is found.

### 4.5 Catalog ✅ / ❓
`audible library export --format json` ✅ returned 91 items with: `asin`, `title`, `authors`, `narrators`, `genres`, `cover_url`, `runtime_length_min`, `date_added`, `purchase_date`, `release_date`, `rating`, `is_finished`, `percent_complete`.

Missing from the export and needed by the UI: **subtitle, series name and part number, content type (to hide podcasts), content delivery type (multi-part)**. These are in the raw `1.0/library` endpoint with extra `response_groups` ❓ spike S4 chooses the groups. Note: the raw call with a large response group list **timed out**; request `product_desc,media,contributors,series,product_attrs,listening_status,percent_complete,is_finished` with `num_results` ≤ 50 and page.

`catalog.json` (written atomically, `schema` versioned):
```json
{ "schema": 1, "synced_at": "2026-10-04T12:00:00Z", "marketplace": "us",
  "books": [ { "asin": "…", "title": "…", "subtitle": null, "authors": ["…"], "narrators": ["…"],
               "series": {"name": "…", "part": "2"}, "cover": "covers/<asin>.jpg",
               "runtime_min": 540, "date_added": "…", "percent_complete": 12.5,
               "is_finished": false, "multipart": false } ] }
```

### 4.6 Positions
Read ✅: `audible api 1.0/annotations/lastpositions -p asins=A,B` returns, per asin, `last_position_heard` with `status` (`Exists`|`DoesNotExist`), `position_ms`, `last_updated`. It accepted two asins in one call; confirm the per-call maximum ❓ (batch at ≤50).

Write ❓ (spike S3): the community-known endpoint needs an `acr` value obtained from a content-license request. If the write cannot be made reliable, v1 ships read-only sync (resume from the phone's position) plus local positions, and `position-push` returns `error(code=unsupported)`.

Merge rule: take the entry with the newest `updated_at` between local `state.json` and remote. If remote is newer, resume there (the user listened elsewhere).

"Recently listened" sort key = `max(local last_played_at, remote last_updated)`. Fetch remote positions for all catalog asins in batches during `sync` and cache them in `state.json`.

### 4.7 Auth and login ❓ (spike S1)
Goal: a login that needs no terminal prompts.
- `login-start`: the `audible` library exposes an external-browser flow (`audible.login`: build the OAuth URL with a PKCE code verifier and device serial; the browser lands on a "page not found" URL whose query contains `openid.oa2.authorization_code`). Backend generates the URL and stores `{verifier, serial, marketplace}` under a short-lived session id (in memory of a tiny lock-guarded file, expiring in 10 minutes).
- `login-finish`: extract the code from the pasted URL, register the device (`audible.register`), build an `Authenticator`, write `auth.json` (mode 0600), derive and store activation bytes, create the audible-cli `config.toml` profile.
- The UI opens the URL with `xdg-open` and offers a "Paste URL from clipboard" button that calls `wl-paste`.
- Never log or persist the pasted URL.

Existing-login import (`login-import-cli`) copies a valid `~/.audible/*.json` auth file and its marketplace into the plugin config dir (so it is independent from audible-cli afterward).

## 5. Player (QML)

### 5.1 mpv
Started by the service when a book is first played, as a detached process:
```
mpv --no-config --no-video --idle=yes --keep-open=yes --no-terminal --audio-display=no \
    --input-ipc-server=$XDG_RUNTIME_DIR/omarchy-audible/mpv.sock \
    --force-window=no --volume=<saved> --speed=<default>
```
`Quickshell.execDetached` (or `systemd-run --user --scope` ❓ choose in spike S5) keeps it independent of the shell.

The service connects with Quickshell's unix-socket client (`Quickshell.Io` `Socket`) and speaks mpv's JSON IPC (`{"command":[…],"request_id":n}`; events as JSON lines). Observed properties: `time-pos`, `duration`, `pause`, `speed`, `chapter`, `chapter-list`, `path`, `idle-active`, `eof-reached`, `volume`.

Commands: `loadfile <path> replace 0 start=<seconds>`, `set pause yes|no`, `seek ±N relative`, `seek <s> absolute`, `add chapter ±1`, `set chapter <i>`, `set speed <x>`.

### 5.2 PlayerController (QML object)
Exposes: `loaded`, `playing`, `positionMs`, `durationMs`, `chapters[]`, `chapterIndex`, `speed`, `asin`, and functions `play(asin)`, `pause()`, `toggle()`, `skip(seconds)`, `nextChapter()`, `prevChapter()`, `seekMs()`, `setSpeed()`, `setSleepTimer()`.

- Position persistence: write `state.json` every 10 s while playing (single writer: the service, via the backend `state` helper or QML `FileView` with atomic write ❓) and on pause/switch/quit.
- Remote push: debounce, every ~60 s while playing and on pause/stop/switch, through `position-push`.
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

One `Panel.qml` window anchored under the bar icon, hosting a `StackLayout` of three views. View rules:
- Select a book in Library → hide the panel, start playback, and reopen on the **Mini** view when playback begins (so the user sees it work).
- ✕ / Esc / click-away → hide the panel; audio continues.
- Bar click → **Mini** if a book is loaded, otherwise **Library**.
- Mini has a library button (→ Library) and a maximize button (→ Full). Full has a collapse button (→ Mini).
- Onboarding view replaces Library when `status.authenticated` is false or setup is incomplete.

Keyboard: search field focused on open; ↑/↓ move; Enter play; Esc close; Space play/pause when the search field is empty; ←/→ skip in Mini/Full.

Shell IPC target `omarchy-audible` for user hotkeys:
`toggle`, `playPause`, `skip <seconds>`, `nextChapter`, `prevChapter`, `openLibrary`.
Example Hyprland binding: `bind = SUPER, A, exec, omarchy-shell omarchy-audible toggle` (exact call syntax to be confirmed against how other plugin IPC targets are invoked ❓).

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
| Programmatic login harder than the CLI's | Blocks "no terminal" goal (the biggest goal) | Spike S1 first. Fallback: ship the "import existing audible-cli login" path and a one-line copy-paste command |
| `.aaxc` books need a different decrypt path | Some books fail | Spike S2 on a book that is aaxc-only; test both paths |
| Position write-back unsupported | Phone and laptop positions diverge | D4: ship read-only sync |
| Multi-part books | Odd files, wrong durations | Spike S4; mark unsupported if needed |
| Quickshell `Socket`/detached-process API limits | Player design changes | Spike S5 early. Fallback: a tiny helper script that owns mpv and exposes a simpler stdio protocol |
| Third-party plugin capability facades block something needed | UI limits | Spike S6; follow the Spotify plugin, which solves the same problems |
| AGPL dependency licensing | Distribution problems | Install at runtime from PyPI; never vendor |

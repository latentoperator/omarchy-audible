# Omarchy Audible

> **Status: M4 done — the bar icon, drawer and player are built, and B11 is in `main`.** Books download exactly as Audible sends them and stay locked: no decrypted copy is written. The review follow-ups (P6, B12, B13, P7) are under way. See [docs/STATE.md](docs/STATE.md).

A book icon in the [Omarchy](https://omarchy.org) bar. Click it to browse your Audible library in a themed drawer, pick a book, and a mini player takes over. Dismiss it and the book keeps playing. Only the books you're listening to live on your laptop. Removing one never touches your Audible account.

## Planned features

- Library drawer: search, sort by recently listened/added/title/author, filter by downloaded or in progress
- Mini player: cover, title and author, chapters, ⏪15 / ⏩15, speed, scrub; maximize to a full view with chapter list and sleep timer
- Playback survives closing the panel and restarting the shell
- Downloads on demand, one-click "Remove from this laptop", optional auto-remove when finished
- Resumes where you left off on your phone
- Sign in from inside the drawer: open a link, sign in to Amazon in your browser, paste the return link back, or reuse an existing audible-cli login
- Follows the current Omarchy theme, including live theme switches

## Backend CLI

The drawer drives everything through one command, `bin/omarchy-audible`. You can run it yourself to test or script. Every command prints one JSON object per line on stdout and ends with exactly one `done` or `error` line. Human-readable logs go to stderr and never contain credentials, sign-in links or decryption keys.

Exit codes: `0` ok, `1` failed, `2` bad arguments, `3` busy (another job is running). Errors look like `{"type":"error","code":"bad_asin","message":"…","hint":"…"}`.

Add `--fake` (or set `OMARCHY_AUDIBLE_FAKE=1`) to any command to run against a built-in fake library with no network and no account. Real paths follow XDG: login in `~/.config/omarchy-audible/`, catalog and covers in `~/.local/share/omarchy-audible/`, books in `~/Audiobooks/Audible/` (override with `OMARCHY_AUDIBLE_BOOKS_DIR`). Fake mode uses a separate tree (`~/.config/omarchy-audible-fake/`, `~/.local/share/omarchy-audible-fake/`, books in `~/.local/share/omarchy-audible-fake/books`) so it never reads or writes the real login, catalog or books, and ignores `OMARCHY_AUDIBLE_BOOKS_DIR`.

Fake mode also carries its own onboarding state, so the sign-in and setup screens can be tested without an account. A fresh fake tree starts signed in; `logout --fake` signs the fake account out and `login-finish --fake` / `login-import-cli --fake` sign it back in (fake `login-finish` accepts any pasted text containing `openid.oa2.authorization_code=`). To preview the missing-tools or setup screen, write `~/.config/omarchy-audible-fake/fake-status.json` — `{"missing": ["mpv"]}` or `{"venv_ready": false}` (both keys optional) — and delete it afterward; `setup --fake` clears the `venv_ready` override again. Real mode reads neither the marker nor `fake-status.json`.

To exercise the player against a long book, fake `get <asin> --fake-chapters 120` (or `OMARCHY_AUDIBLE_FAKE_CHAPTERS=120`) writes 120 evenly spaced chapters instead of the default 5; the range is 1–500, and real mode ignores it. Fake `get` also fakes the failures that matter: `--fake-fail disk` (the volume is treated as nearly full), `network` (the download breaks part-way), `decrypt` (the voucher arrives without key/iv) and `novoucher` (no aaxc voucher, so the aax fallback runs).

**Setup and health**

```sh
omarchy-audible setup     # build the private Python env (audible-cli 0.6.0, audible 0.12.0); a second run does nothing
omarchy-audible status    # {"type":"status","ready":true,"authenticated":true,"marketplace":"us","account":"c…@…",…}
omarchy-audible doctor    # checks python, mpv, ffmpeg/ffprobe, wl-paste, xdg-open, systemd-run, the env and the login
```

**Sign in** (all password, passkey, 2FA and captcha steps happen in your own browser)

```sh
omarchy-audible login-start --marketplace us
#  {"type":"login_url","url":"https://www.amazon.com/ap/signin?…","session":"<id>"}
#  open the url, sign in; Amazon ends on a "page not found" page — copy that address
omarchy-audible login-finish --session <id>   # paste the address on stdin, then Ctrl-D
#  the link is read from stdin, never as an argument; the session expires after 10 minutes
omarchy-audible login-import-cli              # or: reuse an existing audible-cli login from ~/.audible
omarchy-audible logout
```

Login files are written `0600`. If the copied link is still in Omarchy's clipboard history, `login-finish` says so in its `done` line (`"clipboard_history_contains_code": true`) so you can clear it from the clipboard menu. `logout` removes this device from your Amazon account only if it was created by `login-finish`; an imported audible-cli login is never deregistered, because audible-cli still uses it. Downloaded books are kept either way.

**Library and books**

```sh
omarchy-audible sync [--full]       # refresh the catalog, missing covers and Audible's positions; never sends positions
omarchy-audible get <asin>          # download the locked original (aaxc, falls back to aax) → {"type":"done","path":"…/book.aaxc"}
omarchy-audible play-info <asin>    # how to play a local book: {"type":"play_info","path":"…","chapters_file":"…"|null,"lavf_options":"…"}
omarchy-audible cancel <asin>       # stop a running get and clean up its partial files
omarchy-audible local               # {"type":"local","books":[{"asin":"…","size":…,"downloaded_at":"…"}]}
omarchy-audible remove <asin>       # delete the book from this computer only → {"type":"done","freed_bytes":…}
```

`get` checks free space first, reports `progress` lines while it works, and refuses anything that isn't a plain ASIN (`error` code `bad_asin`). **It does not store a decrypted copy**: the book directory keeps the file exactly as Audible sent it (`book.aaxc` or `book.aax`), the key material in a `0600` `key.json`, the chapter list in `chapters.txt` and the metadata in `meta.json`. No `.m4b` is written, and the download needs about 1.1× the book's size free rather than twice it. `play-info` then hands the player the audio path, the chapter file and the ready-made mpv option that unlocks it in memory; those key options are a secret, are never logged, and are not part of any command line. Old `book.m4b` downloads keep playing as before. `remove` never touches your Audible account or library.

**Listening positions**

```sh
omarchy-audible position-get <asin> [<asin>…]          # {"type":"positions","items":{"<asin>":{"ms":…,"updated_at":"…","own":true?}}}
omarchy-audible position-push <asin> <ms> --at <iso-8601>
```

`position-push` is the only command that changes anything on your Audible account. It re-reads Audible's position first and refuses (`error` code `stale`) if Audible's is newer than your local listening time, so it can't move your phone backwards; `--at` (the local listening time the position came from) is required, and omitting it is `error` code `invalid_args`. Audible stamps a push with its own server clock, so the command also remembers its own writes in `<data dir>/pushed.json` and treats an exactly-matching remote position as its own echo rather than a newer listening — that keeps a computer whose clock runs behind Audible's from locking itself out. `position-get` marks such an echo with `"own": true`. The Audible phone app follows a pushed position on its own, with an undo notice. With `--fake`, positions are kept in `<fake data dir>/fake-account-positions.json` instead of the account, so a push, a resume and the stale check can all be tried with no account.

## Hotkeys and IPC

The shell exposes one IPC target you can drive from a terminal or bind to a key:

```sh
omarchy-shell latentoperator.audible <method> [args]
```

| Method | Meaning |
|---|---|
| `toggle` | Toggle the drawer on the primary bar widget |
| `openLibrary` | Open the drawer on the primary bar widget |
| `playPause` | Toggle play/pause for the loaded book |
| `skip <seconds>` | Seek by a signed number of seconds, e.g. `skip -15` |
| `nextChapter` | Jump to the next chapter |
| `prevChapter` | Jump to the previous chapter |
| `stop` | Stop playback and save the current position |

Every method returns a short string: `ok` on success, or an error such as `error: nothing loaded`.

The target also has read-only status methods, such as `playerStatus`, and test methods. The test methods only work in the plugin's development fake mode; otherwise they return `error: dev only`.

## Settings

Settings are plain JSON keys on this plugin's entry in `~/.config/omarchy/shell.json`, under `bar.layout.<section>`. For example, inside the relevant section's widget array:

```json
{
  "id": "latentoperator.audible",
  "skipSeconds": "30",
  "defaultSort": "Title",
  "defaultSpeed": "1.5×"
}
```

Save the file and Omarchy applies the values live; no shell restart is needed. There is no settings UI for `barWidget.schema` in Omarchy 4.0.4. The manifest schema documents the key types, ranges, choices and defaults.

| Key | Type and accepted values | Default | Meaning |
|---|---|---|---|
| `skipSeconds` | Integer or digit string, 5–120 | `15` | Seconds for back/forward skips. Any integer in range is accepted. |
| `defaultSort` | Sort label, case-insensitive: Recently listened, Recently added, Title, Author | `Recently listened` | Initial drawer sort; the user's drawer choice lasts for the session. |
| `autoRemoveFinished` | `On`/`Off` in any case, or JSON `true`/`false` | `Off` | Remove a finished local book. |
| `showTitleInBar` | `On`/`Off` in any case, or JSON `true`/`false` | `Off` | Show the playing book's title beside the bar icon. |
| `defaultSpeed` | Number or string matching a preset; optional trailing `×`, `x` or `X` | `1.0×` | Starting speed. A changed value applies and saves; an unchanged value preserves the speed chosen with the pill. |
| `syncOnOpenHours` | Integer or digit string, 1–48 | `6` | Minimum interval between automatic catalog syncs. Any integer in range is accepted. |

Speed is snapped only when it matches a preset (`0.75`, `1.0`, `1.25`, `1.5`, `1.75`, `2.0`, `2.5`, `3.0`); invalid or out-of-range values use the default. Invalid integers, sort labels and On/Off values also use their defaults.

**The plugin does not add any keybinding.** To add your own, put this in your Hyprland config — that file is yours, this project never edits it:

```ini
bind = SUPER, A, exec, omarchy-shell latentoperator.audible toggle
```

`qs ipc show` lists the target's methods.

## Tests

The suite has two halves: the Python backend under `tests/`, and the pure `qml/lib/*.js` libraries, which run in PySide6's `QJSEngine` — the same V4 engine Quickshell uses.

```sh
pip install -e '.[dev]'   # pytest, ruff, jsonschema, PySide6-Essentials
make test                 # python -m pytest -q
make lint                 # ruff check ., ruff format --check ., omarchy plugin validate ., no-symlink check
```

The JS suites need PySide6. They **fail** when it is missing rather than skipping, so a missing engine can never leave them silently green; set `OMARCHY_AUDIBLE_ALLOW_SKIP_QJS=1` to skip them on purpose, e.g. on a machine that only runs the Python backend. Tests that build or probe the fake audio (`get`, `cancel`, re-download, `play-info`) need `ffmpeg`/`ffprobe` on `PATH`; where they live elsewhere, point `OMARCHY_AUDIBLE_FFMPEG_DIR` at their directory and it is prepended.

## Documents

| | |
|---|---|
| [docs/SCOPE.md](docs/SCOPE.md) | What we're building, for whom, and what we're not |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it works, verified facts, and open questions |
| [docs/PLAN.md](docs/PLAN.md) | Milestones and tasks with acceptance criteria |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | How work is run (roles, tools, loop) and how to resume on another machine |
| [docs/STATE.md](docs/STATE.md) | Live status, decisions, and next steps |
| [AGENTS.md](AGENTS.md) | Rules for AI coding agents working in this repo |

## License

[AGPL-3.0-only](LICENSE). The backend imports the AGPL-licensed [`audible`](https://github.com/mkb79/Audible) library, which setup installs on your machine; it is not bundled here.

## Notice

This is an unofficial project and is not affiliated with Audible or Amazon. It relies on community libraries and an unofficial API that may change or stop working. It is intended only for listening to books you have purchased, on your own computer. Decrypting audiobooks may violate Audible's terms of use or local law; you are responsible for how you use it.

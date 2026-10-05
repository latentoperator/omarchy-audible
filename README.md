# Omarchy Audible

> **Status: backend built, drawer not yet.** The command-line backend works against a real Audible account; the bar icon, drawer and player come next. See [docs/STATE.md](docs/STATE.md).

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
omarchy-audible get <asin>          # download, decrypt (aaxc, falls back to aax), rebuild chapters → {"type":"done","path":"…/book.m4b"}
omarchy-audible cancel <asin>       # stop a running get and clean up its partial files
omarchy-audible local               # {"type":"local","books":[{"asin":"…","size":…,"downloaded_at":"…"}]}
omarchy-audible remove <asin>       # delete the book from this computer only → {"type":"done","freed_bytes":…}
```

`get` checks free space first, reports `progress` lines while it works, and refuses anything that isn't a plain ASIN (`error` code `bad_asin`). `remove` never touches your Audible account or library.

**Listening positions**

```sh
omarchy-audible position-get <asin> [<asin>…]          # {"type":"positions","items":{"<asin>":{"ms":…,"updated_at":"…"}}}
omarchy-audible position-push <asin> <ms> [--at <iso-8601>]
```

`position-push` is the only command that changes anything on your Audible account. It re-reads Audible's position first and refuses (`error` code `stale`) if Audible's is newer than your local listening time, so it can't move your phone backwards. The Audible phone app follows a pushed position on its own, with an undo notice.

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

Every method returns a short string: `ok` on success, or an error such as `error: nothing loaded`.

**The plugin does not add any keybinding.** To add your own, put this in your Hyprland config — that file is yours, this project never edits it:

```ini
bind = SUPER, A, exec, omarchy-shell latentoperator.audible toggle
```

`qs ipc show` lists the target's methods.

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

# Omarchy Audible

> **Status: planning.** Nothing is built yet. See [docs/](docs/).

A book icon in the [Omarchy](https://omarchy.org) bar. Click it to browse your Audible library in a themed drawer, pick a book, and a mini player takes over. Dismiss it and the book keeps playing. Only the books you're listening to live on your laptop. Removing one never touches your Audible account.

## Planned features

- Library drawer: search, sort by recently listened/added/title/author, filter by downloaded or in progress
- Mini player: cover, title and author, chapters, ⏪15 / ⏩15, speed, scrub; maximize to a full view with chapter list and sleep timer
- Playback survives closing the panel and restarting the shell
- Downloads on demand, one-click "Remove from this laptop", optional auto-remove when finished
- Resumes where you left off on your phone
- Sign in from inside the drawer: open a link, sign in to Amazon in your browser, paste the return link back (a one-time terminal login is the fallback)
- Follows the current Omarchy theme, including live theme switches

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

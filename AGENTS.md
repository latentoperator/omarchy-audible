# Instructions for coding agents

You are implementing one task from [docs/PLAN.md](docs/PLAN.md). Read [docs/SCOPE.md](docs/SCOPE.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first. They are the source of truth. If code and docs disagree, stop and say so; do not guess.

## Ground rules

1. **One task per branch and PR.** Name it after the task ID (`b5-get-remove`). Don't touch unrelated files.
2. **Do not redesign.** If a documented assumption (❓) is false, write findings in `docs/SPIKE-RESULTS.md` and stop for the maintainer.
3. **Secrets.** Never commit, print, or log: auth files, tokens, activation bytes, vouchers, `key`/`iv` values, pasted login URLs, or real library data. Fixtures use invented titles. Backend logs go through the scrubbing logger.
4. **Never mutate the Audible account** except the position write-back in `position-push`. `remove` deletes local files only. There must be no code that calls Audible delete/return endpoints.
5. **Theme tokens only** in QML (`qs.Commons`, `qs.Ui`). No hard-coded colors, fonts, or radii.
6. **Network only in the Python backend.** QML never opens network connections. The only QML-side I/O is the mpv socket, local files, and spawning the backend.
7. **Backend launcher uses the Python standard library only.** Third-party imports (`audible`) belong inside `backend/omarchy_audible/` and run in the plugin venv.
8. **Do not vendor** `audible`/`audible-cli` (AGPL). They are installed at runtime via `setup`.
9. Protocol changes: update `docs/ARCHITECTURE.md` and `tests/schemas/` first, then code.

## Working on this machine

- Link the plugin for live reload: `make dev-link` (symlinks the repo into `~/.config/omarchy/plugins/latentoperator.audible/`). Saving a file reloads the plugin. Force it with `omarchy-shell shell rescanPlugins`. Restart the whole shell with `omarchy-restart-shell`.
- Use `OMARCHY_AUDIBLE_FAKE=1` for all development. It needs no account and no network. Use the real account only when a task says so.
- Reference plugins to copy patterns from: `~/.config/omarchy/plugins/quickshell.spotify/` (closest analogue), `~/.config/omarchy/plugins/chrisgray.kanban/` (minimal bar widget), `/usr/share/omarchy/shell/plugins/panels/audio/`. Shell docs: `/usr/share/omarchy/shell/README.md`, `plugins/README.md`.
- Tests: `make test`. Lint: `make lint`.

## Style

- Python 3.11+, type hints, small functions, no global state. `ruff` defaults.
- Every backend command: emit NDJSON per ARCHITECTURE §4.2, nonzero exit on failure, final `done` or `error` event, never print anything else to stdout.
- QML: one component per file, properties over imperative code, no business logic in views. Views bind to `Service`/`LibraryModel`/`PlayerController`.
- Write the test first when the task has pytest acceptance criteria.
- Match existing code; don't add comments that restate the code.

## When you finish

Report: what changed, how you verified it (commands run and results), anything you could not verify, and any doc corrections needed. Tick the task's checkbox in `docs/PLAN.md`.

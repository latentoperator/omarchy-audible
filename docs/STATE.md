# Project state

Update this file in every PR that changes status. Newest first. See [WORKFLOW.md](WORKFLOW.md) for how work is run.

**Last updated:** 2026-10-04 · **Phase:** M0 (spikes + scaffolding) · **Gate G0:** not reached

## Where we are

| Item | Status |
|------|--------|
| Scope, architecture, plan, agent rules | Written and pushed (`docs/`, `AGENTS.md`) |
| Workflow and handoff doc | Written (`docs/WORKFLOW.md`) |
| Repo | `latentoperator/omarchy-audible`, **private** |
| A0 scaffolding | **In progress.** Attempt 1 produced nothing (opencode blocked reading outside the repo, exited 0). Attempt 2 (DeepSeek Flash with in-repo `.reference/` copies) was running on branch `a0-scaffolding`; **not yet verified, reviewed, or committed**. |
| Spikes S1–S6 | Not started |
| Backend / player / UI | Not started |

## Environment (laptop, HMSP-OMARCHYXPS)

- `audible-cli` 0.6.0 installed with `uv tool`; logged in (profile `chrisgray`, files in `~/.audible/`, 91 books).
- Manual proof of the pipeline: downloaded one `.aax`, decrypted with `ffmpeg -activation_bytes … -c copy` to `.m4b` with chapters intact (a leftover test book is in `~/Audiobooks/`). Remote position read (`lastpositions`) works.
- Codex plugin `codex@openai-codex` 1.0.6 installed and `/codex:setup` reports ready. Review gate is **off**.
- DeepSeek works through opencode 1.18.34 (`deepseek/deepseek-flash` and `deepseek/deepseek-v4-pro` verified with a one-word prompt).

## Decisions made

- Panel-style maximize (no separate window).
- Auto-remove finished books: **Off** by default.
- In-drawer login is a **nice-to-have**, not required. A one-time terminal login is an acceptable fallback.
- Worker model: DeepSeek Flash through opencode. Reviewer: Codex. Supervisor: Claude Code.
- Repo is private until M3, then public.

## Open decisions

| ID | Question | Notes |
|----|----------|-------|
| D1 | License | Decide after S1. `audible` and `audible-cli` are **AGPL-3.0-only** (verified). AGPL-3.0 is the safe pick if our backend imports `audible`; MIT only if we call `audible-cli` strictly as a subprocess. Marketplace accepts either. |
| D4 | Position write-back to Audible | Decided by spike S3. |
| D5 | Multi-part books | Decided by spike S4. |
| D6 | Encrypt auth file | No for v1. |

## Next steps (in order)

1. Finish A0: verify the worker output yourself (`git status`, diff, `python -m pytest -q`, `make check-symlinks`, `omarchy plugin validate .`), then test `make dev-link` plus `omarchy-shell shell rescanPlugins` on the laptop. Codex adversarial review. Commit, PR, tick A0.
2. Spikes, strongest model, laptop: S6 and S5 first (they decide the UI and player design), then S1, S2, S4, S3. Write findings in `docs/SPIKE-RESULTS.md`.
3. Gate G0: Chris reviews the spike results, resolves D1/D4/D5, and the docs are corrected to match reality.
4. M1 backend can then run on the laptop or the VPS (fake mode only on the VPS).

## Known risks to keep in mind

- Audible can change its API at any time. Pin `audible-cli`.
- Marketplace maintainers may decline a plugin that decrypts DRM. `omarchy plugin add <git-url>` works regardless.
- Worker exit codes are unreliable. Verify output yourself.

# Project state

Update this file in every PR that changes status. Newest first. See [WORKFLOW.md](WORKFLOW.md) for how work is run.

**Last updated:** 2026-10-04 (night) · **Phase:** M1 (backend) · **Gate G0:** ✅ passed 2026-10-04

## Where we are

| Item | Status |
|------|--------|
| Scope, architecture, plan, agent rules | Written and pushed (`docs/`, `AGENTS.md`) |
| Workflow and handoff doc | Written (`docs/WORKFLOW.md`) |
| Repo | `latentoperator/omarchy-audible`, **private** |
| A0 scaffolding | **Done.** Live-shell check passed on the laptop 2026-10-04 (`scripts/dev-live-check.sh`: shell discovered `latentoperator.audible` via the symlinked dir; plugin left linked but not enabled). Branch `a0-scaffolding`. Worker (DeepSeek Flash) took 3 attempts: #1 blocked reading outside the repo, #2 hung with no model output (killed), #3 succeeded with `--format json` + timeout. Supervisor re-ran `pytest` (1 passed), `make check-symlinks`, `omarchy plugin validate .` (passes; fails correctly on a missing entry point) and fixed a `dev-link`/`dev-unlink` safety bug. Codex adversarial review: **approve, no findings**. |
| Spikes S5, S6 | **Done 2026-10-04** (Dante, driving the laptop over SSH from Hopebox). Findings in `docs/SPIKE-RESULTS.md`, prototypes in `spikes/`. S6: a bar widget that owns a `qs.Ui` KeyboardPanel gives an anchored, themed drawer that closes on Esc, click-away, and popout switch; the IPC target lives in the service. S5: mpv started with `systemd-run --user --scope` survives `omarchy-restart-shell`, and the service reattaches in under 3 s with live state. Proposed G0 changes: drop the `panel` kind, rename the IPC target to `latentoperator.audible`, and note that `Service.qml` edits need a shell restart. The laptop was left as found: plugin disabled, checkout on `main`. |
| Spikes S2, S3, S4 | **Done 2026-10-04** on the laptop (counts and shapes only left it). S4: the catalog groups work in 0.9 s; multi-part books are ordinary single files (D5: no special handling). S2: aax and aaxc both decrypt losslessly with exact durations; embedded chapters can be coarser than Audible's list (rebuild from `chapters.json`). S3: position write-back round trip exact and restored; phone-app check passed (D4: ship write-back). |
| Spike S1, S3 phone check | **Done 2026-10-04** with Chris at the laptop. S1: two-step sign-in (link → pasted redirect URL) registers a device, writes `0600` files, and lists all 91 books; the one-time code was not found in clipboard history, shell history, journals, or the new files; the test device was deregistered afterward. `~/.audible` import works independently of audible-cli. Proposed: `login-finish` reads the URL from stdin, not argv. Clipboard history is a real leak path B3 must handle. S3: the phone follows a write within one app restart and moves by itself with an undo notice (no prompt), so only locally-listened positions may be pushed. |
| Gate G0 | **Passed 2026-10-04.** Chris approved D1 AGPL-3.0-only, D4 write-back (local-listening-only push rules), D5 no multi-part handling, aaxc-first with aax fallback, chapters from Audible's list, no `panel` kind, IPC target `latentoperator.audible`, `login-finish` on stdin. ARCHITECTURE corrected; ownership contracts added (§4.8); minimal Mini view moved into M3 (U2a). `LICENSE` added. |
| Backend (M1) | Kanban lane created: DeepSeek implements, code-reviewer reviews the exact head, Dante reruns checks and merges. Order B1 → B7 → B5 → B2 → B3 → B4 → B6. |
| Backend B1 | **Done.** `bin/omarchy-audible` (stdlib-only) dispatches commands and routes fake/no-venv runs through `backend/omarchy_audible`; it **re-execs** the backend with `os.execve` (same PID, so killing the spawned process stops the job and releases `job.lock`); shared NDJSON `emit()`/`done`/`error` with stable codes, a secret-scrubbing stderr logger (key=value, JSON and dict-repr shapes), the §4.8 job lock (non-blocking `flock` on `job.lock`, `error(code=busy)`) plus a `job.json` helper, `--fake` / `OMARCHY_AUDIBLE_FAKE=1`, and working `status`/`doctor`. Schemas for `status`/`doctor`/`done`/`error` in `tests/schemas/`. Branch `b1-launcher-protocol`; 26 tests pass under `uv run --isolated --no-project --with pytest --with jsonschema python -m pytest -q`. |
| Player / UI | Not started |

## Environment (laptop, HMSP-OMARCHYXPS)

- `audible-cli` 0.6.0 installed with `uv tool`; logged in (profile `chrisgray`, files in `~/.audible/`, 91 books).
- Manual proof of the pipeline: downloaded one `.aax`, decrypted with `ffmpeg -activation_bytes … -c copy` to `.m4b` with chapters intact (a leftover test book is in `~/Audiobooks/`). Remote position read (`lastpositions`) works.
- Codex plugin `codex@openai-codex` 1.0.6 installed and `/codex:setup` reports ready. Review gate is **off**.
- DeepSeek works through opencode 1.18.34 (`deepseek/deepseek-flash` and `deepseek/deepseek-v4-pro` verified with a one-word prompt).

## Decisions made

- Panel-style maximize (no separate window).
- Auto-remove finished books: **Off** by default.
- In-drawer login works (S1) and is the v1 path. The terminal login stays only as an emergency fallback.
- License: **AGPL-3.0-only** (D1, G0).
- Position write-back ships, but only local listening is pushed (D4, G0). Multi-part books need no special handling (D5, G0).
- Downloads try aaxc first and fall back to aax. Chapters are rebuilt from Audible's list (G0).
- M1 runs on Hermes Kanban: DeepSeek implements, the code-reviewer profile reviews the exact head, Dante reruns checks and merges (see WORKFLOW.md). Earlier phases used opencode + Codex + Claude Code.
- Repo is private until M3, then public.

## Open decisions

| ID | Question | Notes |
|----|----------|-------|
| D6 | Encrypt auth file | No for v1. |

D1, D4, D5 were decided at G0 (see SCOPE §9).

## Next steps (in order)

1. ~~Finish A0~~ Done. ~~All spikes S1–S6 and the S3 phone check~~ Done.
2. ~~Gate G0~~ Passed.
3. M1 backend on the Kanban lane (Hopebox, fake mode only). Real-account checks for B3/B5/B6 run on the laptop by Dante.
4. M2 QML (P1, P2) can start in parallel once B1 merges; it needs the laptop.

## Known risks to keep in mind

- Audible can change its API at any time. Pin `audible-cli`.
- Marketplace maintainers may decline a plugin that decrypts DRM. `omarchy plugin add <git-url>` works regardless.
- Worker exit codes are unreliable. Verify output yourself.

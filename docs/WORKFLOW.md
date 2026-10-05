# Workflow — who does what, and how to resume on another machine

This file describes **how work on this repo is run**, so the same workflow can be picked up on any machine (the Omarchy laptop, the VPS "Hopebox", or a new one). Live status is in [STATE.md](STATE.md); the work breakdown is in [PLAN.md](PLAN.md). Claude's per-machine memory does **not** transfer between machines, so these files are the source of truth.

## Roles

| Role | Who / what | Does | Does not |
|------|------------|------|----------|
| Product owner | Chris | Sets scope, decides D1–D6, runs anything that touches the live desktop shell or the real Audible login | |
| Supervisor and final judge | Claude Code (strongest model available) | Writes specs and worker prompts, runs spikes S1–S6, **independently re-runs every check** on worker output, decides accept or rework | Trust a worker's self-report |
| Worker | DeepSeek Flash via `opencode` (`deepseek/deepseek-flash`) | Implements bounded A/B-tier tasks on a branch | Commit, push, merge, touch the live shell, or read credentials |
| Independent reviewer | Codex (`/codex:adversarial-review`, `/codex:review`) | Reviews the worker's diff with fresh eyes and reports findings | Approve its own work or merge |

This mirrors the supervised-worker setup used in the omamail project (`omamail-private/planning/REVIEW-GATE.md`): workers implement, an independent reviewer produces findings, and the supervisor records the final judgment. Tier labels (A/B/S) in PLAN.md say which tasks go to which role: **A** worker alone, **B** worker plus review, **S** supervisor or the strongest model.

## Kanban lane (M1 onward, Hopebox)

From G0 on, backend tasks run as Hermes Kanban cards on Hopebox instead of the opencode loop below:

| Card | Profile | Does |
|------|---------|------|
| Implement `<task>` | `deepseek` | Works in its own git worktree on branch `<task-id>-<slug>`, writes tests first, runs `make test`, commits, pushes the branch, and opens a PR against `main`. Never merges. |
| Review `<task>` | `code-reviewer` | Reviews the PR at its exact head SHA, read-only. PASS: comments `PASS — exact-head review <sha>` and completes. FAIL: comments the findings and blocks. |
| Verify and merge `<task>` | `dante` | Re-reads the diff, re-runs every acceptance check, and runs real-account checks on the laptop where the task requires them. Merges when everything holds, otherwise sends the work back. Completing this card releases the next task. |

Tasks run one at a time in the order B1 → B7 → B5 → B2 → B3 → B4 → B6, because they share the backend package and the CLI dispatcher. Kanban workers on Hopebox run **fake mode only** and never touch real credentials. Hopebox has no Omarchy shell, so `omarchy plugin validate .` runs on the laptop in the merge card. The hard rules below still apply, except that the Kanban implementer commits and pushes its own branch.

## Laptop lane (M2 QML onward)

QML work needs the real shell, so it runs on HMSP-OMARCHYXPS with Claude Code or Codex: one implements and the other reviews the exact head, both following the task brief in `docs/briefs/`. Dante does the final check and merges. Pure logic still goes into `qml/lib/*.js` with QJSEngine tests, so the Hopebox Kanban lane can keep building it. The first brief is [briefs/M2-laptop.md](briefs/M2-laptop.md).

## The loop (one task = one branch = one PR)

1. **Branch** from `main`: `git checkout -b <task-id>-<slug>` (e.g. `a0-scaffolding`).
2. **Prepare references** inside the repo (see "Reference copies" below). Workers cannot read outside the repo.
3. **Write a self-contained worker prompt**: the task text from PLAN.md, the files to read, hard rules (below), and the exact report format. Save it outside the repo (a temp file).
4. **Run the worker**, in the repo directory:
   `opencode run -m deepseek/deepseek-flash "$(cat /path/to/prompt.md)"`
   Run it in the background; output is buffered and appears at the end.
5. **Verify independently.** Read the diff. Re-run the acceptance checks yourself (`make test`, `make lint`, `omarchy plugin validate .`, `make check-symlinks`). Test anything the worker was told not to run (live-shell steps).
6. **Review** with Codex: `/codex:adversarial-review` on the branch diff. Triage findings; send fixes back to the worker or fix directly.
7. **Commit** only after the checks pass, with the task ID in the message. Push and open a PR. Tick the checkbox in PLAN.md and update STATE.md in the same PR.

## Hard rules to put in every worker prompt

- Do not run `git commit/push/branch`, `make dev-link`, `omarchy-shell`, `omarchy plugin add/enable`, or anything that touches `~/.config/omarchy` or restarts the shell.
- Do not read or touch `~/.audible`, `~/.config/omarchy-audible`, `~/Audiobooks`, or any credential.
- No symlinks inside the repo. Do not edit `docs/` or `AGENTS.md` unless the task says so.
- If something needed cannot be read, **stop and say so**; never claim success.
- Final report: files created, commands run with exact output, what could not be verified, doc inconsistencies.

## Lessons learned (update as we learn more)

- **opencode auto-rejects file reads outside the working directory** (`external_directory`; "auto-rejecting"). The first A0 attempt on 2026-10-04 hit this, read nothing, wrote nothing, and still **exited 0**. Exit status is not evidence of success. Always check `git status` and the diff.
- **Reference copies:** put what the worker must read into a git-ignored `.reference/` folder in the repo (`echo '.reference/' >> .git/info/exclude`). For A0 this held: the Spotify plugin's `manifest.json` plus the first ~120 lines of `Service.qml`/`BarWidget.qml`/`Panel.qml`, kanban's `manifest.json` and `BarWidget.qml`, and the "Installing a third-party plugin" section of `/usr/share/omarchy/shell/README.md`. Source paths: `~/.config/omarchy/plugins/{quickshell.spotify,chrisgray.kanban}/` and `/usr/share/omarchy/shell/`. On a machine without those, copy `.reference/` over from the laptop (it is not committed).
- **Run workers with `--format json` and a timeout**, writing events to a file you can watch: `timeout 900 opencode run -m deepseek/deepseek-flash --format json --print-logs --log-level INFO "$(cat prompt.md)" > events.jsonl 2> stderr.log`. Attempt 2 of A0 sat for 9 minutes with no model output (the opencode DB and log showed nothing after startup); attempt 3 with the same prompt finished in about 1 minute. A growing `events.jsonl` means it is alive; a flat one means kill and retry. The final report is the last `text` event.
- **Do not use `pkill -f` with a pattern that appears in your own command line**; it kills your shell. Find workers with `pgrep -x opencode` and kill by pid.
- **`make test` needs pytest**, which the system Python may lack. Use a venv: `python3 -m venv .venv && .venv/bin/pip install pytest`, then `PATH="$PWD/.venv/bin:$PATH" make test` (`.venv/` is git-ignored).
- **Supervisor checks that caught real issues:** the worker's Makefile `dev-link` would have created the link inside an existing real plugin directory, and `dev-unlink` would `rm -f` anything. Reviewing the Makefile line by line, not just running the targets, found it. Codex's review did not catch this class of issue on its own because the guard had already been fixed; do the read-through first.
- `opencode run` (without `--format json`) buffers output until it finishes. A silent worker is not necessarily stuck, but if the opencode log (`~/.local/share/opencode/log/opencode.log`) shows no activity for several minutes, kill it and retry with a smaller prompt.
- The Codex plugin and DeepSeek access are per machine. Verify them on a new machine before relying on them (checklist below).

## Which machine does what

| Work | Where | Why |
|------|-------|-----|
| Spikes S1–S3 (Audible login, decrypt, positions) | **Laptop** | Needs the real Audible account and a browser for sign-in |
| Spikes S5–S6, all QML work (M2 UI parts, M3, M4), manual tests, theme checks | **Laptop** (any Omarchy machine) | Needs the live Omarchy shell and a display |
| Backend (M1), fake mode, pytest, protocol schemas | **Laptop or VPS** | Headless and testable offline |
| Docs, planning, PR review loop | Anywhere | |

**Safety rules for the VPS:**
- Do **not** copy `~/.audible/`, `~/.config/omarchy-audible/`, `activation_bytes`, or any `*.aax`/`*.aaxc`/`*.m4b` there. The VPS works only in fake mode (`OMARCHY_AUDIBLE_FAKE=1`).
- Fixtures contain invented titles only (see AGENTS.md).
- The VPS likely has no Omarchy shell, so `omarchy plugin validate` and live-load tests may be unavailable there. Do those on the laptop before merging.

## New-machine checklist

```bash
git clone https://github.com/latentoperator/omarchy-audible && cd omarchy-audible
python3 --version          # 3.11+
ffmpeg -version | head -1  # needed for fake-mode fixtures and (laptop) decrypt
which opencode && opencode run -m deepseek/deepseek-flash "Reply with exactly: ok"   # worker works
which codex && codex --version                                                       # reviewer CLI
# in Claude Code: /plugin marketplace add openai/codex-plugin-cc ; /plugin install codex@openai-codex ; /codex:setup
```

Laptop only, for real-account work: `uv tool install audible-cli` then run `audible quickstart` in a real terminal (it needs an interactive TTY, so it will not work through Claude Code's `!` prefix). Auth lands in `~/.audible/`.

## Where state lives

| What | Where |
|------|-------|
| Scope, architecture, plan | `docs/SCOPE.md`, `ARCHITECTURE.md`, `PLAN.md` (this repo) |
| Live status, next steps, decisions | `docs/STATE.md` (this repo) |
| Narrative and project page | Obsidian: `Hopewell MSP/05-Dev/Projects/Omarchy Audible/Omarchy Audible.md` and a dated note in `11-Claude/` |
| Claude per-machine memory | `~/.claude/projects/.../memory/` (does not transfer) |

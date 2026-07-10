# CLAUDE.md (global)

<!-- Maintainer note (stripped from context): master lives in the claude-skills repo as
global-CLAUDE.md. Do not edit ~/.claude/CLAUDE.md directly — it is a one-line stub:
@~/path/to/claude-skills/global-CLAUDE.md
Edit the master, commit, and `git pull` on the other machine. -->

Standing instructions for Claude Code across all my research projects. Read at the start of
every session and after every `/clear`. A project-root `CLAUDE.md` adds repo-specific facts
on top of this — this file holds only what is identical across every repo. Keep it lean;
every line costs context on every turn.

## Session start
1. Read `CHECKPOINT.md` and `MEMORY.md` if they exist — resume from the last known state.
2. Read `tasks/lessons.md` if it exists — don't repeat past mistakes.
3. Identify the active project from the working directory and current git branch.
4. If I reference prior decisions, earlier results, or "what we did before", check
   `MEMORY.md` / `tasks/` before answering. Do not guess.
5. If `literature/pdf/` exists, run `literature-sync` **without `--yes`** (preview only —
   lists unconverted PDFs, no API calls) and report the count. Convert only on my go-ahead.

## Stable vs. fluid files
`CLAUDE.md` and `PLAN.md` are read-mostly anchors — the standing rules and the roadmap. Do
not edit them in routine automation; change only on explicit instruction, and show a diff
for approval first. The fluid working state lives elsewhere:
- `tasks/todo.md` — the live task checklist; update it continuously (mark done, add follow-ups).
- `MEMORY.md` — persistent project knowledge, one line per entry. The repo-local
  `MEMORY.md` (git-synced across my machines) is canonical; built-in auto memory is
  machine-local, so treat it as a scratchpad and promote durable facts into the repo file.
- `tasks/lessons.md` — a one-line rule after each correction, so it doesn't recur.

## Core principles
- **Maximum effort.** Treat each task thoroughly; re-read your output against the original
  request and fix gaps before presenting. No silent TODOs, no skipped edge cases.
- **Plan before acting.** For anything non-trivial (3+ steps, a new estimator, a design
  decision), write the plan to `tasks/todo.md` and get my approval first. Interview me with
  concrete options under ambiguity — ask, don't guess.
- **Verify before "done".** Prove it works: re-run, check residuals/coverage, diff against
  the previous result. The standard is "would a careful referee accept this step?"
- **Judgment stays with me.** You draft and check; I decide. Surface assumptions and
  trade-offs rather than hiding them behind a confident summary.
- **Demand elegance.** For non-trivial changes, ask whether there is a cleaner approach
  before committing to a hacky one.

## Orchestration (delegate aggressively, verify rigorously)
Operate as a manager. Hand heavy work to Codex (code, math, simulation) and Antigravity
(reading, literature, long context) via the `delegate` skill; keep orchestration,
integration, and the final quality gate here. Package full context into every delegation —
the external CLIs cannot see project files. They are prerequisites I install myself and cost
money; if they are absent, fall back to independent re-derivation in a fresh sub-context.

Routing (first match wins):
| # | Condition | Route |
|---|-----------|-------|
| 1 | Iterative local loops (edit→run→test→fix) | Claude Code |
| 2 | Secrets, credentials, destructive/stateful ops | Claude Code |
| 3 | High-stakes proof / identification argument | Cross-verify (Codex + Antigravity; Claude CLI breaks ties) |
| 4 | Routine check of a known result / algebra | Antigravity |
| 5 | Code: implement, debug, refactor, test, simulate, mechanical LaTeX | Codex |
| 6 | Reading/reasoning: literature, citations, summaries | Antigravity |
| 7 | Referee review of my own draft | `refine` (independent OpenAI agent — never Claude) |
| 8 | Drafting prose / teaching material | Antigravity draft → Claude edit |

For trivial fixes (typo, off-by-one, missing import), skip the table and do it directly.

## Delegation discipline
- One task per subagent; keep the main context clean.
- Read delegation output with `head -3` (the STATUS/VERDICT header); `cat` only on failure.
- Cap concurrent external dispatches at 6 across all subagents.
- When Codex and Antigravity disagree on a high-stakes claim, resolve it before accepting —
  do not average two answers.

## Quality gates (check before presenting)
| Task type | Must verify |
|---|---|
| Code | Runs; tests pass; seeds set; no absolute paths |
| Estimation | Identification stated; SEs at the right level; robustness checked |
| Proofs | Every step explicit; assumptions stated; cited results checked against source |
| Delegated | STATUS/VERDICT checked; output matches spec; disagreements resolved |
If a gate fails, diagnose and retry — do not patch a number to make it pass. Domain-specific
gates (e.g. conjoint diagnostics) live in the project `CLAUDE.md`.

## Source-verification rule
- Cited results and characterizations of cited work **must be checked against the original
  source text** in the reference library (`literature/`), not against model recall.
- Results provable from definitions alone are exempt unless a specific version/claim is asserted.
- Figures in converted markdown are **caption-only placeholders** — verify any figure-based
  claim against the original PDF, never the `.md`.
- If a source is unavailable, **flag it explicitly** rather than paraphrasing from memory.
- Use the `citation-check` skill before any draft is presented.

## Reproducibility & safety
- Set seeds always. No absolute paths — use project-relative paths.
- Keep the ordered pipeline intact: cleaning → make-data → estimation → figures → results.
- **Never write under a raw-data directory** (`*/04_raw_data/` or the repo's equivalent); it
  is read-only. All transformations write to the make-data directory. A PreToolUse hook
  enforces this and blocks `rm -rf`; if a command is blocked, stop and ask — do not work around it.
- Never print, log, or commit secrets/credentials. Those operations stay in Claude Code and
  are never delegated.

## Context & memory
- `/clear` once the window is well used — quality drops and tokens rise as it fills.
- Before clearing, write the next steps down (`tasks/todo.md`, `MEMORY.md`).

## Environment (my machines)
- I work on both **Mac (zsh)** and **Windows (Git Bash / MINGW64)**; assume either.
- The delegation/PDF agent is **Antigravity CLI (`agy`)** — the terminal binary, *not* the
  Antigravity VS Code editor, which is a separate product that can shadow the `agy` name on
  PATH. If `agy` returns nothing, confirm `~/.local/bin/agy` (the CLI) precedes the editor.
- On Windows, `TMPDIR` must point to a native path (e.g. `C:/Users/.../AppData/Local/Temp`);
  a UNIX-style `/tmp` breaks gemini-pdf chunking.
- `agy` runs **one instance per machine** — never parallelize it; parallel runs hang.
- For long batch conversions, keep the machine awake (disable sleep) and the window open.

## About me / conventions
- Empirical microeconometrics: survey experiments (conjoint), household finance, labor,
  and macroeconomics.
- Methods: IV / DID / event study / local projections; conjoint experiment / survey experiment.
- **Stata** and **R (tidyverse)** for primary estimation; **Python** for independent
  re-derivation, diagnostics, and figures; **LaTeX** for writing; quick slides are
  sometimes made in Markdown with **Marp**.
- Deliverables (manuscript, code, comments) in English. Explanations to me: concise Japanese
  is fine — direct, assumptions stated, no filler, no README files unless asked.

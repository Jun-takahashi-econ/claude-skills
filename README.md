# claude-skills

Personal [Claude Code](https://claude.com/claude-code) skills for empirical economics
research — survey / conjoint experiments, household finance, and literature management.
Distributed as a plugin marketplace (`takahashi-skills`) so every project shares one
central set of skills instead of copying them into each repository.

> **Design note.** General-purpose skills (`delegate`, `gemini-pdf`) live in
> [`hkasahar/claude-code-skills`](https://github.com/hkasahar/claude-code-skills) and are
> used from my fork (kept current with *Sync fork*). **This** repository holds *my own*
> skills only, to avoid duplicate maintenance. `literature-sync` depends on `gemini-pdf`
> being installed.

## Skills

| Skill | What it does |
|---|---|
| **`literature-sync`** | Convert new paper PDFs in `literature/pdf/` to Markdown in `literature/md/`, delegating to `gemini-pdf` (agy). Idempotent reconcile; on demand, at session start, or via an optional watcher. |
| **`citation-check`** | Verify every citation in a draft against original source text in the reference library — never model memory. SUPPORTED / MISCHARACTERIZED / MISSING SOURCE. |
| **`conjoint-amce`** | AMCEs + marginal means from long-format conjoint data, respondent-clustered SEs, tidy tables + forest plot, reconcile vs. existing results. |
| **`conjoint-diagnostics`** | Pass/fail gates before trusting AMCEs: balance, placebo, profile order, carryover, SE ratio, comprehension robustness. |
| **`refine`** | Referee memo for a draft, always delegated to an independent ChatGPT agent (codex CLI / OpenAI API) — never self-review. |

Migrated from per-project repos (`sbi_2026` etc.) to end per-repo duplication.

## Install

This is a **private** repository — your local `git`/`gh` must be authenticated with this
account for the marketplace add to work.

```text
/plugin marketplace add Jun-takahashi-econ/claude-skills
/plugin install literature-sync@takahashi-skills
/plugin install citation-check@takahashi-skills
/plugin install conjoint-amce@takahashi-skills
/plugin install conjoint-diagnostics@takahashi-skills
/plugin install refine@takahashi-skills
```

Restart Claude Code (or `/reload-plugins`). Manual copy (no versioning):

```bash
git clone https://github.com/Jun-takahashi-econ/claude-skills.git
cp -R claude-skills/skills/* ~/.claude/skills/
```

## `literature-sync` — quick look

```bash
LIT="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/skills/literature-sync}"
LIT="${LIT:-$HOME/.claude/skills/literature-sync}"

bash "$LIT/scripts/sync_literature.sh"        # preview: list PDFs needing conversion
bash "$LIT/scripts/sync_literature.sh" --yes  # convert them (sequential)
```

Prerequisite: the `gemini-pdf` skill installed and `agy` (Antigravity CLI) signed in.
Details: [skills/literature-sync/SKILL.md](skills/literature-sync/SKILL.md).

## Python dependencies (conjoint skills)

```bash
pip install pandas numpy statsmodels scipy matplotlib pyreadstat
```

## Security

- Skills run shell commands; some send documents to external services (Google via `agy`,
  OpenAI via `codex`). **Do not send confidential or embargoed material. Never commit API
  keys** — `refine` reads `OPENAI_API_KEY` from the environment only.
- `literature/pdf/` (raw sources) is read-only to these skills.
- Review scripts before running — they are short and readable.

## Attribution & license

Workflow adapted from H. Kasahara, *"Using LLMs and Generative AI for Economics Research"*
(2026) and his `claude-code-skills` (the `gemini-pdf` dependency). MIT License.

Model names, CLI flags, and prices change quickly — values here are dated snapshots.

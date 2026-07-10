---
name: literature-sync
description: Convert new paper PDFs in a literature folder to Markdown, so the reference library stays current for citation checks and hallucination defense. Reconcile is idempotent — only PDFs without a matching .md are converted (existing .md files are skipped); raw PDFs are never modified. Delegates the actual conversion to the gemini-pdf skill (Antigravity CLI / agy vision pathway). Triggers include "sync the literature folder", "convert new literature PDFs", "I dropped a paper in literature", "update the reference library", and "PDF to markdown for my citations".
---

# literature-sync

Keep `literature/md/` in sync with `literature/pdf/`. Drop a paper PDF into the source
folder; this skill finds every PDF that has no matching Markdown yet and converts it,
one at a time, using the `gemini-pdf` skill. It is a thin orchestrator — it does **not**
reimplement conversion.

## When to use

- You added one or more paper PDFs to `literature/pdf/` and want the `.md` versions.
- At session start, to catch anything added since last time.
- Before a citation check, to make sure the reference library is complete.

## Prerequisite

The **`gemini-pdf`** skill must be installed (from Kasahara's `claude-code-skills`), and
`agy` (Antigravity CLI) must be signed in. This skill locates `gemini-pdf` automatically at
`$CLAUDE_PLUGIN_ROOT/skills/gemini-pdf` or `~/.claude/skills/gemini-pdf`.

## Quick usage

```bash
# Locate this skill (plugin install or manual copy)
if [ -n "$CLAUDE_PLUGIN_ROOT" ]; then
  LIT="$CLAUDE_PLUGIN_ROOT/skills/literature-sync"
else
  LIT="$HOME/.claude/skills/literature-sync"
fi

# Preview: list which PDFs still need conversion (no API calls, no conversion)
bash "$LIT/scripts/sync_literature.sh"

# Convert them (sequential; ~1-4 min per chunk). --yes is required to convert.
bash "$LIT/scripts/sync_literature.sh" --yes

# Custom folders
bash "$LIT/scripts/sync_literature.sh" --src literature/pdf --out literature/md --yes

# Also append BibTeX to a central reference library
#   (needs GEMINI_PDF_REFERENCE_DIR set for the gemini-pdf skill)
bash "$LIT/scripts/sync_literature.sh" --bib --yes
```

## How it works

```
find literature/pdf/ -iname '*.pdf'
  for each PDF whose literature/md/<same-name>.md is MISSING:
      gemini-pdf/scripts/pdf_to_markdown.sh  <pdf>  <md>
  (existing .md are skipped; subfolder structure under pdf/ is mirrored under md/)
log every action to literature/logs/literature_sync.log
print a COUNT-ONLY summary (converted / skipped / failed)
```

- **Sequential by design.** `agy` hangs when run in parallel, so conversions run one at a
  time. Dropping 20 PDFs is fine; they process in series (~1-4 min per chunk each).
- **Preview by default.** Without `--yes` the script only lists pending files and exits —
  no conversion, no API calls. Pass `--yes` to actually convert. (Same dry-run/run split as
  the fertility `gemini_pdf_batch.py`.)
- **Idempotent.** Re-running only picks up genuinely new/missing files.

## Three ways to trigger it

1. **On demand (default).** Run the script, or ask Claude Code to "sync the literature folder".
2. **At session start (recommended, cross-platform).** Add this line to the project `CLAUDE.md`:
   > At session start, if `literature/pdf/` contains PDFs with no matching `literature/md/*.md`,
   > run the `literature-sync` skill and report counts only. Do **not** read PDF or MD bodies
   > into context (a `head -10` frontmatter check is the maximum).
3. **True file watcher (optional, macOS).** `scripts/watch_literature.sh` uses `fswatch` to
   run a debounced sync whenever a PDF lands. Needs `brew install fswatch`. On Windows, prefer
   option 2, or schedule the sync script via Task Scheduler.

## Configuration

| Variable / flag | Default | Meaning |
|---|---|---|
| `--src` / `LIT_SRC_DIR` | `literature/pdf` | Where PDFs are dropped |
| `--out` / `LIT_OUT_DIR` | `literature/md` | Where `.md` files are written |
| `--yes` | (off) | Actually convert; without it the script previews and exits |
| `--bib` | (off) | Also sync each result into the gemini-pdf reference library (needs `GEMINI_PDF_REFERENCE_DIR`) |
| `LIT_LOG_DIR` | `literature/logs` | Log destination |

## Security / discipline

- `literature/pdf/` is treated as **read-only**; this skill never edits or deletes PDFs.
- No destructive shell ops. No `rm -rf`.
- Claude does **not** read PDF/MD bodies into context — only counts, logs, and (at most) the
  10-line YAML frontmatter of a converted file.
- Conversion sends documents to Google via `agy`. Do not place confidential or embargoed
  PDFs here. Never commit API keys.

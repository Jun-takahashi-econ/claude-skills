---
name: literature-sync
description: Convert new paper PDFs in a literature folder to Markdown, enrich each paper's metadata from Crossref (volume, issue, pages, publisher), and write a local BibTeX sidecar — so the reference library stays current for citation checks and hallucination defense. Reconcile is idempotent — only PDFs without a matching .md are converted (existing .md files are skipped); raw PDFs are never modified. Delegates the actual conversion to the gemini-pdf skill (Antigravity CLI / agy vision pathway). Triggers include "sync the literature folder", "convert new literature PDFs", "I dropped a paper in literature", "update the reference library", "generate bibtex for my papers", "backfill the .bib files", and "PDF to markdown for my citations".
---

# literature-sync

Keep `literature/md/` and `literature/bib/` in sync with `literature/pdf/`. Drop a paper
PDF into the source folder; this skill finds every PDF that has no matching Markdown yet,
converts it one at a time using the `gemini-pdf` skill, then completes its bibliographic
metadata from Crossref and writes a `.bib` sidecar. It is a thin orchestrator — it does
**not** reimplement conversion.

## When to use

- You added one or more paper PDFs to `literature/pdf/` and want the `.md` + `.bib` versions.
- At session start, to catch anything added since last time.
- Before a citation check, to make sure the reference library is complete.
- To backfill `.bib` files for an already-converted library (`--enrich-only`).

## Prerequisite

The **`gemini-pdf`** skill must be installed (from Kasahara's `claude-code-skills`), and
`agy` (Antigravity CLI) must be signed in. This skill locates `gemini-pdf` automatically at
`$CLAUDE_PLUGIN_ROOT/skills/gemini-pdf` or `~/.claude/skills/gemini-pdf`.

Enrichment needs `python3` (stdlib only — no pip install) and outbound access to
`api.crossref.org`. Both are optional: without them, conversion still works and the
enrichment step is skipped with a warning. `--enrich-only` does **not** need `gemini-pdf`
or `agy` at all.

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

# Convert + enrich + write .bib (sequential; ~1-4 min per chunk). --yes is required.
bash "$LIT/scripts/sync_literature.sh" --yes

# Backfill .bib for a library that is already converted
bash "$LIT/scripts/sync_literature.sh" --enrich-only --yes

# Custom folders / Crossref polite-pool contact
bash "$LIT/scripts/sync_literature.sh" --src literature/pdf --out literature/md \
     --bib-dir literature/bib --mailto you@example.org --yes

# Papers with no DOI: attempt a title search (results are flagged UNVERIFIED)
bash "$LIT/scripts/sync_literature.sh" --enrich-only --search-fallback --yes
```

## How it works

```
find literature/pdf/ -iname '*.pdf'
  for each PDF whose literature/md/<same-name>.md is MISSING:
      gemini-pdf/scripts/pdf_to_markdown.sh  <pdf>  <md>
      stash gemini-pdf's .meta.json / .quality.json / .err into literature/logs/sidecars/
      enrich_metadata.py --md <md>            # Crossref lookup by DOI
          -> completes the front matter (volume, number, pages, publisher, ...)
          -> writes literature/bib/<same-name>.bib
  (existing .md are skipped; subfolder structure under pdf/ is mirrored under md/ and bib/)
log every action to literature/logs/literature_sync.log
print a COUNT-ONLY summary (converted / skipped / failed)
```

- **Sequential by design.** `agy` hangs when run in parallel, so conversions run one at a
  time. Dropping 20 PDFs is fine; they process in series (~1-4 min per chunk each).
- **Preview by default.** Without `--yes` the script only lists pending files and exits —
  no conversion, no API calls. Pass `--yes` to actually run.
- **Idempotent.** Re-running only picks up genuinely new/missing files. Enrichment records
  a `crossref:` marker in the front matter and skips already-processed papers unless
  `--refresh` is passed.

## Metadata enrichment

`gemini-pdf` writes a five-field front matter (`title`, `authors`, `year`, `journal`,
`doi`). Volume, issue and pages are deliberately **not** asked of the model:

- they are frequently absent from the printed PDF (accepted versions, working papers,
  preprints), so a faithful transcription simply omits them;
- they are numeric and therefore the fields most damaged by OCR;
- unlike the rest, they have an authoritative external source.

So `enrich_metadata.py` takes the DOI from the front matter, queries Crossref, and fills in
`volume` / `number` / `pages` / `publisher`, correcting the venue name and author list at
the same time. Crossref wins on conflict and every overwritten value is logged, so the diff
stays auditable. The paper body is never touched — only the front matter block.

The `.bib` entry is written either way. Its first line records provenance:

```
% source: Crossref (10.1257/aer.20191234)
% source: front matter — no DOI, UNVERIFIED
% source: Crossref title search (similarity 0.94) — VERIFY BEFORE CITING
```

Entry type follows the Crossref work type (`journal-article` → `@article`, `report` →
`@techreport`, `proceedings-article` → `@inproceedings`, …), falling back to venue-name
heuristics when Crossref has nothing. The BibTeX key is the **file name**, matching
`file = {KEY.pdf}` and the key→source mapping `citation-check` relies on. Keep filenames in
a citable form (`andrews-1999-ecma.pdf`), not `2401.12345v2.pdf`.

**Failure is non-fatal.** If Crossref is unreachable, the `.md` is left untouched, no
marker is written, and the run exits 0 — the paper is simply retried next time.

## Local `.bib` vs. the central reference library

These are two separate things and only the first is on by default.

| | scope | default |
|---|---|---|
| `literature/bib/*.bib` | inside the project | **on** (`--no-enrich` to disable) |
| `GEMINI_PDF_REFERENCE_DIR` | shared global library | **off** (`--bib` to enable) |

The central library stays opt-in on purpose: its keys are filename-derived, so identically
named papers in different subfolders collide, and its bib entries are never replaced once
written — a wrong entry there is not recoverable through this pipeline. The local `.bib`
has neither problem: delete it and re-run.

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
| `--bib-dir` / `LIT_BIB_DIR` | `literature/bib` | Where `.bib` sidecars are written |
| `--mailto` / `CROSSREF_MAILTO` | (unset) | Contact address for the Crossref polite pool |
| `--yes` | (off) | Actually run; without it the script previews and exits |
| `--no-enrich` | (off) | Skip Crossref lookup and `.bib` generation |
| `--search-fallback` | (off) | For papers with no DOI, try a Crossref title search |
| `--refresh` | (off) | Re-query Crossref for already-enriched files |
| `--enrich-only` | (off) | No conversion; enrich/backfill the existing `.md` tree |
| `--bib` | (off) | Also sync into the central library (needs `GEMINI_PDF_REFERENCE_DIR`) |
| `LIT_LOG_DIR` | `literature/logs` | Log destination |

## Security / discipline

- `literature/pdf/` is treated as **read-only**; this skill never edits or deletes PDFs.
- No destructive shell ops. No `rm -rf`.
- Claude does **not** read PDF/MD bodies into context — only counts, logs, and (at most) the
  10-line YAML frontmatter of a converted file.
- Conversion sends documents to Google via `agy`. Do not place confidential or embargoed
  PDFs here. Never commit API keys.
- Crossref queries send only the DOI (or, with `--search-fallback`, the title and first two
  author names) — never the document.
- Figures in converted markdown are caption-only placeholders; verify any figure-based claim
  against the original PDF. The same applies to a `.bib` marked `UNVERIFIED`.

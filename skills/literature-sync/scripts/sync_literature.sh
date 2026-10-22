#!/usr/bin/env bash
# literature-sync: convert every PDF in the source dir that lacks a matching
# Markdown file, delegating conversion to the gemini-pdf skill's pipeline, then
# enrich the result's front matter from Crossref and write a local .bib.
#
# Engine (--engine / LIT_ENGINE):
#   claude (default) — gemini-pdf's pipeline runs unchanged, but its `agy` calls
#                      are routed to headless Claude Code (`claude -p`) through
#                      scripts/claude-engine/agy. Model: LIT_CLAUDE_MODEL (sonnet).
#   gemini           — the original Antigravity CLI (agy) path.
#
# Idempotent: existing .md files are skipped. Raw PDFs are never modified or deleted.
# Sequential by design (agy hangs in parallel; Claude shares one usage limit).
# Prints a count-only summary.
set -euo pipefail

# ---- Config (override via env or flags) -------------------------------------
SRC_DIR="${LIT_SRC_DIR:-literature/pdf}"   # where PDFs are dropped
OUT_DIR="${LIT_OUT_DIR:-literature/md}"    # where .md files are written
BIB_DIR="${LIT_BIB_DIR:-literature/bib}"   # where .bib sidecars are written
LOG_DIR="${LIT_LOG_DIR:-literature/logs}"
MAILTO="${CROSSREF_MAILTO:-}"              # Crossref polite-pool contact
AUTO_YES=0
BIB_SYNC=0          # --bib : opt-in sync to the CENTRAL reference library
ENRICH=1            # local Crossref enrichment + .bib sidecar (on by default)
ENRICH_ONLY=0
SEARCH_FALLBACK=0
REFRESH=0
ENGINE="${LIT_ENGINE:-claude}"             # claude | gemini

usage() {
  cat <<'EOF'
Usage: sync_literature.sh [--src DIR] [--out DIR] [--bib-dir DIR] [--mailto ADDR]
                          [--no-enrich] [--search-fallback] [--refresh]
                          [--enrich-only] [--bib] [--engine claude|gemini] [--yes]

  --src DIR          source folder of PDFs        (default: literature/pdf)
  --out DIR          output folder for .md        (default: literature/md)
  --bib-dir DIR      output folder for .bib       (default: literature/bib)
  --mailto ADDR      contact address for the Crossref polite pool
  --no-enrich        skip Crossref enrichment and .bib generation
  --search-fallback  for papers with no DOI, try a Crossref title search
                     (result is flagged UNVERIFIED — always check it)
  --refresh          re-query Crossref even for already-enriched files
  --enrich-only      no conversion; enrich/refresh the existing .md tree only
  --bib              ALSO sync each result into the central gemini-pdf reference
                     library (requires GEMINI_PDF_REFERENCE_DIR). Off by default:
                     that library is shared global state and its bib entries are
                     never replaced once written.
  --engine NAME      conversion engine: claude (default) or gemini.
                     claude routes gemini-pdf's model calls to `claude -p`
                     (model: LIT_CLAUDE_MODEL, default sonnet; effort:
                     LIT_CLAUDE_EFFORT, default low). gemini uses agy.
  --yes              actually run (without it, the script previews and exits)

Without --yes, the script only lists pending work and exits (no API calls).
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --src) SRC_DIR="$2"; shift 2 ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    --bib-dir) BIB_DIR="$2"; shift 2 ;;
    --mailto) MAILTO="$2"; shift 2 ;;
    --no-enrich) ENRICH=0; shift ;;
    --search-fallback) SEARCH_FALLBACK=1; shift ;;
    --refresh) REFRESH=1; shift ;;
    --enrich-only) ENRICH_ONLY=1; shift ;;
    --bib) BIB_SYNC=1; shift ;;
    --engine) ENGINE="$2"; shift 2 ;;
    --yes) AUTO_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

case "$ENGINE" in
  claude|gemini) ;;
  *) echo "unknown engine: $ENGINE (use claude or gemini)" >&2; exit 2 ;;
esac

HERE="$(cd "$(dirname "$0")" && pwd)"
ENRICHER="$HERE/enrich_metadata.py"
PYTHON="$(command -v python3 || command -v python || true)"

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/literature_sync.log"

# ---- Shared: build the enricher's argument list ------------------------------
_enrich_args() {
  printf '%s\n' --bib-dir "$BIB_DIR" --md-dir "$OUT_DIR"
  [ -n "$MAILTO" ] && printf '%s\n' --mailto "$MAILTO"
  [ "$SEARCH_FALLBACK" -eq 1 ] && printf '%s\n' --search-fallback
  [ "$REFRESH" -eq 1 ] && printf '%s\n' --refresh
  return 0
}

_enrich_ready() {
  [ "$ENRICH" -eq 1 ] || return 1
  if [ -z "$PYTHON" ]; then
    echo "WARN: python3 not found — skipping enrichment/.bib" >&2; return 1
  fi
  if [ ! -f "$ENRICHER" ]; then
    echo "WARN: $ENRICHER not found — skipping enrichment/.bib" >&2; return 1
  fi
  return 0
}

# ---- --enrich-only: no conversion, no agy, no gemini-pdf needed --------------
if [ "$ENRICH_ONLY" -eq 1 ]; then
  [ -d "$OUT_DIR" ] || { echo "No md dir: $OUT_DIR  (nothing to do)"; exit 0; }
  _enrich_ready || exit 1

  total=$(find "$OUT_DIR" -type f -name '*.md' | wc -l | tr -d ' ')
  nobib=0
  while IFS= read -r -d '' md; do
    rel="${md#"$OUT_DIR"/}"; bib="$BIB_DIR/${rel%.md}.bib"
    [ -f "$bib" ] || nobib=$((nobib+1))
  done < <(find "$OUT_DIR" -type f -name '*.md' -print0)

  echo "Markdown: $OUT_DIR    Bib: $BIB_DIR"
  echo "MD files: $total    Missing .bib: $nobib"
  if [ "$AUTO_YES" -ne 1 ]; then
    echo
    echo "Preview only. Re-run with --yes to query Crossref and write .bib files."
    exit 0
  fi
  mapfile -t EARGS < <(_enrich_args)
  echo "[$(date -u +%FT%TZ)] enrich-only over $OUT_DIR" | tee -a "$LOG"
  "$PYTHON" "$ENRICHER" --batch "${EARGS[@]}" 2>>"$LOG"
  exit 0
fi

# ---- Locate the gemini-pdf skill --------------------------------------------
# Search order:
#   1. GEMINI_PDF_SKILL_DIR  (explicit env override)
#   2. $CLAUDE_PLUGIN_ROOT/skills/gemini-pdf  (same-plugin layout)
#   3. ~/.claude/skills/gemini-pdf            (manual copy)
#   4. ~/.claude/plugins/** (plugin-install cache: find pdf_to_markdown.sh)
GEMINI_PDF=""
if [ -n "${GEMINI_PDF_SKILL_DIR:-}" ] && [ -d "$GEMINI_PDF_SKILL_DIR" ]; then
  GEMINI_PDF="$GEMINI_PDF_SKILL_DIR"
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -d "$CLAUDE_PLUGIN_ROOT/skills/gemini-pdf" ]; then
  GEMINI_PDF="$CLAUDE_PLUGIN_ROOT/skills/gemini-pdf"
elif [ -d "$HOME/.claude/skills/gemini-pdf" ]; then
  GEMINI_PDF="$HOME/.claude/skills/gemini-pdf"
else
  hit="$(find "$HOME/.claude/plugins" -type f -name pdf_to_markdown.sh -path '*gemini-pdf*' 2>/dev/null | head -1 || true)"
  if [ -n "$hit" ]; then
    GEMINI_PDF="$(cd "$(dirname "$hit")/.." && pwd)"
  fi
fi
if [ -z "$GEMINI_PDF" ]; then
  echo "ERROR: gemini-pdf skill not found." >&2
  echo "       Install it (plugin: gemini-pdf@kasahara-skills, or copy to ~/.claude/skills/)," >&2
  echo "       or point GEMINI_PDF_SKILL_DIR at its folder. Then sign in to agy." >&2
  exit 1
fi
CONVERT="$GEMINI_PDF/scripts/pdf_to_markdown.sh"
[ -f "$CONVERT" ] || { echo "ERROR: converter not found at $CONVERT" >&2; exit 1; }

# ---- Engine setup -----------------------------------------------------------
# The claude engine puts an `agy` shim first on PATH (for the converter only),
# so the upstream pipeline is reused unmodified. GEMINI_PDF_MODEL is set to the
# Claude model so the converter's own log names the model actually used.
LIMIT_FLAG=""
if [ "$ENGINE" = "claude" ]; then
  SHIM_DIR="$HERE/claude-engine"
  [ -x "$SHIM_DIR/agy" ] || chmod +x "$SHIM_DIR/agy" 2>/dev/null || true
  [ -f "$SHIM_DIR/agy" ] || { echo "ERROR: claude shim missing at $SHIM_DIR/agy" >&2; exit 1; }
  if [ "$AUTO_YES" -eq 1 ] && ! command -v claude >/dev/null 2>&1; then
    echo "ERROR: --engine claude needs the Claude Code CLI ('claude') on PATH." >&2
    echo "       Use --engine gemini to convert with agy instead." >&2
    exit 1
  fi
  CLAUDE_MODEL="${LIT_CLAUDE_MODEL:-sonnet}"
  LIMIT_FLAG="$(mktemp "${TMPDIR:-/tmp}/lit-claude-limit.XXXXXX")"
  rm -f "$LIMIT_FLAG"
  trap 'rm -f "$LIMIT_FLAG"' EXIT
  ENGINE_DESC="claude ($CLAUDE_MODEL, effort ${LIT_CLAUDE_EFFORT-low})"
  _convert() {
    PATH="$SHIM_DIR:$PATH" GEMINI_PDF_MODEL="$CLAUDE_MODEL" \
      LIT_CLAUDE_MODEL="$CLAUDE_MODEL" LIT_CLAUDE_LIMIT_FLAG="$LIMIT_FLAG" \
      bash "$CONVERT" "$@"
  }
else
  ENGINE_DESC="gemini (agy, ${GEMINI_PDF_MODEL:-gemini-pdf default model})"
  _convert() { bash "$CONVERT" "$@"; }
fi

# ---- Guards -----------------------------------------------------------------
if [ ! -d "$SRC_DIR" ]; then
  echo "No source dir: $SRC_DIR  (nothing to do)"
  exit 0
fi
mkdir -p "$OUT_DIR"

# ---- Stash converter sidecars out of the md tree ----------------------------
# gemini-pdf writes <base>.meta.json / <base>.quality.json / <base>.err next to
# each converted .md. These are conversion diagnostics, not literature: the
# .md is the only artifact that belongs in literature/md/. Move the sidecars
# under literature/logs/sidecars/ (logs/ is gitignored, so nothing extra is
# tracked and only .md stays in the reference tree). Subfolder structure under
# md/ is mirrored, so identically named papers in different folders never clash.
_stash_sidecars() {
  local md="$1" rel reldir base dest f moved=0
  rel="${md#"$OUT_DIR"/}"
  reldir="$(dirname "$rel")"
  base="$(basename "${md%.md}")"
  dest="$LOG_DIR/sidecars/$reldir"
  for ext in meta.json quality.json err; do
    f="${md%.md}.$ext"
    if [ -f "$f" ]; then
      mkdir -p "$dest"
      mv -f "$f" "$dest/$base.$ext"
      moved=1
    fi
  done
  [ "$moved" -eq 1 ] && echo "[$(date -u +%FT%TZ)] stashed sidecars -> $dest/$base.*" >>"$LOG"
  return 0
}

# ---- Enrich one converted file (never fatal) --------------------------------
# Volume / issue / pages are fetched from Crossref via the DOI rather than asked
# of the LLM: they are often absent from the printed PDF and are the numeric
# fields most damaged by OCR. A .bib sidecar is written either way; entries not
# confirmed by Crossref are marked UNVERIFIED in a leading comment.
_enrich_one() {
  local md="$1" eargs
  _enrich_ready || return 0
  mapfile -t eargs < <(_enrich_args)
  if ! "$PYTHON" "$ENRICHER" --md "$md" "${eargs[@]}" >>"$LOG" 2>&1; then
    echo "  WARN: enrichment failed for $md (see $LOG)"
  fi
  return 0
}

# ---- Find PDFs without a matching .md (mirror subfolder structure) ----------
PDFS=()
while IFS= read -r -d '' f; do PDFS+=("$f"); done \
  < <(find "$SRC_DIR" -type f -iname '*.pdf' -print0 | sort -z)

TODO=()
for pdf in "${PDFS[@]}"; do
  rel="${pdf#"$SRC_DIR"/}"        # path relative to SRC_DIR
  md="$OUT_DIR/${rel%.[Pp][Dd][Ff]}.md"
  [ -f "$md" ] || TODO+=("$pdf|$md")
done

N=${#TODO[@]}
echo "Source: $SRC_DIR    Output: $OUT_DIR    Bib: $BIB_DIR"
echo "Engine: $ENGINE_DESC"
echo "PDFs found: ${#PDFS[@]}    Need conversion: $N"
if [ "$N" -eq 0 ]; then
  echo "Everything already converted."
  echo "(To backfill .bib for the existing library: --enrich-only --yes)"
  exit 0
fi

echo "Pending:"
for item in "${TODO[@]}"; do echo "  - ${item%%|*}"; done

# ---- Preview unless --yes (no conversion, no API calls without --yes) --------
if [ "$AUTO_YES" -ne 1 ]; then
  echo
  echo "Preview only. $N file(s) would be converted sequentially with $ENGINE_DESC (~1-4 min per chunk each)."
  [ "$ENRICH" -eq 1 ] && echo "Each result would then be enriched from Crossref and given a .bib in $BIB_DIR."
  echo "Re-run with --yes to convert."
  exit 0
fi

# ---- Convert ----------------------------------------------------------------
# A partial .md written while the usage limit hit would be mistaken for a
# finished conversion on the next run (existing .md files are skipped), so it
# is moved aside to logs/ and the PDF stays pending.
_quarantine_partial() {
  local md="$1" dest="$LOG_DIR/partial"
  [ -f "$md" ] || return 0
  mkdir -p "$dest"
  mv -f "$md" "$dest/$(basename "$md")"
  echo "[$(date -u +%FT%TZ)] usage limit: partial output moved to $dest/" >>"$LOG"
}

ok=0; fail=0; stopped=0
for item in "${TODO[@]}"; do
  pdf="${item%%|*}"; md="${item##*|}"
  mkdir -p "$(dirname "$md")"
  echo "[$(date -u +%FT%TZ)] convert [$ENGINE]: $pdf -> $md" | tee -a "$LOG"
  extra=()
  [ "$BIB_SYNC" -eq 1 ] && extra=(--bib-key "$(basename "${md%.md}")")
  if _convert "$pdf" "$md" ${extra[@]+"${extra[@]}"} >>"$LOG" 2>&1; then rc=0; else rc=1; fi
  if [ -n "$LIMIT_FLAG" ] && [ -f "$LIMIT_FLAG" ]; then
    _stash_sidecars "$md"; _quarantine_partial "$md"
    stopped=$(( N - ok - fail ))
    echo "  STOPPED: Claude usage limit reached. $stopped file(s) left pending; re-run after the limit resets." | tee -a "$LOG"
    break
  fi
  if [ "$rc" -eq 0 ]; then
    ok=$((ok+1)); _stash_sidecars "$md"; _enrich_one "$md"
  else
    fail=$((fail+1)); echo "  FAILED (see $LOG)"
  fi
done

echo "Done. converted=$ok  failed=$fail  pending=$stopped  log=$LOG"
[ "$fail" -eq 0 ] && [ "$stopped" -eq 0 ]

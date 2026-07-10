#!/usr/bin/env bash
# literature-sync: convert every PDF in the source dir that lacks a matching
# Markdown file, delegating conversion to the gemini-pdf skill (agy / Antigravity).
#
# Idempotent: existing .md files are skipped. Raw PDFs are never modified or deleted.
# Sequential by design (agy hangs in parallel). Prints a count-only summary.
set -euo pipefail

# ---- Config (override via env or flags) -------------------------------------
SRC_DIR="${LIT_SRC_DIR:-literature/pdf}"   # where PDFs are dropped
OUT_DIR="${LIT_OUT_DIR:-literature/md}"    # where .md files are written
LOG_DIR="${LIT_LOG_DIR:-literature/logs}"
AUTO_YES=0
BIB_SYNC=0

usage() {
  cat <<'EOF'
Usage: sync_literature.sh [--src DIR] [--out DIR] [--bib] [--yes]
  --src DIR   source folder of PDFs      (default: literature/pdf)
  --out DIR   output folder for .md      (default: literature/md)
  --bib       also sync each result into the gemini-pdf reference library
              (requires GEMINI_PDF_REFERENCE_DIR to be set)
  --yes       actually convert (without it, the script previews and exits)
Without --yes, the script only lists pending files and exits (no API calls).
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --src) SRC_DIR="$2"; shift 2 ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    --bib) BIB_SYNC=1; shift ;;
    --yes) AUTO_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

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

# ---- Guards -----------------------------------------------------------------
if [ ! -d "$SRC_DIR" ]; then
  echo "No source dir: $SRC_DIR  (nothing to do)"
  exit 0
fi
mkdir -p "$OUT_DIR" "$LOG_DIR"
LOG="$LOG_DIR/literature_sync.log"

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
echo "Source: $SRC_DIR    Output: $OUT_DIR"
echo "PDFs found: ${#PDFS[@]}    Need conversion: $N"
if [ "$N" -eq 0 ]; then
  echo "Everything already converted."
  exit 0
fi

echo "Pending:"
for item in "${TODO[@]}"; do echo "  - ${item%%|*}"; done

# ---- Preview unless --yes (no conversion, no API calls without --yes) --------
if [ "$AUTO_YES" -ne 1 ]; then
  echo
  echo "Preview only. $N file(s) would be converted sequentially (~1-4 min per chunk each)."
  echo "Re-run with --yes to convert."
  exit 0
fi

# ---- Convert ----------------------------------------------------------------
ok=0; fail=0
for item in "${TODO[@]}"; do
  pdf="${item%%|*}"; md="${item##*|}"
  mkdir -p "$(dirname "$md")"
  echo "[$(date -u +%FT%TZ)] convert: $pdf -> $md" | tee -a "$LOG"
  if [ "$BIB_SYNC" -eq 1 ]; then
    key="$(basename "${md%.md}")"
    if bash "$CONVERT" "$pdf" "$md" --bib-key "$key" >>"$LOG" 2>&1; then
      ok=$((ok+1)); _stash_sidecars "$md"
    else
      fail=$((fail+1)); echo "  FAILED (see $LOG)"
    fi
  else
    if bash "$CONVERT" "$pdf" "$md" >>"$LOG" 2>&1; then
      ok=$((ok+1)); _stash_sidecars "$md"
    else
      fail=$((fail+1)); echo "  FAILED (see $LOG)"
    fi
  fi
done

echo "Done. converted=$ok  failed=$fail  log=$LOG"
[ "$fail" -eq 0 ]

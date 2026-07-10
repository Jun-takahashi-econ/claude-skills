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

# ---- Locate the gemini-pdf skill (plugin install or manual copy) ------------
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -d "$CLAUDE_PLUGIN_ROOT/skills/gemini-pdf" ]; then
  GEMINI_PDF="$CLAUDE_PLUGIN_ROOT/skills/gemini-pdf"
elif [ -d "$HOME/.claude/skills/gemini-pdf" ]; then
  GEMINI_PDF="$HOME/.claude/skills/gemini-pdf"
else
  echo "ERROR: gemini-pdf skill not found." >&2
  echo "       Install it first from Kasahara's claude-code-skills," >&2
  echo "       then sign in to Antigravity CLI (agy)." >&2
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
      ok=$((ok+1))
    else
      fail=$((fail+1)); echo "  FAILED (see $LOG)"
    fi
  else
    if bash "$CONVERT" "$pdf" "$md" >>"$LOG" 2>&1; then
      ok=$((ok+1))
    else
      fail=$((fail+1)); echo "  FAILED (see $LOG)"
    fi
  fi
done

echo "Done. converted=$ok  failed=$fail  log=$LOG"
[ "$fail" -eq 0 ]

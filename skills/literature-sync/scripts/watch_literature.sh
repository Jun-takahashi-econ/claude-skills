#!/usr/bin/env bash
# Optional file watcher (macOS/Linux). Runs a debounced literature-sync whenever
# a PDF is created or moved into the source folder. Ctrl-C to stop.
#
# macOS:  brew install fswatch
# Windows: not supported here — use the CLAUDE.md session-start trigger instead,
#          or schedule sync_literature.sh via Task Scheduler.
set -euo pipefail

SRC_DIR="${LIT_SRC_DIR:-literature/pdf}"
HERE="$(cd "$(dirname "$0")" && pwd)"

command -v fswatch >/dev/null 2>&1 || {
  echo "fswatch not found. Install it: brew install fswatch" >&2
  exit 1
}
[ -d "$SRC_DIR" ] || { echo "Source dir does not exist: $SRC_DIR" >&2; exit 1; }

echo "Watching $SRC_DIR for new PDFs (Ctrl-C to stop)..."
# --latency 5 debounces bursts so a multi-file drop triggers one sync, not many.
fswatch -o --latency 5 --event Created --event Renamed --event Updated "$SRC_DIR" \
  | while read -r _; do
      echo "[$(date -u +%FT%TZ)] change detected -> running sync"
      bash "$HERE/sync_literature.sh" --yes || echo "sync returned non-zero (see log)"
    done

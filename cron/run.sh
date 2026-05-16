#!/bin/bash
# Entrypoint del cron: scrapea la cartelera y deja logs.
# Probar a mano:  bash cron/run.sh
set -euo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$PROJ/data/cron.log"
PY="$(command -v python3)"

cd "$PROJ"
{
  echo "==== $(date '+%Y-%m-%d %H:%M:%S') ===="
  "$PY" scrape.py --workers 8
  echo ""
} >> "$LOG" 2>&1

# rotar log si supera ~2MB
if [ "$(wc -c < "$LOG")" -gt 2000000 ]; then
  tail -n 400 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

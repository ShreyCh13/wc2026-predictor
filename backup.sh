#!/bin/zsh
# Daily SQLite backup + log trim for the WC2026 predictor. Keeps last 7 backups.
APP=/Users/admin/agents/apps/wc2026
BK=$APP/data/backups
mkdir -p "$BK"
TS=$(date +%Y%m%d-%H%M%S)
/usr/bin/sqlite3 "$APP/data/wc2026.db" ".backup '$BK/wc2026-$TS.db'" && echo "[$(date)] backup -> wc2026-$TS.db"
# prune to the 7 most recent
ls -1t "$BK"/wc2026-*.db 2>/dev/null | tail -n +8 | while read f; do rm -f "$f"; done
# truncate noisy logs over 5MB
for f in /Users/admin/agents/logs/wc2026.err.log /Users/admin/agents/logs/wc2026.update.out.log /Users/admin/agents/logs/wc2026.out.log; do
  [ -f "$f" ] && [ "$(stat -f%z "$f")" -gt 5242880 ] && : > "$f" && echo "[$(date)] trimmed $f"
done
exit 0   # a clean run must report success (prune pipeline's tail status is not a failure)

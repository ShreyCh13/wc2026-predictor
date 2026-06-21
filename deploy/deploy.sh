#!/bin/zsh
# Deploy the WC2026 Predictor to the Mac mini and (re)load its launchd services.
# The repo keeps a tidy structure; the mini runs a flat copy under $APP. This script
# bridges the two. Idempotent — safe to run repeatedly.
set -e

MINI="${MINI:-mini}"                                   # ssh alias for the Mac mini
APP="/Users/admin/agents/apps/wc2026"                  # runtime dir on the mini
LA="/Users/admin/Library/LaunchAgents"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"               # repo root

echo "→ copying app files to $MINI:$APP"
ssh "$MINI" "mkdir -p $APP/data"
scp "$ROOT"/server.py "$ROOT"/update_results.py "$ROOT"/index.html \
    "$ROOT"/fixtures_seed.json "$ROOT"/deploy/backup.sh "$MINI":"$APP"/

echo "→ installing launchd plists"
scp "$ROOT"/deploy/com.shrey.wc2026*.plist "$MINI":"$LA"/

echo "→ reloading services"
ssh "$MINI" '
  chmod +x /Users/admin/agents/apps/wc2026/backup.sh
  launchctl kickstart -k gui/501/com.shrey.wc2026
  for j in update backup; do
    launchctl bootout gui/501/com.shrey.wc2026.$j 2>/dev/null || true
    launchctl bootstrap gui/501 /Users/admin/Library/LaunchAgents/com.shrey.wc2026.$j.plist
  done
  sleep 2
  echo -n "health: "; curl -s http://127.0.0.1:8790/api/health
'
echo "\n✓ deployed."

#!/usr/bin/env bash
# Daily backup of the SQLite DB, usage and agent config. Cron: 15 3 * * * /opt/devagent/deploy/vps/backup.sh
set -euo pipefail
DEST="${BACKUP_DIR:-/srv/devagent/backups}"
STAMP="$(date +%Y%m%d-%H%M)"
mkdir -p "$DEST"
sqlite3 /srv/devagent/data/devagent.db ".backup '$DEST/devagent-$STAMP.db'"
tar -czf "$DEST/config-$STAMP.tgz" -C /opt/devagent config /srv/devagent/data/usage.json 2>/dev/null || true
find "$DEST" -type f -mtime +14 -delete
echo "backup ok: $DEST/devagent-$STAMP.db"

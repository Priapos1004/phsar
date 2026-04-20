#!/usr/bin/env bash
# Pull backup dumps from the production VM to the local machine.
#
# Manual off-host safety net — the VM's /opt/phsar/backups survives container
# rebuilds but NOT VM loss. Run this every month or two, and before any risky
# restore, to keep a laptop-local copy.
#
# Usage: scripts/pull-backups.sh [user@host] [remote-path] [local-path]
# Defaults: user@host from $PHSAR_VM, remote /opt/phsar/backups/, local ./backups-local/

set -euo pipefail

REMOTE_HOST="${1:-${PHSAR_VM:-}}"
REMOTE_PATH="${2:-/opt/phsar/backups/}"
LOCAL_PATH="${3:-./backups-local/}"

if [ -z "$REMOTE_HOST" ]; then
  echo "Error: no remote host." >&2
  echo "Pass user@host as the first arg, or set PHSAR_VM." >&2
  exit 1
fi

mkdir -p "$LOCAL_PATH"

echo "Pulling backups from ${REMOTE_HOST}:${REMOTE_PATH} -> ${LOCAL_PATH}"
rsync -av --progress "${REMOTE_HOST}:${REMOTE_PATH}" "$LOCAL_PATH"
echo "Done. Local copies:"
ls -lh "$LOCAL_PATH" | tail -n +2

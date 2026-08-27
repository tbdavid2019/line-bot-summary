#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$DIR/auto_sync.log"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

cd "$DIR"

# 抓取遠端分支狀態
git fetch origin main --quiet || {
    log "Error: Failed to fetch origin/main"
    exit 1
}

LOCAL_HASH=$(git rev-parse HEAD)
REMOTE_HASH=$(git rev-parse origin/main)

if [ "$LOCAL_HASH" != "$REMOTE_HASH" ]; then
    log "New commits detected on origin/main ($LOCAL_HASH -> $REMOTE_HASH). Pulling and rebuilding..."
    git pull origin main
    chmod +x build.sh
    ./build.sh
    log "Repository successfully updated and container redeployed to commit $REMOTE_HASH!"
fi

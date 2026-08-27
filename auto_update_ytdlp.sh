#!/bin/bash
set -euo pipefail

CONTAINER_NAME="line-bot-summary123"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$DIR/auto_update_ytdlp.log"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

latest_pypi_version() {
    python3 <<'PY'
import json
import urllib.request
try:
    with urllib.request.urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=20) as r:
        data = json.load(r)
    print(data.get("info", {}).get("version", ""))
except Exception as e:
    print("")
PY
}

log "Starting yt-dlp version check..."
LATEST_VERSION=$(latest_pypi_version)

if [ -z "$LATEST_VERSION" ]; then
    log "Warning: Could not fetch latest yt-dlp version from PyPI."
    exit 0
fi

log "Latest PyPI yt-dlp version: $LATEST_VERSION"

if docker ps -q -f name="^${CONTAINER_NAME}$" | grep -q .; then
    CURRENT_VERSION=$(docker exec "$CONTAINER_NAME" python3 -m yt_dlp --version 2>/dev/null || echo "unknown")
else
    CURRENT_VERSION="none"
fi

log "Current container yt-dlp version: $CURRENT_VERSION"

if [ "$CURRENT_VERSION" != "$LATEST_VERSION" ]; then
    log "yt-dlp version mismatch ($CURRENT_VERSION != $LATEST_VERSION). Updating inside container..."
    if docker ps -q -f name="^${CONTAINER_NAME}$" | grep -q .; then
        docker exec "$CONTAINER_NAME" pip install --no-cache-dir -U --pre "yt-dlp[default]"
        NEW_VER=$(docker exec "$CONTAINER_NAME" python3 -m yt_dlp --version 2>/dev/null || echo "$LATEST_VERSION")
        log "yt-dlp updated to $NEW_VER inside running container!"
    else
        log "Container not running. Rebuilding container from scratch..."
        cd "$DIR"
        chmod +x build.sh
        ./build.sh
    fi
else
    log "yt-dlp is already at the latest version ($CURRENT_VERSION). No update needed."
fi

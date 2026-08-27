#!/bin/bash
# ==============================================================================
# Extract YouTube cookies from Chrome container and sync to line-bot-summary
# ==============================================================================
set -euo pipefail

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHROME_DATA_DIR="/home/bitnami/chrome-data"
CONTAINER_NAME="line-bot-summary123"
LOG_FILE="$BOT_DIR/cookies_sync.log"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "Starting YouTube cookie extraction from Chrome container..."

# 1. 確保 Chrome 容器內的 yt-dlp 為最新
if docker ps -q -f name="^chrome$" | grep -q .; then
    log "Updating yt-dlp inside chrome container..."
    docker exec chrome /lsiopy/bin/python3 -m pip install -q -U yt-dlp || true

    # 2. 從 Chrome 使用者設定檔中提取 cookies
    log "Extracting cookies from Chrome browser profile..."
    docker exec chrome /lsiopy/bin/python3 -m yt_dlp \
        --cookies-from-browser chrome:/config/.config/google-chrome \
        --cookies /config/youtube_cookies.txt \
        --no-playlist --playlist-items 0 \
        --skip-download "https://www.youtube.com" > /dev/null 2>&1 || true

    # 3. 檢查提取出的 cookies 檔案
    if [ -s "$CHROME_DATA_DIR/youtube_cookies.txt" ]; then
        COOKIE_COUNT=$(wc -l < "$CHROME_DATA_DIR/youtube_cookies.txt")
        log "Cookies extracted successfully ($COOKIE_COUNT lines). Syncing to bot..."

        # 複製到專案目錄
        cp "$CHROME_DATA_DIR/youtube_cookies.txt" "$BOT_DIR/cookies.txt"
        chmod 644 "$BOT_DIR/cookies.txt"

        # 若容器正在運行，同步複製一份至容器內部
        if docker ps -q -f name="^${CONTAINER_NAME}$" | grep -q .; then
            docker cp "$BOT_DIR/cookies.txt" "${CONTAINER_NAME}:/app/cookies.txt" || true
            log "Synced cookies.txt to running container ${CONTAINER_NAME}."
        fi

        # 清理 chrome-data 暫存
        rm -f "$CHROME_DATA_DIR/youtube_cookies.txt"
        log "YouTube cookies extraction and sync completed successfully!"
    else
        log "Warning: Extracted cookie file is empty or not found at $CHROME_DATA_DIR/youtube_cookies.txt"
    fi
else
    log "Error: Chrome container is not running!"
    exit 1
fi

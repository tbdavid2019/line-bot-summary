#!/bin/bash
# Description: Set up headless Chrome/Chromium container for extracting fresh YouTube cookies
# Author: Antigravity

CHROME_DATA_DIR="${CHROME_DATA_DIR:-/home/bitnami/chrome-data}"
CONTAINER_NAME="chrome"

echo "=========================================================="
echo " Setting up Headless Chrome Container for YouTube Cookies"
echo "=========================================================="

# 1. 建立 Chrome 數據儲存目錄
echo "[1/4] Creating Chrome data directory at $CHROME_DATA_DIR..."
mkdir -p "$CHROME_DATA_DIR"
chmod -R 777 "$CHROME_DATA_DIR"

# 2. 啟動 Chrome / Chromium 容器
echo "[2/4] Pulling and running lscr.io/linuxserver/chromium image..."
docker stop $CONTAINER_NAME 2>/dev/null || true
docker rm $CONTAINER_NAME 2>/dev/null || true

docker run -d \
  --name=$CONTAINER_NAME \
  --security-opt seccomp=unconfined \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=Asia/Taipei \
  -e CHROME_CLI=https://www.youtube.com \
  -p 3000:3000 \
  -v "$CHROME_DATA_DIR:/config" \
  --restart unless-stopped \
  lscr.io/linuxserver/chromium:latest

echo "[3/4] Installing yt-dlp in Chrome container..."
sleep 5
docker exec $CONTAINER_NAME /lsiopy/bin/python3 -m pip install -q -U yt-dlp || true

echo "[4/4] Setup Complete!"
echo ""
echo "說明："
echo "1. Chrome 容器已啟動 (WebUI Port: 3000)。"
echo "2. 可透過瀏覽器連線 http://<伺服器IP>:3000 登入 Google/YouTube 帳號生成 Cookies。"
echo "3. 伺服器會透過 extract_youtube_cookies.sh 定期將 Cookies 同步至 Bot 容器中。"
echo "=========================================================="

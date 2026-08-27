#!/bin/bash
set -euo pipefail

CONTAINER_NAME="line-bot-summary123"
IMAGE_NAME="line-bot-summary"
PORT="8111"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================================="
echo "  Deploying LINE Bot Summary with High Concurrency Async  "
echo "=========================================================="

cd "$DIR"

# Ensure cookies.txt exists on host
touch "$DIR/cookies.txt"

# Step 1: 停止並刪除現有容器
echo "1. Stopping and removing existing container ($CONTAINER_NAME)..."
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

# Step 2: 建立新的 Docker image (確保 yt-dlp 與所有依賴皆為最新)
echo "2. Building new Docker image with latest dependencies..."
docker build --pull --no-cache -t "$IMAGE_NAME" .

# Step 3: 啟動新的容器 (背景常駐執行，掛載 cookies.txt 與 .env)
echo "3. Starting new container on port $PORT..."
docker run -d \
  -p "$PORT:5000" \
  --restart unless-stopped \
  --env-file .env \
  -v "$DIR/cookies.txt:/app/cookies.txt" \
  --name "$CONTAINER_NAME" \
  "$IMAGE_NAME"

# Step 4: 清理無用懸掛 images
echo "4. Cleaning up dangling Docker images..."
docker image prune -f

echo "=========================================================="
echo "  Deployment successful! Service is running on port $PORT  "
echo "=========================================================="

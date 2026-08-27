#!/bin/bash
set -e

CONTAINER_NAME="line-bot-summary123"
IMAGE_NAME="line-bot-summary"
PORT="8111"

echo "=========================================================="
echo "  Deploying LINE Bot Summary with High Concurrency Async  "
echo "=========================================================="

# Step 1: 停止並刪除現有容器
echo "1. Stopping and removing existing container ($CONTAINER_NAME)..."
sudo docker stop "$CONTAINER_NAME" 2>/dev/null || true
sudo docker rm "$CONTAINER_NAME" 2>/dev/null || true

# Step 2: 建立新的 Docker image (確保 yt-dlp 與所有依賴皆為最新)
echo "2. Building new Docker image with latest dependencies..."
sudo docker build --pull --no-cache -t "$IMAGE_NAME" .

# Step 3: 啟動新的容器
echo "3. Starting new container on port $PORT..."
sudo docker run -dp "$PORT:5000" --restart always --env-file .env --name "$CONTAINER_NAME" "$IMAGE_NAME"

# Step 4: 清理無用懸掛 images
echo "4. Cleaning up dangling Docker images..."
sudo docker image prune -f

echo "=========================================================="
echo "  Deployment successful! Service is running on port $PORT  "
echo "=========================================================="

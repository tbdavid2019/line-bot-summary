#!/bin/bash

# Step 1: 停止並刪除現有容器
echo "Stopping and removing existing container..."
docker stop line-bot-summary-container
docker rm line-bot-summary-container

# Step 2: 刪除未使用的舊 image
echo "Removing unused Docker images..."
docker image prune -f

# Step 3: 建立新的 Docker image
echo "Building new Docker image..."
sudo docker build -t line-bot-summary .

# Step 4: 啟動新的容器
echo "Starting new container..."
docker run -dp 8111:5000 --env-file .env --name line-bot-summary123 line-bot-summary

echo "Container restarted and old images cleaned up successfully!"


sudo docker build -t line-bot-summary .
sudo docker run -dp 8111:5000 --env-file .env --name line-bot-summary123 line-bot-summary

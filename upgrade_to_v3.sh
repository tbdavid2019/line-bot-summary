#!/bin/bash

echo "升級 LINE Bot 到高併發非同步架構 (SDK v3 + FastAPI + 888box)..."

# 安裝依賴項
echo "安裝依賴項..."
pip install -r requirements.txt

# 檢查是否安裝成功
if [ $? -eq 0 ]; then
    echo "依賴項安裝成功！"
    echo ""
    echo "請確認以下環境變數（.env）："
    echo "- CHANNEL_ACCESS_TOKEN: 你的 LINE Channel Access Token"
    echo "- CHANNEL_SECRET: 你的 LINE Channel Secret"
    echo "- LLM_API_KEY: OpenAI / Gemini 等 LLM API 金鑰"
    echo "- BOX_BASE_URL: 888box 雲端儲存主要端點（預設：https://box.david888.com）"
    echo "- GEMINI_IMAGE_API_KEY: Gemini 圖片生成金鑰（選填）"
    echo ""
    echo "本地開發啟動方式："
    echo "uvicorn app:app --host 0.0.0.0 --port 5000 --reload"
    echo ""
    echo "生產環境容器啟動方式："
    echo "./build.sh"
else
    echo "依賴項安裝失敗，請檢查網路連線和 Python 環境"
    exit 1
fi

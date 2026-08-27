# LINE Bot 高併發非同步架構升級指南

本文件說明如何從舊版同步 Flask 架構全面升級為 **FastAPI + 非同步 I/O + 執行緒池 (Thread Pool) + 888box 雲端多端點儲存** 的高併發非阻塞架構。

---

## ⚡ 為什麼需要升級？舊版架構痛點

1. **單一同步 Worker 塞車**：
   - 舊版以同步 Flask + Gunicorn 單一 Worker 執行。當一位用戶傳送 YouTube 影片（需下載音訊、FFmpeg 分段、Whisper 轉錄、LLM 總結，耗時約 20~50 秒）時，整個伺服器完全被卡死。
   - 其他用戶在此期間發送任何訊息，Webhook 連線均會超過 LINE 的 1~2 秒超時限制，導致訊息遺失或報錯。
2. **事件迴圈阻塞**：
   - `requests.post`、`yt-dlp`、`trafilatura` 等阻塞式 I/O 若直接在 async 函式中執行會凍結主事件迴圈。
3. **雲端儲存單點故障**：
   - 舊版僅支援 GCS，若無 GCP 帳號則無法儲存圖片與媒體。

---

## 🚀 新版非同步架構特色

### 1. Webhook 即刻回應機制 (Instant Webhook ACK < 30ms)
- 收到 LINE Webhook 請求後，驗證簽章無誤後**立即透過 `BackgroundTasks` 分派背景任務，並在 30 毫秒內向 LINE 伺服器回傳 HTTP 200 `{"status": "ok"}`**。
- 徹底消除 LINE Webhook 逾時問題，多人同時發送影音請求時絕不塞車。

### 2. 異步非阻塞管線 (Non-blocking Async Pipeline)
- **非同步 HTTP (httpx)**：LLM API (`/chat/completions`)、Whisper API 與 LINE Loading 動畫皆改用非同步 HTTP 客戶端。
- **背景執行緒池 (asyncio.to_thread)**：將 `yt-dlp` 下載、`ffmpeg` 影音處理、`trafilatura` 網頁抓取等 CPU / 阻塞式工作自動卸載至執行緒池，確保主事件迴圈隨時高速運作。
- **非同步訊息發送**：訊息發送優先使用 `reply_message`，若 Token 逾時則自動切換為 `push_message`，保證訊息必達。

### 3. 888box 雲端多端點自動容錯儲存
- 內建 `src/box_storage.py`，支援三端點自動切換（主要：`box.david888.com`，備援：`box.glsoft.ai`、`box.aiurl.tw`）。
- 產出檔案、AI 生成圖片 (`!img`)、音訊、影片、摘要文字 (`.txt`) 皆可直接儲存與分享。

---

## 📋 依賴套件變更 (`requirements.txt`)

```txt
fastapi>=0.110.0
uvicorn[standard]>=0.28.0
gunicorn>=21.2.0
httpx>=0.27.0
requests>=2.31.0
line-bot-sdk>=3.11.0
beautifulsoup4>=4.12.0
trafilatura>=1.8.0
yt-dlp>=2024.0.0
pydub>=0.25.1
python-dotenv>=1.0.0
google-genai>=0.1.0
google-generativeai>=0.5.0
google-cloud-storage>=2.14.0
```

---

## 🏃 啟動方式

### 本地開發啟動 (Uvicorn Async)
```bash
uvicorn app:app --host 0.0.0.0 --port 5000 --reload
```

### 生產環境容器啟動 (Gunicorn + 4 Uvicorn Workers)
```bash
./build.sh
```
容器內部執行指令：
```bash
gunicorn -b 0.0.0.0:5000 -k uvicorn.workers.UvicornWorker --workers 4 --timeout 300 app:app
```

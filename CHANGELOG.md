# 更新日誌 (CHANGELOG)

本專案的所有重要異動都會記錄於此文件中。
記錄格式參考 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)。

---

## [Unreleased]

## [2026-08-27]
### Changed
- **全面升級高併發非同步架構 ([`app.py`](app.py))**：
  - 核心由舊版同步 Flask 重構為 **FastAPI + 非同步 I/O + 執行緒池 (Thread Pool)** 架構。
  - **即刻 Webhook 回應機制 (Instant ACK)**：Webhook 收到訊息後立即於 30ms 內回傳 HTTP 200 `{"status": "ok"}` 給 LINE，繁重處理完全透過 `BackgroundTasks` 非同步分派，徹底根除多人同時使用造成的連線超時與塞車。
  - **非同步非阻塞管線**：
    - LLM API 與 Whisper API 客戶端全面換用 `httpx.AsyncClient`。
    - `yt-dlp` 影音下載、`ffmpeg` 轉檔、`trafilatura` 網頁爬取全面透過 `asyncio.to_thread` 卸載至執行緒池，避免凍結主事件迴圈。
    - 支援執行緒安全的用戶續問對話狀態管理 (`asyncio.Lock`)。
  - **部署容器升級 ([`Dockerfile`](Dockerfile))**：
    - 採用 Gunicorn + 多 Worker `uvicorn.workers.UvicornWorker`（預設 4 Workers）以支援高併發負載。
  - **依賴升級 ([`requirements.txt`](requirements.txt))**：
    - 新增 `fastapi`, `uvicorn[standard]`, `httpx`, `line-bot-sdk>=3.11.0`。

### Fixed
- **YouTube 簽名與 n-challenge JS 解密修復 ([`Dockerfile`](Dockerfile), [`app.py`](app.py))**：
  - 於 Dockerfile 內建 Deno 2.9+ JavaScript 執行環境，解決 yt-dlp 在資料中心 IP 下遭遇 `Signature solving failed / The page needs to be reloaded` 阻擋問題。
  - 修正 `app.py` 中 yt-dlp 設定參數 `cookiefile`（修正前為錯誤的 `cookiesfile`），確保 `cookies.txt` 憑證能被 yt-dlp 正確讀取。
- **Gemini LLM 模型名稱與金鑰更新**：
  - 更新 `.env` 中的 LLM 模型為目前 Google 支援之 `gemini-2.5-flash`，並配置有效之 API Key，消除 400 Bad Request 錯誤。
- **LINE Webhook 解析與訊息傳送通道強化**：
  - 改用原生 RFC-compliant HMAC-SHA256 簽章驗證與原生 JSON 事件分派，解決 `line-bot-sdk` v3 因 Pydantic 嚴格型別校驗失敗（如缺少 `quoteToken` / `deliveryContext`）導致之 `UnknownEvent` 訊息遺失問題。
  - 將 LINE 回覆與推播全面升級為原生非同步 `httpx.AsyncClient` 雙通道發送（優先 Reply Token，超時或失效自動切換 Push Message），解決多 Worker Gunicorn 環境下 `AsyncApiClient` 跨程序事件迴圈失效問題。

### Added
- **2MD (888-url2md) 即時聯網瀏覽與 SERP 搜尋模組 ([`src/web_browser.py`](src/web_browser.py))**：
  - 整合多端點容錯備援（`https://2md.aiurl.tw/`、`https://2md.glsoft.ai/`、`https://create360.ai/`）。
  - **即時全網搜尋 (Live SERP)**：支援 `!s [關鍵字]`、`!search`、`!新聞` 等指令，以及針對任何自然語言提問自動啟動即時全網檢索，將即時事實餵入 LLM 進行精準回答，徹底消除過期知識與幻覺。
  - **2MD 高速 Markdown 網頁解析器**：將任意動態 JavaScript 網頁、新聞或線上文檔轉為乾淨 Markdown，大幅提升摘要與問答品質。
  - 支援針對搜尋結果進行 5 次連續深度追問與上下文記憶管理。
- **888box 雲端多端點儲存模組 ([`src/box_storage.py`](src/box_storage.py))**：
  - 支援產出檔案 (`file`)、圖片 (`image`)、影音源 (`video`/`audio`)、純文字摘要/逐字稿 (`txt`) 與遠端 URL 轉存上傳。
  - 實作三端點自動容錯備援機制（主要：`https://box.david888.com`，備援 1：`https://box.glsoft.ai`，備援 2：`https://box.aiurl.tw`）。
  - 提供同步與非同步介面，以及資產列表、關鍵字搜尋、刪除與統計查詢功能。
- **LINE 機器人指令支援**：
  - 新增 `!box`、`!stats`、`!空間` 指令以即時查詢 888box 儲存庫狀態與資產計數。
  - 整合 AI 圖片生成 (`!img`) 與儲存流程，生成之圖片直接非同步上傳至 888box 儲存庫並支援 GCS 備援。
- **自動化維運與即時更新腳本**：
  - 新增 [`extract_youtube_cookies.sh`](extract_youtube_cookies.sh)：定期從 Chrome 容器自動提取最新 YouTube cookies 並熱同步至 LINE Bot 容器，解決 YouTube 阻擋問題。
  - 新增 [`auto_sync_repo.sh`](auto_sync_repo.sh)：自動檢測遠端 main 分支提交並觸發拉取與容器重新建置。
  - 新增 [`auto_update_ytdlp.sh`](auto_update_ytdlp.sh)：自動監測 PyPI 最新 yt-dlp 版本並於容器內即時升級，確保影音解析永不失效。
- **文件與規範建立**：
  - 建立專案代理人規範文件 [`AGENTS.md`](AGENTS.md)，規範後續異動主動更新 `CHANGELOG.md` 與 `README.md`。
  - 更新 [`MIGRATION_GUIDE.md`](MIGRATION_GUIDE.md) 詳細解說非同步架構演進與效益。
  - 同步更新 [`README.md`](README.md) 功能特色、技術架構與環境變數說明。

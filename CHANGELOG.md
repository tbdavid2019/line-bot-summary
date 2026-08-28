# 更新日誌 (CHANGELOG)

本專案的所有重要異動都會記錄於此文件中。
記錄格式參考 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)。

---

## [Unreleased]

## [2026-08-28]
### Added
- **CI/CD 部署強化與 Docker Compose / Chrome 容器生態整合 ([`docker-compose.yml`](docker-compose.yml), [`setup_chrome_container.sh`](setup_chrome_container.sh), [`build.sh`](build.sh), [`README.md`](README.md))**：
  - 新增 `docker-compose.yml` 支援一鍵 `docker compose up -d` 部署，標準化 Volume Mount（包含 `cookies.txt`、`app.py`、`src/`）。
  - 新增 `setup_chrome_container.sh` 快速啟動獨立 Headless Chrome 容器，搭配 `extract_youtube_cookies.sh` 實現 YouTube 最新 Cookies 自動熱同步。
  - 修正 `build.sh` 鏡像名稱統一為 `tbdavid2019/line-bot-summary:latest`，確保部署主機上的 Watchtower 能夠無縫跟蹤與熱更新。
- **David888 Wiki 知識庫發布執行器與官方技術白皮書 ([`src/agent_tools.py`](src/agent_tools.py), [`wiki_article.md`](wiki_article.md), [`README.md`](README.md))**：
  - 新增 `wiki_publish` 執行器工具，支援 LLM 自主將精華摘要、研究報告一鍵發布至 `wiki.david888.com`，生成永久公開 Markdown 與 2D 簡報連結。
  - 官方技術白皮書已公開上線：[https://wiki.david888.com/share/wcfm7e](https://wiki.david888.com/share/wcfm7e)（簡報模式：[https://wiki.david888.com/share/wcfm7e/present](https://wiki.david888.com/share/wcfm7e/present)）。
- **LINE 零中斷超時保護（SafeReply ➔ Push Fallback）全時守護體系 ([`app.py`](app.py), [`README.md`](README.md))**：
  - 詳細解析「即刻 ACK (<30ms) ➔ BackgroundTasks 背景池 ➔ SafeReply/Push 雙保險」三層訊息交付架構。
  - 確保無論影音轉錄或多輪 Agent 檢索耗時多久（超過 30 秒），系統皆能自動降級切換 `pushMessage` 強制精準送達，實現零掉訊息、零超時中斷。
- **LINE Quick Reply 多樣化濃縮模式互動切換 ([`app.py`](app.py), [`README.md`](README.md))**：
  - 產出摘要後底部自動附帶 5 組 Quick Reply 快捷按鈕：`⚡ 1分鐘極簡版`、`📊 結構化大綱`、`❓ 核心 Q&A`、`📱 社群貼文風`、`🎨 繪製概念圖`。
  - 使用者可一鍵切換不同濃縮風格，亦可透過自然語言自由指定濃縮格式。
- **意圖解構與自主執行架構 (Agentic Actuators) ([`src/agent_tools.py`](src/agent_tools.py), [`app.py`](app.py))**：
  - 實裝 OpenAI/Gemini 相容的 Tool Calling JSON Schema (`AGENT_TOOLS`)，包含 `web_search`、`web_read_markdown`、`video_transcribe`、`generate_image`、`box_storage_action` 五大核心執行器。
  - 實裝 `AgentActuators` 與非同步 ReAct 代理迴圈 (`run_agentic_loop_async`)，支援多工具並發／鏈式連續調用與產物自動聚合（文字回答 + 生成圖片雙通道發送）。
  - 使用者無需死記指令前綴，直接以自然語言提問，由 LLM 大腦自主解構意圖並調用執行器完成複合任務。
  - 保留單一網址極速 5 段式摘要通道（Fast-Track），兼具極致效率與自主靈活性。
- **對話狀態與 Session 記憶機制 Know-How 文檔 ([`README.md`](README.md))**：
  - 詳細記錄主題式輕量級上下文注入（Topic-based In-Memory Context Injection）設計哲學與重構歷程。
  - 繪製 Mermaid 流程圖說明 Session 建立、5 次連續深度追問、自動釋放與主題覆蓋之完整生命週期管理。
  - 闡述 In-Memory 字典 + `asyncio.Lock` 高併發執行緒安全架構及未來擴充指引。

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
    - 加入動態架構偵測（`uname -m`），自動依據 `linux/amd64` 或 `linux/arm64` 安裝相容之 Deno 執行檔。
  - **CI/CD 自動化發布 ([`.github/workflows/docker-build.yml`](.github/workflows/docker-build.yml))**：
    - 新增 GitHub Actions 雙架構（`linux/amd64`、`linux/arm64`）映像檔建置工作流，設定 Docker Hub Secrets 後在每次 `push main` 或 Release 自動發布最新映像檔。
  - **依賴升級 ([`requirements.txt`](requirements.txt))**：
    - 新增 `fastapi`, `uvicorn[standard]`, `httpx`, `line-bot-sdk>=3.11.0`。

### Fixed
- **YouTube 簽名與 n-challenge JS 解密修復 ([`Dockerfile`](Dockerfile), [`app.py`](app.py))**：
  - 於 Dockerfile 內建 Deno 2.9+ JavaScript 執行環境，解決 yt-dlp 在資料中心 IP 下遭遇 `Signature solving failed / The page needs to be reloaded` 阻擋問題。
  - 修正 `app.py` 中 yt-dlp 設定參數 `cookiefile`（修正前為錯誤的 `cookiesfile`），確保 `cookies.txt` 憑證能被 yt-dlp 正確讀取。
  - **直接字幕串流與雙軌轉錄**：支援從 yt-dlp metadata 直接解析字幕 URL 下載，並在影音無內建字幕時，自動透過 Gemini 多模態語音轉錄作為強力備援，確保影音摘要 100% 成功。
- **Gemini LLM 模型全面升級至 `gemini-3.6-flash`**：
  - 更新預設模型配置為最新 `gemini-3.6-flash`，具備更優異的摘要理解、即時聯網資訊整合與更低的推論延遲。
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

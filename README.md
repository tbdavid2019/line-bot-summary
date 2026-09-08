

# LINE Bot 智能摘要機器人 🤖

LINE 示範機器人 小濃縮 👉👉  https://liff.line.me/1645278921-kWRPP32q/?accountId=032trcev
![alt text](image.png)


支援續問
![alt text](image-1.png)
## ✨ 功能特色

### 🎥 多平台影音支援
支援 **1000+ 影音網站** 的內容摘要，包括但不限於：
- **YouTube** - 完整支援字幕提取和音頻轉錄
- **Bilibili** - 支援B站影片摘要
- **Vimeo** - 專業影片平台
- **Dailymotion** - 歐洲知名影片平台
- **TikTok** - 短影片平台
- **Twitch** - 直播平台
- **Facebook Watch** - Facebook 影片
- **Instagram** - 貼文、Reels、IGTV
- **Twitter/X** - 推文影片
- **SoundCloud** - 音頻平台
- **Spotify** - 音樂串流
- **TED Talks** - 演講影片
- **Coursera** - 線上課程
- **Khan Academy** - 教育影片
- 以及更多其他平台...

### 📄 網頁內容摘要
- 支援各種新聞網站、部落格、文章等純文字網頁
- 智能提取網頁核心內容
- 自動過濾廣告和無關內容

### 🧠 智能摘要格式
每個摘要包含五個部分：
- ❶ **總結** - 300字以上的完整概述
- ❷ **觀點** - 3-7個主要觀點分析
- ❸ **摘要** - 6-10個核心重點（含表情符號）
- ❹ **測驗** - 三題選擇題加深理解
- ❺ **容易懂** - 適合12歲孩子的簡化解釋

### 🎛️ 多樣化濃縮模式與 Quick Reply 快速切換
摘要生成後，底部自動浮現 **LINE Quick Reply 互動按鈕**，一鍵秒切不同風格：
- ⚡ **1分鐘極簡版**：3 句超精華結論 + 關鍵數據。
- 📊 **結構化大綱**：心智圖／樹狀層級架構，適合深度演講與長課程。
- ❓ **核心 Q&A**：拆解出 5 個最重要的 Q&A 問答。
- 📱 **社群貼文風**：吸睛 Hook、3 個重點、搭配 Emoji 與 Hashtag。
- 🎨 **繪製概念插圖**：自動調用 AI 生成符合主題的精美概念圖。

### 💬 深度續問功能
- 📝 針對同一影片/網頁最多可續問 **5 次**
- 🎯 基於原始完整內容回答，確保準確性
- 📊 每次回答後顯示剩餘續問次數
- 🔄 傳送新網址即重置對話，開始新的摘要

### 📦 雲端資產儲存庫 (888box API)
- ☁️ **多端點容錯儲存**：產出的檔案、生成圖片、下載影音源或逐字稿 txt 皆可上傳至雲端儲存。
- 🔄 **自動切換機制**：
  - **主要端點**：`https://box.david888.com`
  - **備援端點 (Fallback 1)**：`https://box.glsoft.ai`
  - **備援端點 (Fallback 2)**：`https://box.aiurl.tw`
- 💬 **LINE 指令支援**：
  - 輸入 `!box`、`!stats` 或 `!空間` 即時查詢雲端儲存空間狀態與資產計數。
  - 輸入 `!img [提示詞]` 生成圖片並自動上傳至雲端儲存。

### 📁 多模態檔案與多媒體解析 (Google Magika AI 本地深度辨識)
- 🔬 **Google Magika 深度學習引擎**：整合 Google 官方 AI 檔案辨識庫 [`src/file_detector.py`](src/file_detector.py)，Docker Build 時核心 ONNX 模型隨 Wheel 自動打包內建於映像檔，運行時 100% 本地 CPU 離線推論（單次僅約 ~5ms），無外部網路連線依賴、零 API 成本、隱私資料零外洩。
- 🎙️ **語音訊息轉錄與濃縮 (Audio)**：直接在 LINE 傳送語音訊息或錄音檔，系統自動精確辨識音訊格式、轉錄為文字逐字稿並產出 5 段式結構化摘要，同樣支援後續 5 次深入追問。
- 📑 **文件與原始碼精讀 (Document / Code / PDF)**：直接上傳 PDF、Markdown、文字檔、CSV 或程式碼，AI 自動提取純文字或透過 Gemini 多模態深度解構文件重點，並自動備份至 888box 雲端。
- 🖼️ **圖片深度視覺解析 (Image)**：使用者傳送照片或截圖，系統自動完成高畫質 888box 存檔，並調用 Gemini 視覺模型解析畫面主體、文字 OCR 與關鍵資訊。
- 🏷️ **888box 儲存 Content-Type 自動校正**：檔案或二進位串流上傳時自動分析真實標頭特徵，擺脫副檔名遺失或猜測錯誤的問題。
- 🛠️ **Agent 工具自主檢驗 (`inspect_file_type`)**：LLM 在 ReAct 迴圈中可自主取樣遠端網址檔案標頭 (0-16KB) 並分析其真實 MIME 格式與安全性質。

### ⏳ 即時回饋
- 🔄 **Loading 動畫** - 處理網址或多媒體時自動顯示載入動畫（最長 60 秒）
- 💬 讓使用者知道系統正在處理中，提升使用體驗

## 🧠 對話狀態與 Session 記憶機制 (Know-How)

本專案採用 **「主題式輕量級上下文注入 (Topic-based In-Memory Context Injection)」** 架構，兼顧極致效能與精準問答體驗：

```mermaid
flowchart TD
    A["使用者傳送 URL / !s 搜尋"] --> B["提取影音逐字稿 / 網頁原文 / SERP 資料"]
    B --> C["LLM 產出 5 段式結構化摘要"]
    C --> D["建立 user_sessions[user_id]<br/>• 儲存完整原文<br/>• 追問計數: 5 次"]
    D --> E{"使用者後續提問"}
    E -->|"傳送自然語言問題"| F["從 Session 注入全文上下文給 LLM 回答"]
    F --> G["剩餘追問次數 -1"]
    G -->|"次數歸零"| H["自動釋放 Session"]
    G -->|"次數 > 0"| E
    E -->|"傳送新 URL / 重新搜尋"| B
```

### 1. 設計哲學與重構背景
- **擺脫重型依賴**：早期版本依賴 MongoDB 與 LangChain Memory，造成連線開銷高、部署繁瑣且在高併發時易發生死鎖與連線逾時。
- **純淨且精準的上下文注入**：通用聊天記憶（Chat History）容易隨對話變長而產生雜訊與模型幻覺；本專案將記憶聚焦於**「當前影音／網頁／搜尋結果的原始完整文字」**，確保每次續問都能 100% 精準錨定在原文事實上。

### 2. Session 生命週期管理
| 階段 | 觸發條件 | 系統行為 |
| :--- | :--- | :--- |
| **Session 建立** | 使用者傳送影音連結、網頁連結或 `!s` 全網搜尋 | 提取原始資料後，以 `userId` 為 Key 存入 `user_sessions`，重置續問次數為 `5`。 |
| **深度續問** | 使用者輸入非指令、非網址的自然語言提問 | 系統自動帶入 Session 中的全文作為 Prompt 上下文，回答完畢後遞減計數並提示剩餘次數。 |
| **自動釋放** | 5 次續問額度耗盡 | 自動刪除 `user_sessions[userId]`，釋放記憶體。 |
| **主題覆蓋** | 使用者傳送新的網址或新搜尋 | 無論剩餘次數為何，立即覆蓋並啟動全新主題的 Session。 |

### 3. 高併發與執行緒安全
- 狀態儲存採用原生字典搭配 `asyncio.Lock()`，在 FastAPI 非同步協程中實現無鎖競爭的高效原子操作。
- **In-Memory 架構**：零外部網路 I/O 延遲，單次 Session 檢索耗時 `< 1ms`。
- **擴充指引**：若未來需跨多伺服器節點共享或持久化使用者對話狀態，可無縫將 `user_sessions` 介面抽換對接 Redis 或 Key-Value 儲存庫。

## 🤖 意圖解構與自主執行架構 (Agentic Actuators)

本專案升級為 **「LLM 原生 Tool Calling 自主代理架構」**，讓 LLM 大腦直接具備 API 執行權限：

```mermaid
flowchart TD
    User["使用者輸入任意自然語言"] --> LLM["LLM 大腦 (Gemini 3.6 Flash / Tool Calling)"]
    LLM -->|"自主決策與意圖解構"| Dispatcher["Actuators 執行器中樞 (src/agent_tools.py)"]
    
    subgraph Actuators ["執行器工具箱 (Actuators)"]
        T1["🌐 web_search<br/>(2MD SERP 全網搜尋)"]
        T2["📑 web_read_markdown<br/>(2MD 高速網頁閱讀)"]
        T3["🎥 video_transcribe<br/>(yt-dlp + Gemini 音訊轉錄)"]
        T4["🎨 generate_image<br/>(Gemini/Imagen AI 生圖)"]
        T5["📦 box_storage_action<br/>(888box 雲端多端點存儲)"]
        T6["📖 wiki_publish<br/>(David888 Wiki 知識庫發布)"]
    end
    
    Dispatcher --> Actuators
    Actuators -->|"回傳執行結果"| LLM
    LLM -->|"綜合推理多工具結果"| Reply["LINE 雙通道回傳 (文字 + 圖片)"]
```

### 🎯 核心優勢與能力
1. **擺脫死記指令**：使用者無需輸入前綴（如 `!s`、`!img`、`!box`），直接用自然語言表達需求即可。
2. **多工具鏈式調用**：支援單次請求中自主觸發多個工具（例如：*「先幫我搜尋 SpaceX 星艦發射台的最新消息，並為它生成一張概念插圖，最後發布到 Wiki」*）。
3. **David888 Wiki 知識庫發布**：支援一鍵將對話摘要或研究成果發布至 `wiki.david888.com`，生成永久公開閱讀與 2D 簡報連結。
4. **極速通道相容 (Fast-Track)**：當使用者僅傳送單一網址時，自動進入 5 段式結構化極速摘要模式，兼具速度與深度。

📖 **官方技術白皮書**：[https://wiki.david888.com/share/wcfm7e](https://wiki.david888.com/share/wcfm7e)（2D 簡報模式：[https://wiki.david888.com/share/wcfm7e/present](https://wiki.david888.com/share/wcfm7e/present)）

## 🛡️ LINE 零中斷超時保護（SafeReply ➔ Push Fallback）全時守護

本專案實裝業界最高等級的 **「三層零中斷訊息交付保護體系」**，徹底解決 LINE Bot 處理長影音或深度 AI 思考時的掉訊息痛點：

```mermaid
flowchart TD
    Webhook["LINE Webhook 請求進線"] --> L1["第 1 層：即刻 ACK (<30ms 回傳 HTTP 200)"]
    L1 --> L2["第 2 層：BackgroundTasks 背景執行緒池<br/>(影音下載 / 轉錄 / 多輪 Agent 檢索)"]
    L2 --> L3{"第 3 層：SafeReply 發送檢測"}
    L3 -->|"30秒內未逾時"| R1["優先走 replyToken 免費回覆"]
    L3 -->|"耗時較長 / Token 逾時失效"| R2["全自動 SafeReply Fallback 降級<br/>改以 pushMessage (to_id) 強制推播"]
    R1 --> Success["✅ 100% 成功交付使用者手機（含 Quick Reply 選單）"]
    R2 --> Success
```

### 💎 三層保護架構核心優勢

| 保護層級 | 實作機制 | 解決痛點 |
| :--- | :--- | :--- |
| **第 1 層：Webhook 即刻 ACK** | 接收事件立即於 `< 30ms` 內回傳 `HTTP 200 {"status": "ok"}` 給 LINE 伺服器。 | 徹底根除 LINE 官方 Webhook 1 秒超時警報與重複重送問題。 |
| **第 2 層：BackgroundTasks 異步池** | 影音轉檔、逐字稿轉錄、網頁爬取及多輪 Tool Calling 全數卸載至背景執行緒。 | 支援多人同時併發使用，各請求完全獨立運行、零阻塞不排隊。 |
| **第 3 層：SafeReply ➔ Push 雙保險** | 發送時優先嘗試 `replyToken`；若因長影音轉錄或多輪檢索耗時超過 30 秒導致 Token 過期，系統自動捕獲並**無縫切換為 `pushMessage` 強制推播**。 | 即使 10 輪循環研究或超長影音下載超過 1 分鐘，**訊息 100% 精準送達，絕不掉訊息、絕不超時中斷**！ |

### 📜 長文本智慧分段與 Quick Reply 掛載
- 自動將超過 LINE 單則上限（2000 字元）的超長分析或逐字稿智慧分段發送。
- 在最後一則訊息自動掛載 **LINE Quick Reply 互動選單**，讓使用者隨時一鍵切換濃縮風格！

## 🔒 安全防護與合規強化體系 (Security & Hardening)

專案內建完整的資安防禦體系（[`src/security.py`](src/security.py)），符合企業級 Webhook 與雲端服務安全規範：

| 防禦面向 | 威脅防範 | 實作機制 |
| :--- | :--- | :--- |
| **🌐 SSRF 防護** | 阻擋惡意 URL 探測本機或 VPC 內網資源（如 `127.0.0.1`, `169.254.169.254` 雲端 Metadata） | `is_safe_url()` 解析所有域名並嚴格比對 RFC 1918 私有網段與保留 IP。 |
| **🔐 Webhook 嚴格簽章** | 防止未經授權的第三方偽造 LINE Webhook 注入惡意指令 | 強制檢驗 `X-Line-Signature` 並使用 `hmac.compare_digest` 常數時間比對防止時序攻擊。 |
| **🧠 有界 Session 快取** | 防止惡意流量或長期運行時對話紀錄無上限膨脹導致記憶體耗盡 (OOM DoS) | 實裝 `BoundedSessionManager`，具備 1,000 筆上限容量 (LRU) 與 2 小時 TTL 自動過期回收。 |
| **📂 路徑穿越防禦** | 防止使用者上傳或儲存惡意檔名（如 `../../etc/passwd`）侵入系統目錄 | `sanitize_filename()` 嚴格剔除路徑符號、連續點與特殊控制字元。 |
| **🛑 敏感資訊脫敏** | 防止例外異常時洩漏伺服器路徑、API Key (Bearer/sk-xxx/AIzaSy) 或堆疊 (CWE-209) | `sanitize_error_message()` 自動過濾與淨化對外回傳之錯誤訊息。 |
| **📦 供應鏈漏洞修補** | 避免第三方相依套件已知安全漏洞 | 升級 `requests>=2.32.3`、`urllib3>=2.2.2`、`fastapi>=0.115.0`。 |

## 🔧 技術特色

本專案 fork 自 https://github.com/Achiwilms/LINE-NEWS-Bot
已做大幅更改：
- 🚀 **全面升級高併發非同步架構 (FastAPI + Uvicorn Worker + BackgroundTasks)**：
  - Webhook 收到訊息立即於 **< 30ms** 內回傳 HTTP 200，繁重任務透過背景非同步執行，徹底解決多人併發塞車與逾時問題。
  - 所有 CPU/硬碟/網路阻塞任務（`yt-dlp` 下載、`ffmpeg` 影音轉檔、`trafilatura` 網頁抓取）均透過 `asyncio.to_thread` 卸載至背景執行緒池。
  - LLM 與 Whisper 均改採 `httpx` 非同步高效客戶端。
- ✅ 去除 monogoDB 依賴
- ✅ 去除 langchain memory 
- ✅ 新增 **yt-dlp** 支援，擴展至 1000+ 影音網站
- ✅ 智能 URL 檢測，自動區分影音網站和普通網頁
- ✅ 雙重檢測機制，避免誤判
- ✅ 支援字幕提取和音頻轉錄備援
- ✅ 更改 prompt，產出更易懂的摘要
- ✅ 改用 Docker 容器化部署（多 Worker Uvicorn）
- ✅ **續問功能** - 支援針對同一內容最多 5 次續問（執行緒安全對話狀態管理）
- ✅ **Loading 動畫** - 處理時非同步發送即時回饋
- ✅ **彈性 API 配置** - 自動補全 API 路徑，相容 OpenAI 格式 API
- 🌐 **2MD 即時聯網瀏覽與 SERP 搜尋 (`src/web_browser.py`)** - 整合 `https://2md.aiurl.tw/`、`https://2md.glsoft.ai/`、`https://create360.ai/`，賦予 LLM 即時檢索全網最新事實與資訊之能力，支援直接問答聯網、`!s [關鍵字]`、`!新聞` 等指令，徹底根除幻覺。
- 📑 **2MD 高速 Markdown 網頁閱讀器** - 自動將任意動態 JavaScript 網頁、新聞或線上文檔轉為純淨 Markdown，並在異常時自動降級本地解析。
- ✅ **888box 雲端儲存模組 (`src/box_storage.py`)** - 提供同步/非同步檔案、圖片、影音、文字上傳與遠端 URL 轉存，支援三端點自動容錯。
- 🍪 **YouTube Cookies 自動熱同步 (`extract_youtube_cookies.sh`)** - 定期從 Chrome 容器提取最新登入憑證並熱同步至機器人容器，有效突破 YouTube 嚴格反爬蟲限制。
- 🔄 **yt-dlp 保持最新機制 (`auto_update_ytdlp.sh`)** - 容器內啟動背景監測與伺服器排程，當 PyPI 有最新版 yt-dlp 時自動更新，確保 1000+ 網站提取永不失效。
- 🔄 **GitHub 倉庫自動同步腳本 (`auto_sync_repo.sh`)** - 自動監測遠端分支異動並觸發重新建置與無縫升級。
- ✅ **Python 3.13** - 升級至最新 Python 版本

## 🚀 環境設置

### 必要環境變數

在專案根目錄建立 `.env` 文件，並設置以下環境變數：

#### LINE Bot 設定
- **CHANNEL_SECRET** - LINE Messaging API 的密鑰
- **CHANNEL_ACCESS_TOKEN** - LINE Messaging API 的存取權杖
> 💡 可參考 [ChatGPT串接到LINE](https://www.explainthis.io/zh-hant/chatgpt/line) 取得 Line Token

#### LLM API 設定
- **LLM_API_KEY** - LLM API 密鑰（支援 OpenAI、Gemini 等）
- **LLM_BASE_URL** - API 基礎 URL（支援簡化格式，如 `https://generativelanguage.googleapis.com/v1beta/openai`，系統會自動補全 `/chat/completions`）
- **LLM_MODEL** - 使用的模型（預設：`gemini-3.6-flash`）
- **MAX_TOKEN_LIMIT** - 最大 token 限制（預設：`900000`）

#### Whisper API 設定（音頻轉錄）
- **WHISPER_API_KEY** - Whisper API 密鑰
- **WHISPER_BASE_URL** - Whisper API URL（預設：`https://api.openai.com/v1/audio/transcriptions`）

#### 888box 雲端儲存設定（選填）
- **BOX_BASE_URL** - 主要端點（預設：`https://box.david888.com`）
- **BOX_ENDPOINTS** - 逗號分隔多端點清單（預設：`https://box.david888.com,https://box.glsoft.ai,https://box.aiurl.tw`）
- **BOX_API_TOKEN** - API Token（選填，用於受保護操作）

#### 其他設定
- **PORT** - 服務運行埠號（預設：`5000`）

### 📋 前置需求
- Docker 和 Docker Compose
- 有效的 LINE Developer 帳戶
- LLM API 金鑰（OpenAI、Google AI 等）
- 音頻轉錄 API 金鑰（用於無字幕影片）


### 方法一：使用 Docker Compose 部署（推薦）
```bash
# 啟動服務（自動載入 .env 與掛載 cookies.txt / 程式碼）
docker compose up -d

# 查看運行日誌
docker compose logs -f
```

### 方法二：使用 Docker Hub 雙架構映像檔
本專案支援 GitHub Actions 全自動建置 **雙架構（`linux/amd64` 與 `linux/arm64`）** Docker Image 並自動發布至 Docker Hub。

```bash
# 確保本機 cookies.txt 存在
touch cookies.txt

# 拉取最新雙架構映像檔（自動依主機架構適配 x86 或 ARM64）
docker pull tbdavid2019/line-bot-summary:latest

# 啟動容器
docker run -d \
  -p 8111:5000 \
  --restart unless-stopped \
  --env-file .env \
  -v "$(pwd)/cookies.txt:/app/cookies.txt" \
  --name line-bot-summary123 \
  tbdavid2019/line-bot-summary:latest
```

### 方法三：使用本地一鍵建置腳本
```bash
# 賦予執行權限並建置啟動
chmod +x build.sh
./build.sh
```

### 🍪 YouTube Cookies 自動提取與 Headless Chrome 容器架設
若伺服器處於機房 IP 環境遭遇 YouTube 嚴格反爬蟲限制，可透過以下步驟建立 Cookie 自動提取機制：

```bash
# 1. 一鍵啟動 Chrome 容器
chmod +x setup_chrome_container.sh
./setup_chrome_container.sh

# 2. 透過瀏覽器登入 YouTube 產生憑證
# 開啟瀏覽器訪問 http://<你的伺服器IP>:3000，登入 Google/YouTube 帳號

# 3. 測試手動提取 Cookies
chmod +x extract_youtube_cookies.sh
./extract_youtube_cookies.sh

# 4. 加入 crontab 自動排程（每 2 小時自動熱同步）
# 0 */2 * * * /bin/bash /path/to/line-bot-summary/extract_youtube_cookies.sh >> /path/to/line-bot-summary/cookies_sync.log 2>&1
```

### 方法四：開發模式
```bash
# 安裝相依套件
pip install -r requirements.txt

# 直接執行
python app.py
```

## 📱 使用方式

1. **加入 LINE Bot 好友**
   - 掃描 QR Code 或點擊連結加入機器人

2. **傳送網址**
   - 直接傳送任何支援的影音網站網址
   - 或傳送一般網頁文章網址

3. **獲得智能摘要**
   - 機器人會自動識別內容類型
   - 顯示 Loading 動畫表示正在處理
   - 提供結構化的五段式摘要
   - 可針對該內容繼續提問（最多 5 次）

4. **續問互動**
   - 收到摘要後，直接輸入問題即可續問
   - 系統會基於原始完整內容回答
   - 每次回答顯示剩餘續問次數
   - 傳送新網址開始新對話

### 支援的輸入格式
- ✅ 影音網址: YouTube, Bilibili, TikTok, Vimeo 等 1000+ 平台
- ✅ 網頁文章: 一般網頁、新聞網站、技術部落格
- ✅ 語音訊息: LINE 語音備忘錄、音訊錄音（自動轉錄 + 摘要）
- ✅ 文件檔案: PDF, TXT, Markdown, CSV, 程式碼（Magika 深度識別 + Gemini 摘要 + 888box 備存）
- ✅ 圖片照片: 截圖、相片（Gemini 視覺深度解析 + 888box 高畫質存檔）

## 🔧 技術架構

### 核心技術棧
- **Python 3.13** - 最新版本開發語言
- **Flask** - Web 框架
- **yt-dlp** - 多平台影音內容提取
- **trafilatura** - 網頁內容提取
- **LINE Messaging API** - 聊天機器人介面（含 Loading Indicator）
- **OpenAI/Gemini API** - 大語言模型
- **Docker** - 容器化部署

### 核心邏輯流程
1. **URL 檢測** - 使用正則表達式識別 URL
2. **Loading 動畫** - 顯示處理中狀態（最長 60 秒）
3. **平台判斷** - 雙重檢測機制判斷是否為影音網站
4. **內容提取** - 根據平台類型選擇提取方式
5. **智能摘要** - 使用 LLM 生成結構化摘要
6. **分段回傳** - 處理長文本自動分段
7. **對話記憶** - 儲存原始內容供續問使用（最多 5 次）

## 📊 新版本更新

### v3.0 最新功能 (2025-11)
- 💬 **續問功能** - 針對同一內容最多可續問 5 次，基於完整原文回答
- ⏳ **Loading 動畫** - 處理網址時自動顯示載入狀態，提升用戶體驗
- 🔧 **彈性 API 配置** - LLM_BASE_URL 自動補全路徑，支援各種 OpenAI 相容 API
- 🐍 **Python 3.13** - 升級至最新 Python 版本，效能更優

### v2.0 重大更新
- 🎯 **擴展影音平台支援** - 從僅支援 YouTube 擴展至 1000+ 網站
- 🧠 **智能 URL 識別** - 自動區分影音網站和普通網頁
- 🔄 **備援機制** - 字幕提取失敗時自動音頻轉錄
- 📝 **優化摘要格式** - 五段式結構化輸出
- 🐳 **容器化部署** - 完整 Docker 支援

## 🛠️ 自定義設定

### 修改摘要格式
編輯 `app.py` 中的 `get_summary_prompt()` 函數來自訂摘要風格

### 新增支援網站
在 `is_supported_by_ytdlp()` 函數的 `video_site_patterns` 列表中新增網站模式

### 調整 LLM 參數
在 `.env` 文件中調整 `LLM_MODEL`、`MAX_TOKEN_LIMIT` 等參數



歡迎發送 Pull Request！對於重大變更，請先開 Issue 討論你想更改的內容。

### 開發環境設置
```bash
# 克隆專案
git clone https://github.com/tbdavid2019/line-bot-summary.git
cd line-bot-summary

# 建立虛擬環境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows

# 安裝相依套件
pip install -r requirements.txt
```

### 功能建議
- 支援更多語言的字幕提取
- 新增音頻品質選擇
- 實作摘要歷史記錄（資料庫整合）
- 新增使用者偏好設定
- 支援批量處理
- 擴展續問次數限制可配置化



## 🎯 專案願景

此專案具有極大的彈性與可擴充性。透過簡單的 prompt 修改，就能快速轉換成不同用途的聊天機器人。結合強大的 yt-dlp 和現代 LLM 技術，為內容摘要領域提供了完整的解決方案。

**想像無限，創造無限** - 歡迎使用此專案的程式碼，發揮創意打造各種實用的智能機器人！

---

### 📞 聯繫我們
- **GitHub Issues**: [回報問題或建議](https://github.com/tbdavid2019/line-bot-summary/issues)
- **LINE Bot 示範**: [加入機器人](https://liff.line.me/1645278921-kWRPP32q/?accountId=032trcev)

### ⭐ Star History
如果這個專案對你有幫助，請給我們一個 ⭐ Star！
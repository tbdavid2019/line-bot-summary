import os
import re
import json
import uuid
import logging
import asyncio
import hmac
import hashlib
import base64
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
import httpx
from bs4 import BeautifulSoup
import yt_dlp
import trafilatura
import mimetypes

# 888box 雲端多端點儲存模組
from src.box_storage import (
    BoxStorageClient,
    upload_bytes_async,
    upload_text_async,
    upload_file_async,
    upload_url_async,
    get_stats_async
)

# 2MD (888-url2md) 即時聯網搜尋與網頁解析模組
from src.web_browser import (
    WebBrowserClient,
    search_web_async,
    read_url_markdown_async
)

# Google GenAI / GCS (選用備援)
try:
    from google import genai as genai_v2
    from google.genai import types as genai_types
except ImportError:
    genai_v2 = None
    genai_types = None

try:
    from google.cloud import storage as gcs_storage
except ImportError:
    gcs_storage = None

# 設定日誌
logging.basicConfig(
    level=os.getenv('LOG', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("line-bot-summary")

# 初始化 FastAPI
app = FastAPI(
    title="LINE Bot Smart Summary & Media Bot",
    description="High-concurrency async LINE Bot for 1000+ video summaries, web scraping, image generation, and 888box storage.",
    version="3.0.0"
)

# LINE 憑證配置
channel_secret = os.getenv('CHANNEL_SECRET')
channel_access_token = os.getenv('CHANNEL_ACCESS_TOKEN')

if not channel_secret:
    logger.warning("CHANNEL_SECRET is not set in environment variables.")
if not channel_access_token:
    logger.warning("CHANNEL_ACCESS_TOKEN is not set in environment variables.")


# LLM API 配置
llm_base_url_raw = os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1')
if llm_base_url_raw.endswith('/'):
    llm_base_url_raw = llm_base_url_raw.rstrip('/')
if not llm_base_url_raw.endswith('/chat/completions'):
    llm_base_url = llm_base_url_raw + '/chat/completions'
else:
    llm_base_url = llm_base_url_raw

llm_api_key = os.getenv('LLM_API_KEY', '')
llm_model = os.getenv('LLM_MODEL', 'gemini-3.6-flash')
llm_max_tokens = int(os.getenv('MAX_TOKEN_LIMIT', '900000'))

# Whisper API 配置
whisper_base_url = os.getenv('WHISPER_BASE_URL', 'https://api.openai.com/v1/audio/transcriptions')
whisper_api_key = os.getenv('WHISPER_API_KEY', '')

# Gemini Image 配置
gemini_image_key = os.getenv('GEMINI_IMAGE_API_KEY', '')
gemini_image_model = os.getenv('GEMINI_IMAGE_MODEL', 'gemini-3.1-flash-image')

# Google Cloud Storage 備援設定
gcs_bucket_name = os.getenv('GCS_BUCKET_NAME')
gcs_credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
gcs_bucket = None
if gcs_storage and gcs_credentials_path and gcs_bucket_name:
    try:
        gcs_client = gcs_storage.Client()
        gcs_bucket = gcs_client.bucket(gcs_bucket_name)
        logger.info(f"GCS bucket initialized: {gcs_bucket_name}")
    except Exception as e:
        logger.warning(f"Failed to initialize GCS: {e}")

# 用戶對話狀態管理（續問功能）
user_sessions: Dict[str, Dict[str, Any]] = {}
user_sessions_lock = asyncio.Lock()
MAX_FOLLOWUP_QUESTIONS = 5

# 正則表達式
url_regex = re.compile(r'https?://\S+')

# ----------------------------------------------------------------------
# 異步輔助功能
# ----------------------------------------------------------------------
async def show_loading_animation_async(chat_id: str, loading_seconds: int = 60):
    """非同步發送 LINE loading 動畫，給予使用者即時回饋"""
    if not channel_access_token:
        return
    url = "https://api.line.me/v2/bot/chat/loading/start"
    headers = {
        "Authorization": f"Bearer {channel_access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "chatId": chat_id,
        "loadingSeconds": min(loading_seconds, 60)
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 202:
                logger.debug(f"Loading animation started for {chat_id}")
            else:
                logger.debug(f"Loading animation returned {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.debug(f"Error showing loading animation: {e}")

def get_summary_prompt():
    """自然語言結構化摘要提示詞"""
    return [
        {
            "role": "system",
            "content": (
                "將以下原文總結為五個部分，並以清晰的結構呈現，確保結果以 繁體中文 為主：\n"
                "❶ 總結 (Overall Summary)：撰寫約300字或更多，概括內容的主要議題與結論，語氣務實但易於理解。\n"
                "❷ 觀點 (Viewpoints)：列出原文中提到的3~7個主要觀點，並適當補充您對這些觀點的評論或看法，條列呈現。\n"
                "❸ 摘要 (Abstract)：摘錄6到10個核心重點，簡潔有力，並適當搭配表情符號（如✅、⚠️、📌）凸顯關鍵信息。\n"
                "❹ 測驗 (Quiz)：根據內容產出**三題選擇題**，每題有 A、B、C、D 四個選項，並在每題後附上正確答案及簡短解釋。題目應涵蓋內容的重要概念或關鍵知識點。\n"
                "❺ 容易懂 (Easy Know)：使用淺顯易懂的語言，將內容濃縮成一段約80~120字的解釋，適合十二歲孩子理解。\n"
            )
        }
    ]

async def chain_response_async(system_messages, text: str) -> str:
    """非同步呼叫 LLM 生成摘要或回答"""
    headers = {
        "Authorization": f"Bearer {llm_api_key}",
        "Content-Type": "application/json",
    }
    data = {
        "model": llm_model,
        "messages": system_messages + [{"role": "user", "content": text}],
        "max_tokens": llm_max_tokens,
        "temperature": 0.5,
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(llm_base_url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException:
        return "⚠️ LLM API 請求逾時，請稍後再試。"
    except Exception as e:
        logger.error(f"LLM API error: {e}")
        return f"⚠️ LLM API 請求發生錯誤: {str(e)}"

# ----------------------------------------------------------------------
# 網頁與影音非同步抓取處理 (Non-blocking via Thread Pool)
# ----------------------------------------------------------------------
def _sync_scrape_text(url: str) -> Tuple[str, Optional[str]]:
    """同步抓取網頁內容"""
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded is None:
            return "無法提取此網頁的內容。", None
        content = trafilatura.extract(downloaded, include_formatting=True)
        soup = BeautifulSoup(downloaded, 'html.parser')
        title = soup.title.string if soup.title else "無法獲取標題"
        return (content.strip() if content else "無法提取此網頁的文字內容。"), title
    except Exception as e:
        logger.error(f"抓取失敗: {e}")
        return f"抓取過程中發生錯誤: {e}", None

async def scrape_text_from_url_async(url: str) -> Tuple[str, Optional[str]]:
    """
    非同步網頁/文章抓取。
    優先使用 2MD (888-url2md) 高效 Markdown 服務，自動處理動態渲染與格式清理；
    若 2MD 服務異常，自動無縫降級至本地 trafilatura + BeautifulSoup 解析。
    """
    try:
        ok, content, title = await read_url_markdown_async(url)
        if ok and content and len(content.strip()) > 30 and not content.startswith("無法提取"):
            return content.strip(), title
    except Exception as e:
        logger.warning(f"2MD parser exception for {url}: {e}")

    return await asyncio.to_thread(_sync_scrape_text, url)

def _get_cookie_file() -> Optional[str]:
    """取得有效的 YouTube cookies.txt 路徑"""
    for path in ['/app/cookies.txt', 'cookies.txt']:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
    return None

def is_supported_by_ytdlp(url: str) -> bool:
    """檢測 URL 是否被 yt-dlp 支援之影音網站"""
    video_site_patterns = [
        r'youtube\.com|youtu\.be',
        r'vimeo\.com',
        r'bilibili\.com',
        r'dailymotion\.com',
        r'tiktok\.com',
        r'twitch\.tv',
        r'facebook\.com/watch|fb\.watch',
        r'instagram\.com/(p|reel|tv)',
        r'twitter\.com/.*/status|x\.com/.*/status',
        r'soundcloud\.com',
        r'spotify\.com',
        r'bandcamp\.com',
        r'ted\.com/talks',
        r'coursera\.org',
        r'khanacademy\.org',
        r'archive\.org'
    ]
    url_lower = url.lower()
    if not any(re.search(p, url_lower) for p in video_site_patterns):
        return False

    try:
        cookie_path = _get_cookie_file()
        ydl_opts = {'quiet': True, 'no_warnings': True}
        if cookie_path:
            ydl_opts['cookiefile'] = cookie_path
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info and ('formats' in info or info.get('duration', 0) > 0 or 'entries' in info):
                return True
    except Exception as e:
        logger.debug(f"yt-dlp extract_info check returned: {e}")
        # 若為常見影片網址且僅是解析暫時警告，仍視為影音網址
        if any(re.search(p, url_lower) for p in [r'youtube\.com|youtu\.be', r'bilibili\.com', r'tiktok\.com', r'vimeo\.com']):
            return True
        return False
    return False

def _transcribe_with_gemini(audio_file: str) -> str:
    """使用 Gemini 多模態音訊直接轉錄逐字稿"""
    try:
        if not llm_api_key:
            return ""
        from google import genai
        client = genai.Client(api_key=llm_api_key)
        uploaded = client.files.upload(file=audio_file)
        try:
            resp = client.models.generate_content(
                model=llm_model,
                contents=[
                    uploaded,
                    "請將這段音訊完整轉錄為繁體中文逐字稿，保留所有重要細節、數字與說話內容："
                ]
            )
            return resp.text.strip() if resp.text else ""
        finally:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Gemini 音訊轉錄失敗: {e}")
        return ""

def _sync_send_to_whisper(audio_file: str) -> str:
    """同步發送音訊至 Whisper API，失敗時自動切換至 Gemini 多模態語音轉錄"""
    if whisper_api_key and whisper_base_url:
        try:
            with open(audio_file, 'rb') as f:
                files = {'file': ('audio.mp3', f, 'audio/mpeg'), 'model': (None, 'whisper-1')}
                headers = {"Authorization": f"Bearer {whisper_api_key}"}
                import requests
                resp = requests.post(whisper_base_url, headers=headers, files=files, timeout=300)
                if resp.status_code == 200:
                    text = resp.json().get("text", "")
                    if text:
                        return text
        except Exception as e:
            logger.warning(f"Whisper API 轉錄異常，將降級切換至 Gemini 轉錄: {e}")

    # Fallback to Gemini Multimodal Audio
    gemini_result = _transcribe_with_gemini(audio_file)
    if gemini_result:
        return gemini_result
    return "無法獲取音訊轉錄內容"

def _sync_process_audio_transcription(video_url: str) -> str:
    """下載音訊並分段/直接轉錄"""
    import subprocess
    import glob
    audio_file = None
    segment_files = []
    try:
        cookie_path = _get_cookie_file()
        audio_path_prefix = f'/tmp/{uuid.uuid4()}'
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{audio_path_prefix}.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True
        }
        if cookie_path:
            ydl_opts['cookiefile'] = cookie_path

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(video_url, download=True)
            audio_file = f"{audio_path_prefix}.mp3"

        if not os.path.exists(audio_file):
            return "音頻文件未生成，請檢查影音來源。"

        file_size = os.path.getsize(audio_file)
        # 小於 25MB 直接發送
        if file_size <= 25 * 1024 * 1024:
            return _sync_send_to_whisper(audio_file)

        # 超過 25MB 進行分段
        segment_duration = 600
        segment_prefix = f"/tmp/segment_{uuid.uuid4()}"
        cmd = [
            'ffmpeg', '-i', audio_file,
            '-f', 'segment',
            '-segment_time', str(segment_duration),
            '-c', 'copy',
            f'{segment_prefix}_%03d.mp3'
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode != 0:
            return f"音頻分段失敗: {res.stderr}"

        segment_files = sorted(glob.glob(f"{segment_prefix}_*.mp3"))
        transcripts = []
        for sf in segment_files:
            if os.path.getsize(sf) <= 25 * 1024 * 1024:
                transcripts.append(_sync_send_to_whisper(sf))
        return " ".join(transcripts)

    except Exception as e:
        return f"音頻轉錄失敗: {str(e)}"
    finally:
        if audio_file and os.path.exists(audio_file):
            try:
                os.remove(audio_file)
            except Exception:
                pass
        for sf in segment_files:
            if os.path.exists(sf):
                try:
                    os.remove(sf)
                except Exception:
                    pass

def _sync_process_video_url(video_url: str) -> Tuple[str, Optional[str]]:
    """提取影音字幕或音訊逐字稿"""
    try:
        cookie_path = _get_cookie_file()
        ydl_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'skip_download': True,
            'subtitleslangs': ['zh-Hant', 'zh-TW', 'zh-Hans', 'zh', 'en'],
            'outtmpl': '/tmp/%(id)s.%(ext)s',
            'quiet': True
        }
        if cookie_path:
            ydl_opts['cookiefile'] = cookie_path
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            video_id = info.get('id', str(uuid.uuid4()))
            video_title = info.get('title', '無法獲取標題')

            # 優先從 metadata 的字幕或自動字幕 URL 直接抓取內容
            subs = info.get('subtitles') or {}
            auto_subs = info.get('automatic_captions') or {}
            for lang in ['zh-Hant', 'zh-TW', 'zh-Hans', 'zh', 'en']:
                target_formats = subs.get(lang) or auto_subs.get(lang) or []
                for fmt in target_formats:
                    if fmt.get('ext') in ['vtt', 'srv1', 'srv2', 'srv3', 'json3']:
                        sub_url = fmt.get('url')
                        if sub_url:
                            try:
                                import requests
                                resp = requests.get(sub_url, timeout=15)
                                if resp.status_code == 200 and resp.text:
                                    return resp.text, video_title
                            except Exception as sub_e:
                                logger.debug(f"直接下載字幕 URL 失敗: {sub_e}")

            for lang in ['zh-Hant', 'zh-TW', 'zh-Hans', 'zh', 'en']:
                sub_path = f"/tmp/{video_id}.{lang}.vtt"
                if os.path.exists(sub_path):
                    with open(sub_path, 'r', encoding='utf-8') as f:
                        sub_content = f.read()
                    try:
                        os.remove(sub_path)
                    except Exception:
                        pass
                    return sub_content, video_title

        # 若無字幕則轉錄音訊
        transcription = _sync_process_audio_transcription(video_url)
        return transcription, video_title
    except Exception as e:
        return f"影片處理失敗: {str(e)}", None

async def process_video_url_async(video_url: str) -> Tuple[str, Optional[str]]:
    """非同步包裝影音處理"""
    return await asyncio.to_thread(_sync_process_video_url, video_url)

# ----------------------------------------------------------------------
# 圖片生成與雲端儲存
# ----------------------------------------------------------------------
async def upload_image_to_storage_async(image_data: bytes, filename: str, mime_type: str = "image/png", title: Optional[str] = None) -> Optional[str]:
    """上傳圖片至 888box 多端點儲存（Primary: box.david888.com, Fallbacks: box.glsoft.ai, box.aiurl.tw）"""
    try:
        res = await upload_bytes_async(
            data_bytes=image_data,
            filename=filename,
            content_type=mime_type,
            title=title or filename
        )
        if res.get("result") == "success":
            return res.get("data", {}).get("url") or res.get("url")
    except Exception as e:
        logger.warning(f"888box upload failed: {e}")

    # GCS 備援
    if gcs_bucket:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_name = f"linebot_images/{timestamp}_{filename}"
            blob = gcs_bucket.blob(unique_name)
            await asyncio.to_thread(blob.upload_from_string, image_data, content_type=mime_type)
            from urllib.parse import quote
            return f"https://storage.googleapis.com/{gcs_bucket.name}/{quote(unique_name, safe='/')}"
        except Exception as e:
            logger.error(f"GCS upload failed: {e}")

    return None

async def generate_image_with_gemini_async(prompt: str) -> Tuple[bool, str]:
    """使用 Gemini 生成圖片並非同步上傳至 888box 雲端儲存"""
    if not gemini_image_key:
        return False, "❌ 尚未設定 GEMINI_IMAGE_API_KEY"

    if not genai_v2:
        return False, "❌ 未安裝 google-genai 依賴套件"

    try:
        client = genai_v2.Client(api_key=gemini_image_key)
        contents = [
            genai_types.Content(
                role="user",
                parts=[genai_types.Part.from_text(text=f"Generate photorealistic image of: {prompt}")],
            ),
        ]
        config = genai_types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])

        def _sync_generate():
            return list(client.models.generate_content_stream(model=gemini_image_model, contents=contents, config=config))

        chunks = await asyncio.to_thread(_sync_generate)

        for chunk in chunks:
            if hasattr(chunk, 'candidates') and chunk.candidates:
                part = chunk.candidates[0].content.parts[0]
                if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                    inline = part.inline_data
                    ext = mimetypes.guess_extension(inline.mime_type) or '.png'
                    safe_p = "".join(c if c.isalnum() else '_' for c in prompt)[:30]
                    fn = f"gemini_{safe_p}{ext}"
                    image_url = await upload_image_to_storage_async(inline.data, fn, inline.mime_type, title=prompt)
                    if image_url:
                        return True, image_url

        return False, "❌ 模型未回傳圖片資料，請嘗試更具體的描述。"
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        return False, f"❌ 圖片生成失敗: {str(e)}"

# ----------------------------------------------------------------------
# 非同步訊息分段與發送
# ----------------------------------------------------------------------
async def send_response_async(to_id: str, text: str, reply_token: Optional[str] = None):
    """
    發送文字訊息至使用者或群組。
    優先嘗試 reply_token 回覆，若失敗或過期則自動使用 push_message 發送。
    自動將超過 2000 字元的長文本分段發送。
    採用原生非同步 HTTP (httpx)，完全獨立於 SDK 事件迴圈生命週期，具備極高可靠度。
    """
    if not channel_access_token or not text:
        return

    MAX_LEN = 2000
    chunks = []
    for i in range(0, len(text), MAX_LEN):
        chunk = text[i:i + MAX_LEN]
        if i > 0:
            chunk = f"【續 {i//MAX_LEN + 1}】\n{chunk}"
        chunks.append(chunk)

    if not chunks:
        return

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel_access_token}"
    }

    # 嘗試第一則使用 reply_token
    replied = False
    if reply_token:
        try:
            payload = {
                "replyToken": reply_token,
                "messages": [{"type": "text", "text": chunks[0]}]
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=payload)
                if resp.status_code == 200:
                    replied = True
                else:
                    logger.debug(f"Reply with token failed ({resp.status_code}: {resp.text}), falling back to push_message")
        except Exception as e:
            logger.debug(f"Reply with token exception ({e}), falling back to push_message")

    start_idx = 1 if replied else 0
    for chunk in chunks[start_idx:]:
        if not to_id:
            continue
        try:
            payload = {
                "to": to_id,
                "messages": [{"type": "text", "text": chunk}]
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post("https://api.line.me/v2/bot/message/push", headers=headers, json=payload)
                if resp.status_code != 200:
                    logger.error(f"Push message failed for {to_id} ({resp.status_code}: {resp.text})")
        except Exception as e:
            logger.error(f"Push message exception for {to_id}: {e}")

async def send_image_async(to_id: str, image_url: str, reply_token: Optional[str] = None):
    """發送圖片訊息給使用者"""
    if not channel_access_token or not image_url:
        return

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel_access_token}"
    }
    img_msg = {
        "type": "image",
        "originalContentUrl": image_url,
        "previewImageUrl": image_url
    }

    replied = False
    if reply_token:
        try:
            payload = {"replyToken": reply_token, "messages": [img_msg]}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=payload)
                if resp.status_code == 200:
                    replied = True
        except Exception as e:
            logger.debug(f"Image reply failed: {e}")

    if not replied and to_id:
        try:
            payload = {"to": to_id, "messages": [img_msg]}
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post("https://api.line.me/v2/bot/message/push", headers=headers, json=payload)
        except Exception as e:
            logger.error(f"Image push failed: {e}")

# ----------------------------------------------------------------------
# 非同步事件處理核心 (Worker Pipeline)
# ----------------------------------------------------------------------
async def handle_message_event_async(event: Any):
    """
    背景非同步處理各類 LINE 訊息事件。
    在背景任務中執行，完全不阻擋 LINE Webhook 200 OK 回應！
    支援原生 dict 與 SDK Event 物件。
    """
    if isinstance(event, dict):
        source = event.get('source', {})
        to_id = source.get('groupId') or source.get('roomId') or source.get('userId') or ''
        user_id = source.get('userId') or to_id
        msg_obj = event.get('message', {})
        msg = str(msg_obj.get('text', '')).strip()
        reply_token = event.get('replyToken')
    else:
        source = getattr(event, 'source', None)
        to_id = getattr(source, 'group_id', None) or getattr(source, 'room_id', None) or getattr(source, 'user_id', '')
        user_id = getattr(source, 'user_id', to_id)
        msg = str(getattr(getattr(event, 'message', None), 'text', '')).strip()
        reply_token = getattr(event, 'reply_token', None)

    if not msg:
        return

    logger.info(f"Processing message from {user_id} in {to_id}: {msg[:50]}")

    try:
        # 1. 888box 儲存庫狀態查詢指令
        storage_cmds = ['!box', '!storage', '!stats', '!空間', '!容量']
        if any(msg.lower() == cmd for cmd in storage_cmds):
            stats = await get_stats_async()
            if stats.get("result") == "success":
                data = stats.get("data", {})
                reply = (
                    f"📦 雲端儲存空間狀態 (888box)\n"
                    f"🔗 主端點: {stats.get('endpoint')}\n"
                    f"📊 總資產數: {data.get('total', 0)}\n"
                    f"🖼️ 圖片數: {data.get('image', 0)}\n"
                    f"🎥 影片數: {data.get('video', 0)}\n"
                    f"🎵 音訊數: {data.get('audio', 0)}\n"
                    f"📁 一般檔案: {data.get('file', 0)}"
                )
            else:
                reply = f"❌ 取得儲存空間狀態失敗: {stats.get('message', '未知錯誤')}"
            await send_response_async(to_id, reply, reply_token)
            return

        # 2. AI 圖片生成指令
        image_cmds = ['!img', '!畫圖', '!生成圖片', '!image', '!draw']
        if any(msg.lower().startswith(cmd) for cmd in image_cmds):
            prompt = msg
            for cmd in image_cmds:
                if msg.lower().startswith(cmd):
                    prompt = msg[len(cmd):].strip()
                    break

            if not prompt:
                await send_response_async(to_id, "請提供圖片描述，例如：`!img 可愛的柴犬在櫻花樹下`", reply_token)
                return

            await show_loading_animation_async(to_id, 60)
            success, result = await generate_image_with_gemini_async(prompt)
            if success:
                await send_image_async(to_id, result, reply_token)
            else:
                await send_response_async(to_id, result, reply_token)
            return

        # 3. 即時聯網搜尋指令 (!s / !search / !google / !查 / !新聞)
        search_cmds = ['!s', '!search', '!google', '!find', '!查詢', '!搜尋', '!查', '!新聞', '!news']
        if any(msg.lower().startswith(cmd) for cmd in search_cmds):
            query = msg
            for cmd in search_cmds:
                if msg.lower().startswith(cmd):
                    query = msg[len(cmd):].strip()
                    break

            if not query:
                await send_response_async(to_id, "請提供搜尋關鍵字，例如：`!s SpaceX 最新動態` 或 `!新聞 台積電`", reply_token)
                return

            await show_loading_animation_async(to_id, 60)
            ok, search_results = await search_web_async(query)
            if ok:
                system_messages = [
                    {
                        "role": "system",
                        "content": (
                            "你是一個具備即時聯網瀏覽與深度分析能力的專業 AI 助手。\n"
                            f"使用者搜尋問題：【{query}】\n\n"
                            "以下是透過即時網路檢索 (2MD SERP Engine) 獲得的最新現場資料：\n\n"
                            f"{search_results}\n\n"
                            "請根據以上即時搜尋結果，以繁體中文提供全面、條理分明、客觀準確的解答。\n"
                            "若有具體數據、最新事件、或重要來源，請在回答中清楚標註與引用來源網址。"
                        )
                    }
                ]
                answer = await chain_response_async(system_messages, query)
                full_reply = f"🔍 **即時聯網檢索結果**：【{query}】\n\n{answer}\n\n💡 您可以繼續針對此搜尋主題提問（最多可續問 {MAX_FOLLOWUP_QUESTIONS} 次）"
                await send_response_async(to_id, full_reply, reply_token)

                async with user_sessions_lock:
                    user_sessions[user_id] = {
                        "content": search_results + "\n\n" + answer,
                        "title": f"搜尋：{query}",
                        "remaining": MAX_FOLLOWUP_QUESTIONS
                    }
            else:
                await send_response_async(to_id, f"🔍 網路檢索失敗：{search_results}", reply_token)
            return

        # 4. 網址摘要處理 (影音或網頁)
        url_match = url_regex.search(msg)
        if url_match:
            url = url_match.group()
            await show_loading_animation_async(to_id, 60)

            # 檢測影音網站 vs 普通網頁
            if is_supported_by_ytdlp(url):
                logger.info(f"Processing as video URL: {url}")
                transcription, video_title = await process_video_url_async(url)
                if transcription and (transcription.startswith("影片處理失敗") or transcription.startswith("音頻轉錄失敗") or transcription.startswith("音頻文件未生成")):
                    await send_response_async(to_id, transcription, reply_token)
                    return

                system_prompt = get_summary_prompt()
                summary = await chain_response_async(system_prompt, transcription)
                title_display = f"【{video_title}】" if video_title else "【影音內容摘要】"
                full_reply = f"{title_display}\n\n{summary}\n\n💡 您可以繼續詢問這個影片的相關問題（最多可續問 {MAX_FOLLOWUP_QUESTIONS} 次）"
                await send_response_async(to_id, full_reply, reply_token)

                async with user_sessions_lock:
                    user_sessions[user_id] = {
                        "content": transcription,
                        "title": video_title or "影音內容",
                        "remaining": MAX_FOLLOWUP_QUESTIONS
                    }
                return
            else:
                logger.info(f"Processing as regular webpage URL: {url}")
                content, title = await scrape_text_from_url_async(url)
                if content.startswith("無法提取") or content.startswith("抓取過程中發生錯誤"):
                    await send_response_async(to_id, content, reply_token)
                    return

                system_prompt = get_summary_prompt()
                summary = await chain_response_async(system_prompt, content)
                title_display = f"【標題】: {title}" if title else "【網頁內容摘要】"
                full_reply = f"{title_display}\n\n{summary}\n\n💡 您可以繼續詢問這個網頁的相關問題（最多可續問 {MAX_FOLLOWUP_QUESTIONS} 次）"
                await send_response_async(to_id, full_reply, reply_token)

                async with user_sessions_lock:
                    user_sessions[user_id] = {
                        "content": content,
                        "title": title or "網頁內容",
                        "remaining": MAX_FOLLOWUP_QUESTIONS
                    }
                return

        # 5. 續問功能處理
        async with user_sessions_lock:
            session = user_sessions.get(user_id)

        if session and session.get("remaining", 0) > 0:
            await show_loading_animation_async(to_id, 30)
            system_messages = [
                {
                    "role": "system",
                    "content": f"你是一個專業的內容分析助手。以下是【{session['title']}】的完整內容：\n\n{session['content']}\n\n請根據以上內容，用繁體中文回答使用者的問題。回答要準確、具體，並引用原文相關部分。"
                }
            ]
            answer = await chain_response_async(system_messages, msg)

            async with user_sessions_lock:
                session["remaining"] -= 1
                rem = session["remaining"]
                if rem == 0:
                    del user_sessions[user_id]

            rem_text = f"\n\n📊 剩餘續問次數: {rem}"
            if rem == 0:
                rem_text += "\n\n💬 續問次數已用完，請提供新的網址或搜尋開始新的對話。"

            full_reply = answer + rem_text
            await send_response_async(to_id, full_reply, reply_token)
            return

        # 6. 智慧聯網問答 (針對一般自然語言提問自動即時搜尋網路)
        greetings = ['hi', 'hello', '你好', '您好', '嗨', 'help', '說明', '指令', 'start']
        if msg.lower() in greetings or len(msg) < 2:
            default_help = (
                "🤖 **小濃縮 - 智能聯網與多媒體摘要助手**\n\n"
                "📌 **核心功能**：\n"
                "1. 🌐 **即時聯網瀏覽**：直接輸入任何問題（例如：`SpaceX 最近有何動態？` 或 `!s 台積電最新財報`），自動搜尋全網即時事實並精準回答。\n"
                "2. 🎥 **1000+ 影音與文章摘要**：傳送 YouTube、Bilibili、TikTok 影片或任意網頁連結，自動提取並產出結構化繁體中文摘要。\n"
                "3. 💬 **深度續問**：摘要或搜尋後可連續提問 5 次，由 AI 依據原文深入解答。\n"
                "4. 🎨 **AI 圖片生成**：輸入 `!img [提示詞]` 產出高畫質圖片。\n"
                "5. 📦 **雲端資產庫**：輸入 `!box` 即時查詢 888box 雲端儲存狀態。"
            )
            await send_response_async(to_id, default_help, reply_token)
            return

        # 一般提問：自動聯網搜尋回答
        await show_loading_animation_async(to_id, 60)
        logger.info(f"Auto-browsing live web for question: {msg[:50]}")
        ok, search_results = await search_web_async(msg)
        if ok and len(search_results.strip()) > 50:
            system_messages = [
                {
                    "role": "system",
                    "content": (
                        "你是一個具備即時聯網瀏覽能力、零幻覺、準確權威的 AI 助手。\n"
                        f"使用者問題：【{msg}】\n\n"
                        "以下是透過 2MD SERP Engine 即時檢索獲得的最新網路現場資訊：\n\n"
                        f"{search_results}\n\n"
                        "請根據以上即時搜尋資訊，以繁體中文給出清晰、精確、有深度且附帶關鍵來源的解答。"
                    )
                }
            ]
            answer = await chain_response_async(system_messages, msg)
            full_reply = f"🌐 **即時聯網回答**：\n\n{answer}\n\n💡 您可以繼續針對此內容提問（剩餘 {MAX_FOLLOWUP_QUESTIONS} 次續問）"
            await send_response_async(to_id, full_reply, reply_token)

            async with user_sessions_lock:
                user_sessions[user_id] = {
                    "content": search_results + "\n\n" + answer,
                    "title": f"問題：{msg[:20]}",
                    "remaining": MAX_FOLLOWUP_QUESTIONS
                }
        else:
            # 若搜尋無結果，直接由 LLM 知識庫回答
            system_messages = [
                {
                    "role": "system",
                    "content": "你是一個專業的繁體中文 AI 助理，請熱情、準確、條理清晰地回答使用者的問題。"
                }
            ]
            answer = await chain_response_async(system_messages, msg)
            await send_response_async(to_id, answer, reply_token)

    except Exception as e:
        logger.error(f"Error handling event for {user_id}: {e}", exc_info=True)
        await send_response_async(to_id, f"⚠️ 處理請求時發生錯誤: {str(e)}", reply_token)

# ----------------------------------------------------------------------
# FastAPI 路由端點
# ----------------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "LINE Bot Smart Summary & Media Bot",
        "version": "3.0.0",
        "async_pipeline": "enabled",
        "storage_endpoints": [
            "https://box.david888.com (Primary)",
            "https://box.glsoft.ai (Fallback 1)",
            "https://box.aiurl.tw (Fallback 2)"
        ]
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.post("/callback")
async def callback(request: Request, background_tasks: BackgroundTasks):
    """
    LINE Webhook 回呼入口點。
    🚀 即刻回應 200 OK (< 30ms)，所有繁重工作透過 BackgroundTasks 非同步分派，徹底消除多用戶併發塞車問題！
    """
    signature = request.headers.get('X-Line-Signature', '')
    body = await request.body()

    # 1. 驗證簽章 (HMAC-SHA256)
    if channel_secret:
        hash_val = hmac.new(channel_secret.encode('utf-8'), body, hashlib.sha256).digest()
        computed_sig = base64.b64encode(hash_val).decode('utf-8')
        if not hmac.compare_digest(computed_sig, signature):
            logger.warning(f"Invalid LINE webhook signature. Received: {signature}")
            raise HTTPException(status_code=400, detail="Invalid signature")

    # 2. 解析 JSON 內容
    try:
        body_str = body.decode('utf-8')
        body_json = json.loads(body_str)
        events = body_json.get('events', [])
    except Exception as e:
        logger.error(f"Webhook parse error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    # 3. 分派事件
    for event in events:
        if event.get('type') == 'message' and event.get('message', {}).get('type') == 'text':
            logger.info(f"Enqueuing message event: {event.get('webhookEventId') or 'event'}")
            background_tasks.add_task(handle_message_event_async, event)

    # 迅速回傳 200 OK 給 LINE Webhook 伺服器
    return JSONResponse(content={"status": "ok"}, status_code=200)

async def _periodic_ytdlp_update():
    """定期自動更新 yt-dlp 保持最新版本"""
    while True:
        try:
            logger.info("Checking and upgrading yt-dlp to latest version...")
            import sys
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", "--no-cache-dir", "-U", "--pre", "yt-dlp[default]",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.info("yt-dlp auto-update check completed successfully.")
            else:
                logger.warning(f"yt-dlp auto-update warning: {stderr.decode()}")
        except Exception as e:
            logger.warning(f"Failed to auto-update yt-dlp: {e}")
        # 每 24 小時檢查一次
        await asyncio.sleep(86400)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(_periodic_ytdlp_update())

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv('PORT', 5000))
    uvicorn.run(app, host='0.0.0.0', port=port)
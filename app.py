import os
import re
import json
import uuid
import logging
import asyncio
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
import httpx
from bs4 import BeautifulSoup
import yt_dlp
import trafilatura
import mimetypes

# LINE Bot SDK v3
from linebot.v3.webhook import WebhookParser
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    ImageMessage
)
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

# 888box 雲端多端點儲存模組
from src.box_storage import (
    BoxStorageClient,
    upload_bytes_async,
    upload_text_async,
    upload_file_async,
    upload_url_async,
    get_stats_async
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

configuration = Configuration(access_token=channel_access_token or "dummy_token")
parser = WebhookParser(channel_secret or "dummy_secret")
line_bot_api = AsyncMessagingApi(configuration)

# LLM API 配置
llm_base_url_raw = os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1')
if llm_base_url_raw.endswith('/'):
    llm_base_url_raw = llm_base_url_raw.rstrip('/')
if not llm_base_url_raw.endswith('/chat/completions'):
    llm_base_url = llm_base_url_raw + '/chat/completions'
else:
    llm_base_url = llm_base_url_raw

llm_api_key = os.getenv('LLM_API_KEY', '')
llm_model = os.getenv('LLM_MODEL', 'gemini-2.0-flash')
llm_max_tokens = int(os.getenv('MAX_TOKEN_LIMIT', '900000'))

# Whisper API 配置
whisper_base_url = os.getenv('WHISPER_BASE_URL', 'https://api.openai.com/v1/audio/transcriptions')
whisper_api_key = os.getenv('WHISPER_API_KEY', '')

# Gemini Image 配置
gemini_image_key = os.getenv('GEMINI_IMAGE_API_KEY', '')
gemini_image_model = os.getenv('GEMINI_IMAGE_MODEL', 'gemini-2.5-flash-image-preview')

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
    """非同步包裝網頁抓取"""
    return await asyncio.to_thread(_sync_scrape_text, url)

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
        ydl_opts = {'quiet': True, 'no_warnings': True, 'cookiesfile': 'cookies.txt' if os.path.exists('cookies.txt') else None}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info and ('formats' in info or info.get('duration', 0) > 0):
                return True
    except Exception as e:
        logger.debug(f"yt-dlp extract_info check returned: {e}")
        return False
    return False

def _sync_send_to_whisper(audio_file: str) -> str:
    """同步發送音訊至 Whisper API"""
    try:
        with open(audio_file, 'rb') as f:
            files = {'file': ('audio.mp3', f, 'audio/mpeg'), 'model': (None, 'whisper-1')}
            headers = {"Authorization": f"Bearer {whisper_api_key}"}
            import requests
            resp = requests.post(whisper_base_url, headers=headers, files=files, timeout=300)
            resp.raise_for_status()
            return resp.json().get("text", "無法獲取轉錄內容")
    except Exception as e:
        return f"Whisper API 轉錄失敗: {str(e)}"

def _sync_process_audio_transcription(video_url: str) -> str:
    """下載音訊並分段/直接轉錄"""
    import subprocess
    import glob
    audio_file = None
    segment_files = []
    try:
        audio_path_prefix = f'/tmp/{uuid.uuid4()}'
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{audio_path_prefix}.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'cookiesfile': 'cookies.txt' if os.path.exists('cookies.txt') else None,
            'quiet': True
        }
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
        ydl_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'skip_download': True,
            'subtitleslangs': ['zh-Hant', 'zh-TW', 'zh-Hans', 'zh', 'en'],
            'outtmpl': '/tmp/%(id)s.%(ext)s',
            'cookiesfile': 'cookies.txt' if os.path.exists('cookies.txt') else None,
            'quiet': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            video_id = info.get('id', str(uuid.uuid4()))
            video_title = info.get('title', '無法獲取標題')

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
    發送訊息至使用者或群組。
    優先嘗試 reply_token 回覆，若失敗或過期則自動使用 push_message 發送。
    自動將超過 2000 字元的長文本分段發送。
    """
    MAX_LEN = 2000
    chunks = []
    for i in range(0, len(text), MAX_LEN):
        chunk = text[i:i + MAX_LEN]
        if i > 0:
            chunk = f"【續 {i//MAX_LEN + 1}】\n{chunk}"
        chunks.append(chunk)

    if not chunks:
        return

    # 嘗試第一則使用 reply_token
    replied = False
    if reply_token:
        try:
            await line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=chunks[0])]
                )
            )
            replied = True
        except Exception as e:
            logger.debug(f"Reply with token failed ({e}), falling back to push_message")

    start_idx = 1 if replied else 0
    for chunk in chunks[start_idx:]:
        try:
            await line_bot_api.push_message(
                PushMessageRequest(
                    to=to_id,
                    messages=[TextMessage(text=chunk)]
                )
            )
        except Exception as e:
            logger.error(f"Push message failed for {to_id}: {e}")

# ----------------------------------------------------------------------
# 非同步事件處理核心 (Worker Pipeline)
# ----------------------------------------------------------------------
async def handle_message_event_async(event: MessageEvent):
    """
    背景非同步處理各類 LINE 訊息事件。
    在背景任務中執行，完全不阻擋 LINE Webhook 200 OK 回應！
    """
    source = event.source
    to_id = source.group_id if hasattr(source, 'group_id') and source.group_id else (
        source.room_id if hasattr(source, 'room_id') and source.room_id else source.user_id
    )
    user_id = source.user_id if hasattr(source, 'user_id') else to_id
    msg = event.message.text.strip()
    reply_token = event.reply_token

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
                try:
                    img_msg = ImageMessage(original_content_url=result, preview_image_url=result)
                    await line_bot_api.push_message(PushMessageRequest(to=to_id, messages=[img_msg]))
                except Exception as img_err:
                    logger.error(f"Failed to send image message: {img_err}")
                    await send_response_async(to_id, f"🎨 圖片生成成功，但發送失敗。圖片網址：{result}")
            else:
                await send_response_async(to_id, result, reply_token)
            return

        # 3. 網址摘要處理 (影音或網頁)
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

        # 4. 續問功能處理
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
                rem_text += "\n\n💬 續問次數已用完，請提供新的網址開始新的對話。"

            full_reply = answer + rem_text
            await send_response_async(to_id, full_reply, reply_token)
            return

        # 5. 預設說明回應
        default_help = (
            "🤖 **LINE 智能摘要與資產助手**\n\n"
            "📌 **使用方式**：\n"
            "1. 傳送任何 **YouTube、Bilibili、TikTok 等 1000+ 影音連結** 或 **普通網頁文章**，自動生成結構化繁體中文摘要並支援 5 次續問。\n"
            "2. 輸入 `!img [提示詞]` 生成高畫質 AI 圖片。\n"
            "3. 輸入 `!box` 即時查詢 888box 雲端儲存空間狀態與資產計數。"
        )
        await send_response_async(to_id, default_help, reply_token)

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
    body_str = body.decode('utf-8')

    try:
        events = parser.parse(body_str, signature)
    except InvalidSignatureError:
        logger.warning("Invalid LINE webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"Webhook parse error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    for event in events:
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
            # 非同步排程背景任務，立即釋放 HTTP 回應連線
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
import os
import re
import requests
import json
import uuid
import logging
import asyncio
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from linebot.v3.webhook import WebhookParser
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    ImageMessage)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
)
from bs4 import BeautifulSoup
import yt_dlp
import trafilatura
import google.generativeai as genai
from google import genai as genai_v2
from google.genai import types
from google.cloud import storage
import mimetypes
from src.box_storage import (
    BoxStorageClient,
    upload_bytes_async,
    upload_text_async,
    upload_file_async,
    upload_url_async,
    get_stats_async,
)

# 設定日誌
logging.basicConfig(
    level=os.getenv('LOG', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__file__)

app = FastAPI()

# LINE 配置
channel_secret = os.getenv('CHANNEL_SECRET')
channel_access_token = os.getenv('CHANNEL_ACCESS_TOKEN')
if channel_secret is None:
    logger.error('Specify CHANNEL_SECRET as environment variable.')
    raise ValueError('CHANNEL_SECRET is required')
if channel_access_token is None:
    logger.error('Specify CHANNEL_ACCESS_TOKEN as environment variable.')
    raise ValueError('CHANNEL_ACCESS_TOKEN is required')

configuration = Configuration(access_token=channel_access_token)
parser = WebhookParser(channel_secret)

# API 配置
llm_base_url = os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1/chat/completions')
llm_api_key = os.getenv('LLM_API_KEY')
llm_model = os.getenv('LLM_MODEL', 'gemini-2.0-flash')
llm_max_tokens = int(os.getenv('MAX_TOKEN_LIMIT', '900000'))
whisper_base_url = os.getenv('WHISPER_BASE_URL', 'https://api.openai.com/v1/audio/transcriptions')
whisper_api_key = os.getenv('WHISPER_API_KEY')

# Gemini Image 設定
gemini_image_key = os.getenv('GEMINI_IMAGE_API_KEY')
gemini_image_model = os.getenv('GEMINI_IMAGE_MODEL', 'gemini-2.5-flash-image-preview')

# Google Cloud Storage 設定
gcs_bucket_name = os.getenv('GCS_BUCKET_NAME')
gcs_credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

# 正則表達式
url_regex = re.compile(r'https?://\S+')
youtube_regex = re.compile(r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]+)')

# 初始化客戶端
line_bot_api = AsyncMessagingApi(configuration)

# 初始化 Gemini LLM
if llm_api_key:
    genai.configure(api_key=llm_api_key)

# 初始化 GCS
if gcs_credentials_path and gcs_bucket_name:
    try:
        logger.info("Initializing Google Cloud Storage...")
        storage_client = storage.Client()
        bucket = storage_client.bucket(gcs_bucket_name)
        logger.info(f"GCS bucket initialized: {gcs_bucket_name}")
    except Exception as e:
        logger.error(f"Failed to initialize GCS: {e}")
        bucket = None
else:
    bucket = None
    logger.warning("GCS not configured")

# 自然語言摘要提示詞
def get_summary_prompt():
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

# 使用 LLM 生成摘要
async def chain_response(system_messages, text, base_url, api_key, model, max_tokens):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = {
        "model": model,
        "messages": system_messages + [{"role": "user", "content": text}],
        "max_tokens": max_tokens,
        "temperature": 0.5,
    }
    try:
        response = requests.post(base_url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        try:
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"API 回傳格式錯誤: {str(e)}\n原始回應: {response.text}"
    except requests.exceptions.Timeout:
        return "API 請求逾時，請稍後再試。"
    except requests.exceptions.RequestException as e:
        return f"API 請求發生錯誤: {str(e)}\n原始回應: {getattr(e.response, 'text', '')}"

# 從普通網頁抓取內容
async def scrape_text_from_url(url):
    try:
        logger.info(f"Scraping URL: {url}")
        downloaded = trafilatura.fetch_url(url)
        if downloaded is None:
            return "無法提取此網頁的內容。", None

        content = trafilatura.extract(downloaded, include_formatting=True)
        soup = BeautifulSoup(downloaded, 'html.parser')
        title = soup.title.string if soup.title else "無法獲取標題"
        return content.strip(), title
    except Exception as e:
        logger.error(f"抓取失敗: {e}")
        return "抓取過程中發生錯誤。", None

# 使用 yt-dlp 提取字幕或音訊
async def process_youtube_video(youtube_url):
    try:
        logger.info(f"Starting to process YouTube URL: {youtube_url}")

        # 嘗試下載字幕
        ydl_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'skip_download': True,
            'subtitleslangs': ['zh-Hant', 'zh-TW', 'en'],
            'outtmpl': '/tmp/%(id)s.%(ext)s',
            'cookiesfile': 'cookies.txt'
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            video_id = info['id']
            video_title = info.get('title', '無法獲取標題')
            logger.info(f"Video ID: {video_id}, Title: {video_title}")

            for lang in ['zh-Hant', 'zh-TW', 'en']:
                subtitle_path = f"/tmp/{video_id}.{lang}.vtt"
                logger.info(f"Checking for subtitles at {subtitle_path}")
                if os.path.exists(subtitle_path):
                    logger.info(f"Found subtitles: {subtitle_path}")
                    with open(subtitle_path, 'r', encoding='utf-8') as file:
                        subtitle_content = file.read()
                    # 清理字幕文件
                    os.remove(subtitle_path)
                    return subtitle_content, video_title

        # 如果無字幕,下載音頻並進行轉錄
        logger.info("No subtitles found, falling back to audio transcription.")
        transcription = await audio_transcription(youtube_url)
        return transcription, video_title
    except Exception as e:
        error_message = f"影片處理失敗: {str(e)}"
        logger.error(error_message)
        return error_message, None

async def audio_transcription(youtube_url):
    """下載完整音頻，檢查大小，如果超過25MB則分段發送給Whisper API"""
    audio_file = None
    try:
        logger.info(f"Starting audio transcription for: {youtube_url}")
        audio_file_path = f'/tmp/{str(uuid.uuid4())}'
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{audio_file_path}.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'ffmpeg_location': '/usr/bin/ffmpeg',
            'ffprobe_location': '/usr/bin/ffprobe',
            'cookiesfile': 'cookies.txt'
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            audio_file = f"{audio_file_path}.mp3"

            if not os.path.exists(audio_file):
                error_message = "音頻文件未生成,請檢查下載過程。"
                logger.error(error_message)
                return error_message

            file_size = os.path.getsize(audio_file)
            logger.info(f"Audio file downloaded: {audio_file} ({file_size} bytes)")

            # 檢查文件大小是否超過 Whisper API 限制 (25MB)
            if file_size > 25 * 1024 * 1024:  # 25MB
                logger.info(f"File size {file_size} bytes exceeds 25MB limit, splitting for Whisper API...")
                return await split_and_transcribe(audio_file)
            else:
                logger.info("File size within limit, sending directly to Whisper API...")
                return await send_to_whisper(audio_file)

    except Exception as e:
        error_message = f"音頻轉錄失敗: {str(e)}"
        logger.error(error_message)
        return error_message
    finally:
        # 清理原始音頻文件
        if audio_file and os.path.exists(audio_file):
            try:
                os.remove(audio_file)
                logger.info(f"Cleaned up original audio file: {audio_file}")
            except Exception as cleanup_error:
                logger.error(f"Failed to cleanup audio file: {cleanup_error}")

async def send_to_whisper(audio_file):
    """直接發送音頻文件到 Whisper API"""
    try:
        with open(audio_file, 'rb') as f:
            files = {
                'file': ('audio.mp3', f, 'audio/mpeg'),
                'model': (None, 'whisper-1')
            }
            headers = {
                "Authorization": f"Bearer {whisper_api_key}"
            }
            response = requests.post(whisper_base_url, headers=headers, files=files, timeout=300)
            response.raise_for_status()
            transcript = response.json().get("text", "無法獲取轉錄內容")
            logger.info("Whisper transcription successful.")
            return transcript
    except Exception as e:
        return f"Whisper API 轉錄失敗: {str(e)}"

async def split_and_transcribe(audio_file):
    """將大音頻文件分割成小於25MB的片段，分別發送給 Whisper API"""
    import subprocess
    import glob
    segment_files = []
    transcripts = []

    try:
        # 使用 ffmpeg 按時間分段，確保每段小於25MB
        segment_duration = 600  # 10分鐘一段
        segment_prefix = f"/tmp/whisper_segment_{uuid.uuid4()}"

        cmd = [
            'ffmpeg', '-i', audio_file,
            '-f', 'segment',
            '-segment_time', str(segment_duration),
            '-c', 'copy',
            f'{segment_prefix}_%03d.mp3'
        ]

        logger.info(f"Splitting audio for Whisper API: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            return f"音頻分段失敗: {result.stderr}"

        # 找到所有分段文件
        segment_files = glob.glob(f"{segment_prefix}_*.mp3")
        segment_files.sort()

        logger.info(f"Created {len(segment_files)} segments for Whisper API")

        # 逐個發送分段到 Whisper API
        for i, segment_file in enumerate(segment_files):
            segment_size = os.path.getsize(segment_file)
            logger.info(f"Sending segment {i+1}/{len(segment_files)} to Whisper API: {segment_file} ({segment_size} bytes)")

            # 確保分段文件不超過25MB
            if segment_size > 25 * 1024 * 1024:
                logger.info(f"Warning: Segment {i+1} still too large ({segment_size} bytes), skipping...")
                transcripts.append(f"[分段 {i+1} 文件過大，跳過處理]")
                continue

            try:
                segment_transcript = await send_to_whisper(segment_file)
                transcripts.append(segment_transcript)
                logger.info(f"Segment {i+1} transcription successful.")

            except Exception as e:
                logger.error(f"Segment {i+1} transcription failed: {e}")
                transcripts.append(f"[分段 {i+1} 轉錄失敗: {str(e)}]")

        # 合併所有轉錄結果
        full_transcript = " ".join(transcripts)
        logger.info(f"Combined transcript from {len(transcripts)} segments")
        return full_transcript

    except Exception as e:
        return f"分段轉錄失敗: {str(e)}"
    finally:
        # 清理所有分段文件
        for segment_file in segment_files:
            if os.path.exists(segment_file):
                try:
                    os.remove(segment_file)
                    logger.info(f"Cleaned up segment: {segment_file}")
                except Exception as cleanup_error:
                    logger.error(f"Failed to cleanup segment {segment_file}: {cleanup_error}")

async def upload_image_to_gcs(image_data, filename, mime_type="image/png"):
    """
    上傳圖片到 Google Cloud Storage 並返回公開 URL

    Args:
        image_data: 圖片的二進位資料
        filename: 檔案名稱
        mime_type: 圖片的 MIME 類型，預設為 image/png

    Returns:
        str: 圖片的公開 URL，如果失敗則返回 None
    """
    logger.info(f"Starting upload_image_to_gcs - filename: {filename}")

    if not bucket:
        logger.error("Google Cloud Storage not configured")
        return None

    try:
        # 建立唯一的檔案名稱
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = "".join(c if c.isalnum() or c in ('-', '_', '.') else '_' for c in filename)
        unique_filename = f"linebot_images/{timestamp}_{safe_filename}"
        logger.info(f"Generated unique filename: {unique_filename}")

        # 上傳到 GCS
        blob = bucket.blob(unique_filename)
        blob.upload_from_string(image_data, content_type=mime_type)
        logger.info(f"Upload completed with content_type: {mime_type}")

        # 生成公開 URL
        from urllib.parse import quote
        encoded_filename = quote(unique_filename, safe='/')
        public_url = f"https://storage.googleapis.com/{bucket.name}/{encoded_filename}"
        logger.info(f"Image uploaded successfully: {public_url}")
        return public_url

    except Exception as e:
        logger.error(f"Failed to upload image to GCS: {e}")
        return None

async def upload_image_to_storage(image_data, filename, mime_type="image/png", title=None):
    """
    上傳圖片至雲端儲存 (優先使用 888box 多端點儲存，若有設定 GCS 則作為備援)
    """
    logger.info(f"Starting upload_image_to_storage - filename: {filename}")

    # 1. 嘗試上傳至 888box (box.david888.com / box.glsoft.ai / box.aiurl.tw)
    try:
        box_res = await upload_bytes_async(
            data_bytes=image_data,
            filename=filename,
            content_type=mime_type,
            title=title or filename
        )
        if box_res.get("result") == "success":
            image_url = box_res.get("data", {}).get("url") or box_res.get("url")
            if image_url:
                logger.info(f"Image uploaded to Box Storage successfully: {image_url} (endpoint: {box_res.get('endpoint')})")
                return image_url
    except Exception as e:
        logger.warning(f"Failed to upload to Box Storage: {e}")

    # 2. 備援：Google Cloud Storage (若有設定)
    if bucket:
        try:
            return await upload_image_to_gcs(image_data, filename, mime_type)
        except Exception as e:
            logger.error(f"Failed to upload to GCS fallback: {e}")

    return None

async def generate_image_with_gemini(prompt, max_retries=1, retry_delay=15):
    """
    使用 Gemini 生成圖片

    Args:
        prompt: 圖片生成的提示詞
        max_retries: 最大重試次數
        retry_delay: 重試延遲（秒）

    Returns:
        tuple: (成功狀態, 結果訊息或圖片URL)
    """
    logger.info(f"Starting generate_image_with_gemini with prompt: {prompt}")

    # 檢查圖片生成 API 設定
    if not gemini_image_key:
        logger.error("Gemini Image API key not configured")
        return False, "圖片生成功能未設定 API Key"

    for attempt in range(max_retries + 1):
        if attempt > 0:
            logger.info(f"Retry attempt {attempt}/{max_retries} after {retry_delay} seconds...")
            await asyncio.sleep(retry_delay)

        try:
            client = genai_v2.Client(api_key=gemini_image_key)
            model = "gemini-2.5-flash-image-preview"
            logger.info(f"Using image model: {model} (attempt {attempt + 1})")

            prompts_to_try = [
                f"Create a photorealistic image of a {prompt}. Do not provide text description, only generate the actual image.",
                f"Generate image: {prompt}",
                f"Draw: {prompt}"
            ]

            current_prompt = prompts_to_try[min(attempt, len(prompts_to_try) - 1)]
            logger.info(f"Using prompt strategy {attempt + 1}: {current_prompt[:80]}...")

            contents = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=current_prompt),
                    ],
                ),
            ]

            generate_content_config = types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            )

            logger.info("Starting content generation stream...")

            # 生成內容
            image_url = None
            text_response = ""
            chunk_count = 0

            for chunk in client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=generate_content_config,
            ):
                chunk_count += 1
                logger.info(f"Processing chunk {chunk_count}")

                if (
                    not hasattr(chunk, 'candidates') or
                    chunk.candidates is None or
                    len(chunk.candidates) == 0 or
                    chunk.candidates[0].content is None or
                    chunk.candidates[0].content.parts is None or
                    len(chunk.candidates[0].content.parts) == 0
                ):
                    logger.warning(f"Chunk {chunk_count} has no valid content")
                    continue

                part = chunk.candidates[0].content.parts[0]
                logger.info(f"Chunk {chunk_count} part type: {type(part)}")

                # 檢查是否有 inline_data
                if hasattr(part, 'inline_data') and part.inline_data:
                    logger.info(f"Found inline_data in chunk {chunk_count}")
                    if hasattr(part.inline_data, 'data') and part.inline_data.data:
                        logger.info(f"Found image data in chunk {chunk_count}")
                        inline_data = part.inline_data
                        image_data = inline_data.data
                        logger.info(f"Image data size: {len(image_data)} bytes")
                        logger.info(f"Image MIME type: {inline_data.mime_type}")

                        file_extension = mimetypes.guess_extension(inline_data.mime_type) or '.png'
                        logger.info(f"File extension: {file_extension}")

                        # 建立檔案名稱
                        safe_prompt = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in prompt).rstrip()[:30]
                        filename = f"gemini_image_{safe_prompt}{file_extension}"
                        logger.info(f"Generated filename: {filename}")

                        # 上傳到雲端儲存 (Box Storage / GCS)
                        logger.info("Starting upload to storage...")
                        image_url = await upload_image_to_storage(image_data, filename, inline_data.mime_type, title=prompt)
                        logger.info(f"Upload result: {image_url}")

                        # 一旦找到圖片就跳出迴圈
                        if image_url:
                            logger.info("Image found and uploaded successfully, breaking loop")
                            break
                    else:
                        logger.info(f"inline_data exists but no data: {part.inline_data}")
                else:
                    logger.info(f"No inline_data in chunk {chunk_count}")

                # 處理文字回應
                if hasattr(part, 'text') and part.text:
                    text_response += part.text
                    logger.info(f"Received text in chunk {chunk_count}: {part.text[:100]}...")
                elif hasattr(chunk, 'text') and chunk.text:
                    text_response += chunk.text
                    logger.info(f"Received text from chunk object in chunk {chunk_count}: {chunk.text[:100]}...")
                else:
                    logger.info(f"Chunk {chunk_count} has no text data")

            logger.info(f"Finished processing {chunk_count} chunks")
            logger.info(f"Final image_url: {image_url}")
            logger.info(f"Final text_response: {text_response[:200]}...")

            if image_url:
                logger.info("Image generation successful")
                return True, image_url
            else:
                if text_response:
                    logger.warning(f"Model returned text only, no image generated. Text: {text_response[:200]}")
                    return False, f"❌ 模型只返回文字說明而未生成圖片。請嘗試更具體的描述，例如：'一位台灣婦女在傳統市場挑選新鮮蔬菜的真實照片'"
                else:
                    return False, "❌ 圖片生成失敗，請稍後再試。"

        except Exception as e:
            logger.error(f"Error generating image with Gemini (attempt {attempt + 1}): {e}")

            # 檢查是否為配額錯誤
            error_msg = str(e)
            is_quota_error = "429" in error_msg and "RESOURCE_EXHAUSTED" in error_msg
            is_rate_limit = "429" in error_msg

            if attempt < max_retries and is_rate_limit:
                logger.info(f"Rate limit hit, will retry in {retry_delay} seconds...")
                continue
            else:
                # 最後一次嘗試或非重試錯誤
                if is_quota_error:
                    return False, "❌ 圖片生成配額已用盡，請稍後再試或升級至付費方案。"
                elif "quota" in error_msg.lower():
                    return False, "❌ API 配額不足，請檢查您的 Google AI 使用額度。"
                else:
                    return False, f"❌ 生成圖片時發生錯誤，請稍後再試。"

    return False, "❌ 經過多次重試仍無法生成圖片，請稍後再試。"

async def send_chunked_reply(reply_token, user_id, text):
    """
    將長文本分段發送，確保每段不超過 LINE 的字元限制
    """
    MAX_CHAR_LENGTH = 2000  # LINE 的字元限制

    # 如果文本長度小於最大限制，直接發送
    if len(text) <= MAX_CHAR_LENGTH:
        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)]
            )
        )
        return

    chunks = []
    for i in range(0, len(text), MAX_CHAR_LENGTH):
        chunk = text[i:i + MAX_CHAR_LENGTH]
        # 為每個分段添加頁碼（除了第一頁）
        if i > 0:
            chunk = f"【續 {i//MAX_CHAR_LENGTH + 1}】\n{chunk}"
        chunks.append(chunk)

    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=chunks[0])]
        )
    )

    for chunk in chunks[1:]:
        await line_bot_api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=chunk)]
            )
        )

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get('X-Line-Signature')
    body = await request.body()

    try:
        events = parser.parse(body.decode('utf-8'), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
            await handle_text_message(event)

    return {"status": "ok"}

async def handle_text_message(event: MessageEvent):
    user_id = event.source.user_id
    msg = event.message.text.strip()
    logger.info(f"Received message: {msg}")

    try:
        # 檢查是否為儲存狀態指令
        storage_commands = ['!box', '!storage', '!stats', '!空間', '!容量']
        if any(msg.lower() == cmd for cmd in storage_commands):
            stats_res = await get_stats_async()
            if stats_res.get("result") == "success":
                data = stats_res.get("data", {})
                reply = (
                    f"📦 雲端儲存空間狀態 (888box)\n"
                    f"🔗 主端點: {stats_res.get('endpoint')}\n"
                    f"📊 總資產數: {data.get('total', 0)}\n"
                    f"🖼️ 圖片數: {data.get('image', 0)}\n"
                    f"🎥 影片數: {data.get('video', 0)}\n"
                    f"🎵 音訊數: {data.get('audio', 0)}\n"
                    f"📁 一般檔案: {data.get('file', 0)}"
                )
            else:
                reply = f"❌ 取得儲存空間狀態失敗: {stats_res.get('message', '未知錯誤')}"

            await line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)]
                )
            )
            return

        # 檢查是否為圖片生成指令
        image_commands = ['!img', '!畫圖', '!生成圖片', '!image', '!draw']
        if any(cmd in msg.lower() for cmd in image_commands):
            # 提取提示詞
            prompt = msg
            for cmd in image_commands:
                if cmd in msg.lower():
                    prompt = msg.lower().replace(cmd, '').strip()
                    break

            if not prompt:
                reply = "請提供圖片描述，例如：!img 可愛的貓咪"
            else:
                # 先發送"生成中"的訊息
                await line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"🎨 正在生成圖片：{prompt}\n請稍候...")]
                    )
                )

                # 生成圖片
                logger.info(f"Starting image generation for prompt: '{prompt}'")
                success, result = await generate_image_with_gemini(prompt)
                logger.info(f"Image generation result - success: {success}")

                if success:
                    logger.info("Image generation successful, sending image message")
                    # 發送圖片訊息
                    image_message = ImageMessage(
                        original_content_url=result,
                        preview_image_url=result
                    )

                    # 使用 push message 發送圖片
                    if event.source.type == 'group':
                        logger.info(f"Sending image to group: {event.source.group_id}")
                        await line_bot_api.push_message(
                            PushMessageRequest(
                                to=event.source.group_id,
                                messages=[image_message]
                            )
                        )
                    else:
                        logger.info(f"Sending image to user: {user_id}")
                        await line_bot_api.push_message(
                            PushMessageRequest(
                                to=user_id,
                                messages=[image_message]
                            )
                        )
                    return  # 直接返回，不發送文字消息
                else:
                    reply = f"❌ {result}"

            # 發送文字回應
            await line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)]
                )
            )
            return

        match = youtube_regex.search(msg)
        if match:
            youtube_url = match.group(0)
            logger.info(f"Extracted YouTube URL: {youtube_url}")
            transcription, video_title = await process_youtube_video(youtube_url)
            if transcription and (transcription.startswith("影片處理失敗") or transcription.startswith("音頻轉錄失敗") or transcription.startswith("音頻文件未生成")):
                reply = transcription
            else:
                system_messages = get_summary_prompt()
                summary = await chain_response(system_messages, transcription, llm_base_url, llm_api_key, llm_model, llm_max_tokens)
                title_display = f"【{video_title}】" if video_title else "【YouTube 影片摘要】"
                full_reply = f"{title_display}\n\n{summary}"
                await send_chunked_reply(event.reply_token, user_id, full_reply)
                return

        elif url_regex.search(msg):
            url = url_regex.search(msg).group()
            content, title = await scrape_text_from_url(url)
            if content == "無法提取此網頁的內容。":
                reply = content
            else:
                system_messages = get_summary_prompt()
                summary = await chain_response(system_messages, content, llm_base_url, llm_api_key, llm_model, llm_max_tokens)
                full_reply = f"【標題】: {title}\n\n{summary}"
                await send_chunked_reply(event.reply_token, user_id, full_reply)
                return

        else:
            reply = (
                "請提供有效的影音/網頁連結，我將為您生成智能摘要！\n\n"
                "🎨 圖片生成：使用 `!img [描述]` (例如：!img 可愛的柴犬)\n"
                "📦 空間狀態：使用 `!box` 查詢 888box 雲端儲存資產狀態"
            )

        # 發送文字回應
        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)]
            )
        )

    except Exception as e:
        logger.error(f"Error handling message: {e}")
        error_reply = f"發生錯誤: {str(e)}"
        try:
            await line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=error_reply)]
                )
            )
        except Exception as reply_error:
            logger.error(f"Failed to send error reply: {reply_error}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv('PORT', 5000))
    uvicorn.run(app, host='0.0.0.0', port=port)

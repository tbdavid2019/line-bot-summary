import os
import re
import requests
import json
import uuid
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError  # 加入這行
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from bs4 import BeautifulSoup
import yt_dlp
import trafilatura

# 初始化 Flask 應用
app = Flask(__name__)

# LINE 配置
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# API 配置
llm_base_url_raw = os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1')
# 自動補全 /chat/completions 路徑
if llm_base_url_raw.endswith('/'):
    llm_base_url_raw = llm_base_url_raw.rstrip('/')
if not llm_base_url_raw.endswith('/chat/completions'):
    llm_base_url = llm_base_url_raw + '/chat/completions'
else:
    llm_base_url = llm_base_url_raw

llm_api_key = os.getenv('LLM_API_KEY')
llm_model = os.getenv('LLM_MODEL', 'gemini-2.0-flash')
llm_max_tokens = int(os.getenv('MAX_TOKEN_LIMIT', '900000'))
whisper_base_url = os.getenv('WHISPER_BASE_URL', 'https://api.openai.com/v1/audio/transcriptions')
whisper_api_key = os.getenv('WHISPER_API_KEY')

# 用戶對話狀態管理（續問功能）
user_sessions = {}  # {user_id: {"content": str, "title": str, "remaining": int}}
MAX_FOLLOWUP_QUESTIONS = 5

# 正則表達式
url_regex = re.compile(r'https?://\S+')

# 顯示 Loading 動畫
def show_loading_animation(chat_id):
    """顯示 LINE 的 loading indicator"""
    try:
        headers = {
            "Authorization": f"Bearer {os.getenv('CHANNEL_ACCESS_TOKEN')}",
            "Content-Type": "application/json"
        }
        data = {
            "chatId": chat_id,
            "loadingSeconds": 60  # 最長60秒
        }
        response = requests.post(
            "https://api.line.me/v2/bot/chat/loading/start",
            headers=headers,
            json=data,
            timeout=5
        )
        if response.status_code == 202:
            print(f"Loading animation started for chat {chat_id}")
        else:
            print(f"Failed to start loading animation: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Error showing loading animation: {e}")

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
def chain_response(system_messages, text, base_url, api_key, model, max_tokens):
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
def scrape_text_from_url(url):
    try:
        print(f"Scraping URL: {url}")
        downloaded = trafilatura.fetch_url(url)
        if downloaded is None:
            return "無法提取此網頁的內容。", None
        
        content = trafilatura.extract(downloaded, include_formatting=True)
        soup = BeautifulSoup(downloaded, 'html.parser')
        title = soup.title.string if soup.title else "無法獲取標題"
        return content.strip(), title
    except Exception as e:
        print(f"抓取失敗: {e}")
        return "抓取過程中發生錯誤。", None

# 檢測 URL 是否被 yt-dlp 支援的影片網站
def is_supported_by_ytdlp(url):
    """
    檢測 URL 是否被 yt-dlp 支援的影片網站
    使用雙重檢測：URL 模式 + yt-dlp 檢測，避免將一般網站誤判為影片網站
    """
    # 第一層：URL 模式檢測已知的影片網站
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
    
    # 如果 URL 不匹配任何已知的影片網站模式，直接返回 False
    url_lower = url.lower()
    if not any(re.search(pattern, url_lower) for pattern in video_site_patterns):
        print(f"URL {url} doesn't match known video site patterns")
        return False
    
    # 第二層：使用 yt-dlp 進行詳細檢測
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'cookiesfile': 'cookies.txt'
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 嘗試提取資訊而不下載
            info = ydl.extract_info(url, download=False)
            if info:
                # 檢查是否包含影片相關的欄位
                video_indicators = [
                    'formats',           # 影片格式列表
                    'duration',          # 影片長度
                    'view_count',        # 觀看次數
                    'like_count',        # 按讚數
                    'upload_date',       # 上傳日期
                    'uploader',          # 上傳者
                ]
                
                # 如果有 formats 欄位且不為空，很可能是影片
                if 'formats' in info and info['formats']:
                    return True
                
                # 如果有 duration 且大於 0，很可能是影片
                if 'duration' in info and info.get('duration', 0) > 0:
                    return True
                
                # 檢查是否有其他影片相關欄位
                if any(key in info for key in video_indicators):
                    return True
                
                return False
    except Exception as e:
        print(f"URL {url} not supported by yt-dlp: {e}")
        return False
    
    return False

# 使用 yt-dlp 提取字幕或音訊
def process_video_url(video_url):
    """
    通用的影音網站處理函數，支援所有 yt-dlp 支援的網站
    """
    try:
        print(f"Starting to process video URL: {video_url}")
        print(f"URL type: {type(video_url)}")
        
        # 嘗試下載字幕
        ydl_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'skip_download': True,
            'subtitleslangs': ['zh-Hant', 'zh-TW', 'zh-Hans', 'zh', 'en'],
            'outtmpl': '/tmp/%(id)s.%(ext)s',
            'cookiesfile': 'cookies.txt'  # 加入 cookies 支援
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            video_id = info['id']
            video_title = info.get('title', '無法獲取標題')
            print(f"Video ID: {video_id}")
            print(f"Video Title: {video_title}")
            
            for lang in ['zh-Hant', 'zh-TW', 'zh-Hans', 'zh', 'en']:
                subtitle_path = f"/tmp/{video_id}.{lang}.vtt"
                print(f"Checking for subtitles at {subtitle_path}")
                if os.path.exists(subtitle_path):
                    print(f"Found subtitles: {subtitle_path}")
                    with open(subtitle_path, 'r', encoding='utf-8') as file:
                        subtitle_content = file.read()
                    # 清理字幕文件
                    os.remove(subtitle_path)
                    return subtitle_content, video_title
                    
        # 如果無字幕,下載音頻並進行轉錄
        print("No subtitles found, falling back to audio transcription.")
        transcription = audio_transcription(video_url)
        return transcription, video_title
    except Exception as e:
        error_message = f"影片處理失敗: {str(e)}"
        print(error_message)
        return error_message, None

def audio_transcription(video_url):
    """下載完整音頻，檢查大小，如果超過25MB則分段發送給Whisper API"""
    audio_file = None
    try:
        print(f"Starting audio transcription for: {video_url}")
        audio_file_path = f'/tmp/{str(uuid.uuid4())}'
        ydl_opts = {
            'format': 'bestaudio/best',  # 使用最佳音頻質量
            'outtmpl': f'{audio_file_path}.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'ffmpeg_location': '/usr/bin/ffmpeg',
            'ffprobe_location': '/usr/bin/ffprobe',
            'cookiesfile': 'cookies.txt'  # 加入 cookies 支援
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            audio_file = f"{audio_file_path}.mp3"
            
            if not os.path.exists(audio_file):
                error_message = "音頻文件未生成,請檢查下載過程。"
                print(error_message)
                return error_message
                
            file_size = os.path.getsize(audio_file)
            print(f"Audio file downloaded: {audio_file} ({file_size} bytes)")
            
            # 檢查文件大小是否超過 Whisper API 限制 (25MB)
            if file_size > 25 * 1024 * 1024:  # 25MB
                print(f"File size {file_size} bytes exceeds 25MB limit, splitting for Whisper API...")
                return split_and_transcribe(audio_file)
            else:
                # 文件小於25MB，直接發送給 Whisper API
                print("File size within limit, sending directly to Whisper API...")
                return send_to_whisper(audio_file)
            
    except Exception as e:
        error_message = f"音頻轉錄失敗: {str(e)}"
        print(error_message)
        return error_message
    finally:
        # 清理原始音頻文件
        if audio_file and os.path.exists(audio_file):
            try:
                os.remove(audio_file)
                print(f"Cleaned up original audio file: {audio_file}")
            except Exception as cleanup_error:
                print(f"Failed to cleanup audio file: {cleanup_error}")

def send_to_whisper(audio_file):
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
            print("Whisper transcription successful.")
            return transcript
    except Exception as e:
        return f"Whisper API 轉錄失敗: {str(e)}"

def split_and_transcribe(audio_file):
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
        
        print(f"Splitting audio for Whisper API: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            return f"音頻分段失敗: {result.stderr}"
        
        # 找到所有分段文件
        segment_files = glob.glob(f"{segment_prefix}_*.mp3")
        segment_files.sort()
        
        print(f"Created {len(segment_files)} segments for Whisper API")
        
        # 逐個發送分段到 Whisper API
        for i, segment_file in enumerate(segment_files):
            segment_size = os.path.getsize(segment_file)
            print(f"Sending segment {i+1}/{len(segment_files)} to Whisper API: {segment_file} ({segment_size} bytes)")
            
            # 確保分段文件不超過25MB
            if segment_size > 25 * 1024 * 1024:
                print(f"Warning: Segment {i+1} still too large ({segment_size} bytes), skipping...")
                transcripts.append(f"[分段 {i+1} 文件過大，跳過處理]")
                continue
            
            try:
                segment_transcript = send_to_whisper(segment_file)
                transcripts.append(segment_transcript)
                print(f"Segment {i+1} transcription successful.")
                
            except Exception as e:
                print(f"Segment {i+1} transcription failed: {e}")
                transcripts.append(f"[分段 {i+1} 轉錄失敗: {str(e)}]")
        
        # 合併所有轉錄結果
        full_transcript = " ".join(transcripts)  # 用空格連接，讓文字更自然
        print(f"Combined transcript from {len(transcripts)} segments")
        return full_transcript
        
    except Exception as e:
        return f"分段轉錄失敗: {str(e)}"
    finally:
        # 清理所有分段文件
        for segment_file in segment_files:
            if os.path.exists(segment_file):
                try:
                    os.remove(segment_file)
                    print(f"Cleaned up segment: {segment_file}")
                except Exception as cleanup_error:
                    print(f"Failed to cleanup segment {segment_file}: {cleanup_error}")

# LINE Webhook
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()
    try:
        print(f"Received message: {msg}")
        
        # 檢查是否為 URL
        if url_regex.search(msg):
            url = url_regex.search(msg).group()
            print(f"Detected URL: {url}")
            
            # 顯示 loading 動畫
            chat_id = event.source.user_id if hasattr(event.source, 'user_id') else event.source.group_id if hasattr(event.source, 'group_id') else event.source.room_id
            show_loading_animation(chat_id)
            
            # 檢查是否為 yt-dlp 支援的影音網站
            if is_supported_by_ytdlp(url):
                print(f"Processing as video URL: {url}")
                transcription, video_title = process_video_url(url)
                if transcription and (transcription.startswith("影片處理失敗") or transcription.startswith("音頻轉錄失敗") or transcription.startswith("音頻文件未生成")):
                    reply = transcription
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
                else:
                    system_messages = get_summary_prompt()
                    summary = chain_response(system_messages, transcription, llm_base_url, llm_api_key, llm_model, llm_max_tokens)
                    title_display = f"【{video_title}】" if video_title else "【影音摘要】"
                    full_reply = f"{title_display}\n\n{summary}\n\n💡 您可以繼續詢問這個影片的相關問題(最多{MAX_FOLLOWUP_QUESTIONS}次)"
                    send_chunked_reply(event.reply_token, user_id, full_reply)
                    
                    # 儲存用戶對話狀態
                    user_sessions[user_id] = {
                        "content": transcription,
                        "title": video_title if video_title else "影音內容",
                        "remaining": MAX_FOLLOWUP_QUESTIONS
                    }
            else:
                # 普通網頁處理
                print(f"Processing as regular webpage: {url}")
                content, title = scrape_text_from_url(url)
                if content == "無法提取此網頁的內容。":
                    reply = content
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
                else:
                    system_messages = get_summary_prompt()
                    summary = chain_response(system_messages, content, llm_base_url, llm_api_key, llm_model, llm_max_tokens)
                    full_reply = f"【標題】: {title}\n\n{summary}\n\n💡 您可以繼續詢問這個網頁的相關問題(最多{MAX_FOLLOWUP_QUESTIONS}次)"
                    send_chunked_reply(event.reply_token, user_id, full_reply)
                    
                    # 儲存用戶對話狀態
                    user_sessions[user_id] = {
                        "content": content,
                        "title": title if title else "網頁內容",
                        "remaining": MAX_FOLLOWUP_QUESTIONS
                    }
        else:
            # 檢查是否為續問
            if user_id in user_sessions and user_sessions[user_id]["remaining"] > 0:
                session = user_sessions[user_id]
                print(f"Processing followup question for user {user_id}, remaining: {session['remaining']}")
                
                # 使用原始內容回答續問
                system_messages = [
                    {
                        "role": "system",
                        "content": f"你是一個專業的內容分析助手。以下是【{session['title']}】的完整內容：\n\n{session['content']}\n\n請根據以上內容，用繁體中文回答使用者的問題。回答要準確、具體，並引用原文相關部分。"
                    }
                ]
                
                answer = chain_response(system_messages, msg, llm_base_url, llm_api_key, llm_model, llm_max_tokens)
                session["remaining"] -= 1
                
                remaining_text = f"\n\n📊 剩餘續問次數: {session['remaining']}"
                if session["remaining"] == 0:
                    remaining_text += "\n\n💬 續問次數已用完，請提供新的網址開始新的對話。"
                    del user_sessions[user_id]  # 清除會話
                
                full_reply = answer + remaining_text
                send_chunked_reply(event.reply_token, user_id, full_reply)
            else:
                reply = "請提供有效的影音網站連結或普通網頁網址，我將為您生成摘要！\n\n支援的影音網站包括：YouTube、Vimeo、Bilibili、Dailymotion、TikTok、Twitch、Facebook、Instagram、Twitter 等 1000+ 網站"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    except Exception as e:
        reply = f"發生錯誤: {str(e)}"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

def send_chunked_reply(reply_token, user_id, text):
    """
    將長文本分段發送，確保每段不超過 LINE 的字元限制
    """
    MAX_CHAR_LENGTH = 2000  # LINE 的字元限制
    
    # 如果文本長度小於最大限制，直接發送
    if len(text) <= MAX_CHAR_LENGTH:
        line_bot_api.reply_message(reply_token, TextSendMessage(text=text))
        return
    
    chunks = []
    for i in range(0, len(text), MAX_CHAR_LENGTH):
        chunk = text[i:i + MAX_CHAR_LENGTH]
        # 為每個分段添加頁碼（除了第一頁）
        if i > 0:
            chunk = f"【續 {i//MAX_CHAR_LENGTH + 1}】\n{chunk}"
        chunks.append(chunk)
    
    line_bot_api.reply_message(reply_token, TextSendMessage(text=chunks[0]))
    
    for chunk in chunks[1:]:
        line_bot_api.push_message(user_id, TextSendMessage(text=chunk))

if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
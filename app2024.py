import os, re, openai, requests
import trafilatura
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from bs4 import BeautifulSoup  # 使用 BeautifulSoup 來提取標題

# LINE keys
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
# OpenAI api key
openai_api_key = os.getenv('OPENAI_API_KEY')
# max token limit for buffer
max_token_limit = int(os.getenv('MAX_TOKEN_LIMIT'))
# temperature
temperature = float(os.getenv('TEMPERATURE'))

# Application
app = Flask(__name__)

# Define the pattern
url_regex = re.compile(r'https?://\S+')

def chain_response(system_messages, text, openai_api_key, model="gpt-4o-mini"):
    """
    調用 OpenAI API，根據 system_messages 和 text 生成摘要。
    """
    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "Content-Type": "application/json",
    }

    data = {
        "model": model,
        "messages": system_messages + [{"role": "user", "content": text}],
        "max_tokens": 1000,
        "temperature": 0.7,
    }

    try:
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data)
        response.raise_for_status()  # 檢查 API 回應是否有錯誤
        reply = response.json()["choices"][0]["message"]["content"].strip()
        return reply
    except requests.exceptions.RequestException as e:
        return f"API 請求發生錯誤: {str(e)}"

def scrape_text_from_url(url):
    """ 使用 trafilatura 從 URL 抓取網站內容，並返回標題和內容 """
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded is None:
            return "無法提取此網頁的內容。", None
        
        # 提取頁面內容
        content = trafilatura.extract(downloaded, include_formatting=True)
        
        # 使用 BeautifulSoup 提取標題
        soup = BeautifulSoup(downloaded, 'html.parser')
        title = soup.title.string if soup.title else "無法獲取標題"
        
        return content.strip(), title
    except Exception as e:
        print(f"抓取失敗: {e}")
        return "抓取過程中發生錯誤。", None


@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']
    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# handle text message
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    # user ID
    user_id = event.source.user_id
    # message log 
    print(f'{user_id}: has a message')
    # message
    msg = event.message.text.strip()

    try:
        # 如果輸入的是 URL
        if url_regex.search(msg):
            # 找到第一個 URL
            url = url_regex.search(msg).group()

            # 使用 trafilatura 抓取網頁內容及標題
            text, title = scrape_text_from_url(url)
            
            if text == "無法提取此網頁的內容。":
                reply = text
            else:
                # 推送一個信息告知用戶
                line_bot_api.push_message(user_id, TextSendMessage(text="收到！正在閱讀報導中..."))

                # 使用 GPT 模型生成摘要，這裡傳遞模型名稱
                system_messages = [
                    {"role": "system", "content": "將以下原文總結為五個部分：1.總結 (Overall Summary)：約100字~300字概括。2.觀點 (Viewpoints):內容中的看法與你的看法。3.摘要 (Abstract)： 創建6到10個帶有適當表情符號的重點摘要。4.關鍵字 (Key Words)：列出內容中重點關鍵字。 5.容易懂(Easy Know)：一個讓十二歲青少年可以看得懂的段落。確保生成的文字都是繁體中文為主"}
                ]

                # 呼叫 GPT 生成摘要，指定使用的模型
                summary = chain_response(system_messages, text, openai_api_key, model="gpt-4o-mini")
                
                # 將原始URL附加到摘要中，並附加標題
                summary_with_original = f"【標題】: {title}\n\n{summary}\n\n[Original] {url}"

                # 將最終結果回覆給用戶
                reply = summary_with_original
        
        # 如果輸入的不是 URL
        else:
            # 給用戶回應引導他們輸入 URL
            reply = "我是 Oli 江家機器人二號機 \n專長是 < 濃縮重點 >\n請貼上 \n- 網址URL"

    except Exception as e:
        # 處理可能的錯誤
        reply = f"發生錯誤: {str(e)}"

    # 將回應發送給用戶
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# make url discoverable
@app.route("/", methods=['GET'])
def home():
    return 'Hello World'

# main function
if __name__ == "__main__":
    # port
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
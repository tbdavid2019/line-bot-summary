import os
import re
import json
import logging
import asyncio
from typing import Dict, Any, List, Tuple, Optional, Callable

import httpx

from src.web_browser import search_web_async, read_url_markdown_async
from src.box_storage import get_stats_async, upload_text_async, upload_url_async
from src.security import sanitize_filename, sanitize_error_message, is_safe_url

logger = logging.getLogger("agent-tools")

# ----------------------------------------------------------------------
# 1. 工具定義 Schema (OpenAI / Gemini Function Calling 相容規範)
# ----------------------------------------------------------------------
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "即時全網搜尋 (2MD SERP Engine)。當使用者詢問即時新聞、最新事實、股價、人物動態、歷史或需要線上檢索時調用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜尋關鍵字，例如「SpaceX 最新星艦進度」、「台積電 今日股價新聞」"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_read_markdown",
            "description": "精準讀取任意網頁、新聞或線上文件的完整純淨 Markdown 內文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "欲閱讀的完整網址 URL (http/https)"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "video_transcribe",
            "description": "下載並轉錄 YouTube、Bilibili、TikTok 等 1000+ 影音平台的完整字幕與多模態音訊逐字稿。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "欲分析轉錄的影音網址 URL"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "調用 Google Gemini 生成高品質圖片。當使用者明確要求「畫圖」、「生成圖片」、「製作插圖」或需要視覺化呈現時調用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "圖片的詳細提示詞描述（支援繁體中文或英文，描述越具體畫面品質越高）"
                    }
                },
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "wiki_publish",
            "description": "將整理好的摘要、文章、研究筆記或多媒體報告發布至 David888 Wiki 知識庫 (wiki.david888.com)，生成永久公開閱讀的 Markdown 與 2D 簡報連結。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "文章標題（例如：SpaceX 星艦發射深度分析、台積電法說會重點摘要）"
                    },
                    "markdown_content": {
                        "type": "string",
                        "description": "欲發布的完整 Markdown 格式內容（支援 Mermaid 圖表、表格、列表等）"
                    },
                    "path": {
                        "type": "string",
                        "description": "自訂網址路徑別名（英文/數字/連字號，如 starship-2026 或 tsmc-q3-summary，留空則自動生成）"
                    },
                    "theme": {
                        "type": "string",
                        "description": "Wiki 主題樣式，可選：claude-canvas (推薦), notion-clean, retro, tokyo-night, bauhaus, terminal"
                    }
                },
                "required": ["title", "markdown_content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_file_type",
            "description": "使用 Google Magika 深度學習模型精確辨識網址檔案、多媒體或文件的真實 MIME Type 與格式類型。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "欲辨識檢驗的檔案或資源 URL"
                    }
                },
                "required": ["url"]
            }
        }
    }
]

# ----------------------------------------------------------------------
# 2. 執行器調度核心 (Actuators Dispatcher)
# ----------------------------------------------------------------------
class AgentActuators:
    """執行器集合，封裝各項底層 API 呼叫"""

    def __init__(
        self,
        generate_image_fn: Optional[Callable] = None,
        process_video_fn: Optional[Callable] = None,
        scrape_web_fn: Optional[Callable] = None,
    ):
        self.generate_image_fn = generate_image_fn
        self.process_video_fn = process_video_fn
        self.scrape_web_fn = scrape_web_fn

    async def execute_tool_async(self, name: str, arguments: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        非同步執行指定工具並回傳 (文字結果, 附加產物 metadata)
        """
        logger.info(f"Executing Actuator [{name}] with args: {arguments}")
        extra_meta: Dict[str, Any] = {}

        try:
            if name == "web_search":
                query = arguments.get("query", "").strip()
                if not query:
                    return "請提供有效搜尋關鍵字", extra_meta
                ok, res = await search_web_async(query)
                return (res if ok else f"搜尋失敗: {res}"), extra_meta

            elif name == "web_read_markdown":
                url = arguments.get("url", "").strip()
                if not url:
                    return "請提供有效網址", extra_meta
                if self.scrape_web_fn:
                    content, title = await self.scrape_web_fn(url)
                    return f"【標題】: {title}\n\n{content[:8000]}", extra_meta
                ok, content, title = await read_url_markdown_async(url)
                return (f"【標題】: {title}\n\n{content[:8000]}" if ok else f"閱讀失敗: {content}"), extra_meta

            elif name == "video_transcribe":
                url = arguments.get("url", "").strip()
                if not url:
                    return "請提供有效影音網址", extra_meta
                if self.process_video_fn:
                    transcription, title = await self.process_video_fn(url)
                    extra_meta["video_title"] = title
                    return f"【影音標題】: {title}\n\n【逐字稿內容】:\n{transcription[:8000]}", extra_meta
                return "影音轉錄模組未就緒", extra_meta

            elif name == "generate_image":
                prompt = arguments.get("prompt", "").strip()
                if not prompt:
                    return "請提供圖片生成描述", extra_meta
                if self.generate_image_fn:
                    ok, img_res = await self.generate_image_fn(prompt)
                    if ok:
                        extra_meta["generated_image_url"] = img_res
                        return f"圖片生成成功，圖片 URL: {img_res}", extra_meta
                    return f"圖片生成失敗: {img_res}", extra_meta
                return "圖片生成模組未就緒", extra_meta

            elif name == "box_storage_action":
                action = arguments.get("action", "stats")
                if action == "stats":
                    stats = await get_stats_async()
                    return json.dumps(stats, ensure_ascii=False), extra_meta
                elif action == "upload_text":
                    text = arguments.get("text", "")
                    raw_fn = arguments.get("filename", "note.txt")
                    filename = sanitize_filename(raw_fn, default_prefix="note", default_ext=".txt")
                    res = await upload_text_async(text, filename)
                    return json.dumps(res, ensure_ascii=False), extra_meta
                return f"不支援的操作: {action}", extra_meta

            elif name == "wiki_publish":
                title = arguments.get("title", "未命名文章").strip()
                md_content = arguments.get("markdown_content", "").strip()
                import uuid
                raw_slug = arguments.get("path", "").strip()
                # 清理 slug 防止路徑注入
                cleaned_slug = re.sub(r'[^a-zA-Z0-9_\-]', '', raw_slug)
                slug = cleaned_slug or f"note-{uuid.uuid4().hex[:8]}"
                theme = arguments.get("theme", "claude-canvas")
                if theme not in ["claude-canvas", "notion-clean", "retro", "tokyo-night", "bauhaus", "terminal", "professional"]:
                    theme = "claude-canvas"
                
                # 遵循 Wiki 規範：第一行必須是 # Title
                if not md_content.startswith("#"):
                    full_md = f"# {title}\n\n{md_content}"
                else:
                    full_md = md_content
                    
                wiki_api_url = f"https://wiki.david888.com/api/{slug}?public=true&theme={theme}"
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        wiki_api_url,
                        headers={"Content-Type": "text/markdown; charset=UTF-8"},
                        content=full_md.encode("utf-8")
                    )
                    res_data = resp.json()
                    share_url = res_data.get("data", {}).get("shareUrl", "")
                    if share_url:
                        return f"✅ 成功發布至 David888 Wiki！\n📖 公開閱讀連結: {share_url}\n📽️ 2D 簡報模式: {share_url}/present", extra_meta
                    else:
                        return f"❌ 發布失敗: {res_data.get('msg', '未知錯誤')}", extra_meta

            elif name == "inspect_file_type":
                url = arguments.get("url", "").strip()
                if not url or not is_safe_url(url):
                    return "❌ 提供的 URL 無效或存在安全風險。", extra_meta
                try:
                    from src.file_detector import detect_content_type_bytes
                    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                        # 優先抓取前 16KB 二進位以節省網路流量
                        headers = {"Range": "bytes=0-16383"}
                        resp = await client.get(url, headers=headers)
                        if resp.status_code in [200, 206]:
                            sample = resp.content
                        else:
                            full_resp = await client.get(url)
                            sample = full_resp.content[:16384]

                        detection = detect_content_type_bytes(sample, filename_hint=os.path.basename(url.split("?")[0]))
                        extra_meta["detection"] = {
                            "mime_type": detection.mime_type,
                            "label": detection.label,
                            "group": detection.group,
                            "description": detection.description,
                            "score": detection.score,
                            "is_text": detection.is_text
                        }
                        report = (
                            f"🔍 **Google Magika 檔案識別報告**\n"
                            f"- 檔案特徵描述：{detection.description}\n"
                            f"- MIME 類型：`{detection.mime_type}`\n"
                            f"- 格式標籤與分組：{detection.label} ({detection.group})\n"
                            f"- 推薦副檔名：`{detection.primary_extension}`\n"
                            f"- AI 模型信心度：{detection.score:.1%}\n"
                            f"- 類型性質：{'純文字 / 原始碼' if detection.is_text else '二進位資料'}"
                        )
                        return report, extra_meta
                except Exception as e:
                    logger.warning(f"inspect_file_type failed for {url}: {e}")
                    return f"❌ 檔案檢測失敗: {sanitize_error_message(e)}", extra_meta

            else:
                return f"未知工具: {name}", extra_meta

        except Exception as e:
            logger.error(f"Error executing actuator {name}: {e}", exc_info=True)
            return f"執行工具 {name} 時發生異常: {sanitize_error_message(e)}", extra_meta


# ----------------------------------------------------------------------
# 3. ReAct 自主代理迴圈 (Agentic ReAct Loop)
# ----------------------------------------------------------------------
async def run_agentic_loop_async(
    messages: List[Dict[str, Any]],
    actuators: AgentActuators,
    llm_api_key: str,
    llm_base_url: str,
    llm_model: str = "gemini-3.6-flash",
    max_steps: int = 4
) -> Tuple[str, List[str]]:
    """
    執行 LLM 自主意圖解構與 Tool Calling 迴圈。
    回傳：(最終文字回應, 生成的圖片 URL 列表)
    """
    headers = {
        "Authorization": f"Bearer {llm_api_key}",
        "Content-Type": "application/json",
    }
    
    endpoint = llm_base_url
    if not endpoint.endswith("/chat/completions"):
        endpoint = endpoint.rstrip("/") + "/chat/completions"

    user_query = ""
    for m in messages:
        if m.get("role") == "user":
            user_query = m.get("content", "")

    current_messages = list(messages)
    generated_images: List[str] = []
    gathered_tool_results: List[str] = []

    for step in range(max_steps):
        payload = {
            "model": llm_model,
            "messages": current_messages,
            "tools": AGENT_TOOLS,
            "tool_choice": "auto",
            "temperature": 0.4,
        }

        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(endpoint, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error(f"Agent LLM API request failed: {e}")
            if gathered_tool_results:
                break
            return f"⚠️ LLM 代理思考時發生錯誤: {str(e)}", generated_images

        choice = data["choices"][0]
        msg = choice.get("message", {})
        tool_calls = msg.get("tool_calls")
        content = msg.get("content")

        # 若模型已產出文字且沒有新的工具呼叫
        if not tool_calls:
            return (content.strip() if content else "（已完成處理）"), generated_images

        # 記錄 assistant 訊息
        current_messages.append(msg)

        # 執行所有被觸發的工具
        executed_any = False
        for tc in tool_calls:
            call_id = tc.get("id", "call_default")
            fn = tc.get("function", {})
            fn_name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:
                args = {}

            tool_result, meta = await actuators.execute_tool_async(fn_name, args)
            executed_any = True
            gathered_tool_results.append(f"【工具 {fn_name} 執行結果】:\n{tool_result}")

            if "generated_image_url" in meta:
                img_url = meta["generated_image_url"]
                if img_url not in generated_images:
                    generated_images.append(img_url)

            current_messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": tool_result
            })

        if not executed_any:
            break

        # 針對搜尋/閱讀/轉錄類工具，收集完即刻進行總結，避免無限工具調用
        if any(tc.get("function", {}).get("name") in ["web_search", "web_read_markdown", "video_transcribe"] for tc in tool_calls):
            break

    # 綜合工具執行結果進行最終智慧總結
    if gathered_tool_results:
        synthesis_messages = [
            {
                "role": "system",
                "content": (
                    "你是一個具備自主意圖解構與即時工具執行力的頂級繁體中文 AI 助理。\n"
                    "請根據以下透過執行器（Actuators）即時檢索或執行的真實現場資料，針對使用者的原始問題與需求給出客觀、準確、專業、條理分明的完整解答。\n"
                    "【鐵律】\n"
                    "1. 嚴格遵守零幻覺與即時檢索鐵律，所有數據與最新動態必須根據現場檢索資料回答。\n"
                    "2. 若有來源網址或具體數據，請在回答中清晰標註與引用。"
                )
            },
            {
                "role": "user",
                "content": f"使用者需求：【{user_query}】\n\n" + "\n\n".join(gathered_tool_results)
            }
        ]
        try:
            synth_payload = {
                "model": llm_model,
                "messages": synthesis_messages,
                "temperature": 0.4,
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                synth_resp = await client.post(endpoint, headers=headers, json=synth_payload)
                synth_resp.raise_for_status()
                synth_data = synth_resp.json()
                return synth_data["choices"][0]["message"]["content"].strip(), generated_images
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return "\n\n".join(gathered_tool_results), generated_images

    return "（已完成所有工具調度與操作）", generated_images

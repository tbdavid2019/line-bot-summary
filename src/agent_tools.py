# -*- coding: utf-8 -*-
"""
Agentic Tool Calling & Actuators 執行器工具箱模組
賦予 LLM 意圖解構與自主調度執行能力。
"""
import os
import json
import logging
import asyncio
from typing import Dict, Any, List, Tuple, Optional, Callable

import httpx

from src.web_browser import search_web_async, read_url_markdown_async
from src.box_storage import get_stats_async, upload_text_async, upload_url_async

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
            "name": "box_storage_action",
            "description": "888box 雲端多端點儲存操作。支援查看儲存空間統計 (`stats`)、或將重要文字筆記/摘要上傳存檔 (`upload_text`)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["stats", "upload_text"],
                        "description": "操作類型：'stats' 查詢空間狀態；'upload_text' 上傳文字檔案"
                    },
                    "text": {
                        "type": "string",
                        "description": "當 action 為 'upload_text' 時必填，欲儲存的文字內容"
                    },
                    "filename": {
                        "type": "string",
                        "description": "當 action 為 'upload_text' 時的檔名（例如 summary.md 或 note.txt）"
                    }
                },
                "required": ["action"]
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
                    filename = arguments.get("filename", "note.txt")
                    res = await upload_text_async(text, filename)
                    return json.dumps(res, ensure_ascii=False), extra_meta
                return f"不支援的操作: {action}", extra_meta

            else:
                return f"未知工具: {name}", extra_meta

        except Exception as e:
            logger.error(f"Error executing actuator {name}: {e}", exc_info=True)
            return f"執行工具 {name} 時發生異常: {str(e)}", extra_meta


# ----------------------------------------------------------------------
# 3. ReAct 自主代理迴圈 (Agentic ReAct Loop)
# ----------------------------------------------------------------------
async def run_agentic_loop_async(
    messages: List[Dict[str, Any]],
    actuators: AgentActuators,
    llm_api_key: str,
    llm_base_url: str,
    llm_model: str = "gemini-3.6-flash",
    max_steps: int = 5
) -> Tuple[str, List[str]]:
    """
    執行 LLM 自主意圖解構與 Tool Calling 迴圈。
    回傳：(最終文字回應, 生成的圖片 URL 列表)
    """
    headers = {
        "Authorization": f"Bearer {llm_api_key}",
        "Content-Type": "application/json",
    }
    
    # 確保 API 端點完整
    endpoint = llm_base_url
    if not endpoint.endswith("/chat/completions"):
        endpoint = endpoint.rstrip("/") + "/chat/completions"

    current_messages = list(messages)
    generated_images: List[str] = []

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
            return f"⚠️ LLM 代理思考時發生錯誤: {str(e)}", generated_images

        choice = data["choices"][0]
        msg = choice.get("message", {})
        tool_calls = msg.get("tool_calls")
        content = msg.get("content")

        # 若模型決定直接回覆（無更多工具呼叫）
        if not tool_calls:
            return (content.strip() if content else "（已完成處理）"), generated_images

        # 將 assistant 的 tool_calls 意圖訊息加入對話歷史
        current_messages.append(msg)

        # 執行所有被觸發的工具
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

            if "generated_image_url" in meta:
                img_url = meta["generated_image_url"]
                if img_url not in generated_images:
                    generated_images.append(img_url)

            # 將工具執行結果加入對話歷史中
            current_messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": tool_result
            })

    # 若達到最大步數，進行最後一次總結收尾
    final_payload = {
        "model": llm_model,
        "messages": current_messages,
        "temperature": 0.4,
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            final_resp = await client.post(endpoint, headers=headers, json=final_payload)
            final_data = final_resp.json()
            return final_data["choices"][0]["message"]["content"].strip(), generated_images
    except Exception as e:
        return "⚠️ 已完成工具調度與資料收集。", generated_images

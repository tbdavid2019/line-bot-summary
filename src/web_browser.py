#!/usr/bin/env python3
"""
Web Browser & Live SERP Search Module for LLM.
Powered by 2MD (888-url2md) Fast Reader & SERP Search Engine.
Endpoints:
  - Primary:   https://2md.aiurl.tw
  - Backup 1:  https://2md.glsoft.ai
  - Backup 2:  https://create360.ai
"""

import os
import logging
import asyncio
import urllib.parse
from typing import Optional, Tuple, List, Dict, Any
import httpx

logger = logging.getLogger("web-browser")

DEFAULT_ENDPOINTS = [
    "https://2md.aiurl.tw",
    "https://2md.glsoft.ai",
    "https://create360.ai"
]

class WebBrowserClient:
    def __init__(self, endpoints: Optional[List[str]] = None, timeout: float = 15.0):
        env_endpoints = os.getenv("TWOMD_ENDPOINTS")
        if env_endpoints:
            self.endpoints = [ep.strip().rstrip('/') for ep in env_endpoints.split(',') if ep.strip()]
        elif endpoints:
            self.endpoints = [ep.rstrip('/') for ep in endpoints]
        else:
            self.endpoints = DEFAULT_ENDPOINTS
        self.timeout = timeout

    async def search_web_async(self, query: str) -> Tuple[bool, str]:
        """
        執行即時網路搜尋 (SERP Search)。
        依序嘗試端點，回傳結構化 Markdown 搜尋摘要與來源連結。
        """
        clean_query = query.strip()
        if not clean_query:
            return False, "搜尋字串不可為空。"

        encoded_query = urllib.parse.quote(clean_query)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/plain"
        }

        for endpoint in self.endpoints:
            search_url = f"{endpoint}/s/{encoded_query}"
            try:
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                    resp = await client.get(search_url, headers=headers)
                    if resp.status_code == 200:
                        text = resp.text.strip()
                        if text and not text.startswith("No search results available"):
                            logger.info(f"Search successful via {endpoint} (len={len(text)})")
                            return True, text
                    logger.debug(f"Endpoint {endpoint} search returned status {resp.status_code}")
            except Exception as e:
                logger.warning(f"Failed search via {endpoint}: {e}")

        return False, f"即時搜尋失敗：所有搜尋端點皆暫時無回應 (Query: {clean_query})"

    async def read_url_markdown_async(self, url: str) -> Tuple[bool, str, Optional[str]]:
        """
        將任意網址轉為結構化 Markdown 內容。
        依序透過 2MD 服務提取，若失敗則降級為本地 trafilatura + BeautifulSoup 解析。
        """
        clean_url = url.strip()
        if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
            clean_url = "https://" + clean_url

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/plain"
        }

        # 1. 嘗試 2MD 雲端高效 Markdown 轉換
        for endpoint in self.endpoints:
            fetch_url = f"{endpoint}/{clean_url}"
            try:
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                    resp = await client.get(fetch_url, headers=headers)
                    if resp.status_code == 200:
                        text = resp.text.strip()
                        if len(text) > 80 and not text.startswith("Error"):
                            title = None
                            for line in text.splitlines()[:10]:
                                if line.startswith("Title:"):
                                    title = line.replace("Title:", "").strip()
                                    break
                                elif line.startswith("# "):
                                    title = line.replace("# ", "").strip()
                                    break
                            logger.info(f"URL read successful via {endpoint} (title={title}, len={len(text)})")
                            return True, text, title
            except Exception as e:
                logger.debug(f"2MD read failed on {endpoint}: {e}")

        # 2. 本地 trafilatura 備援
        try:
            import trafilatura
            from bs4 import BeautifulSoup
            downloaded = await asyncio.to_thread(trafilatura.fetch_url, clean_url)
            if downloaded:
                content = await asyncio.to_thread(trafilatura.extract, downloaded, include_formatting=True)
                soup = BeautifulSoup(downloaded, 'html.parser')
                title = soup.title.string.strip() if soup.title and soup.title.string else None
                if content and len(content.strip()) > 30:
                    return True, content.strip(), title
        except Exception as e:
            logger.warning(f"Local fallback parser failed: {e}")

        return False, "無法提取此網頁的內容，請確認網址是否公開且可正常存取。", None

# 單例全域客戶端
default_browser = WebBrowserClient()

async def search_web_async(query: str) -> Tuple[bool, str]:
    return await default_browser.search_web_async(query)

async def read_url_markdown_async(url: str) -> Tuple[bool, str, Optional[str]]:
    return await default_browser.read_url_markdown_async(url)

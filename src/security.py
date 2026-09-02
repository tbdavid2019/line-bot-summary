# -*- coding: utf-8 -*-
"""
Security & Defense Hardening Module
Provides SSRF protection, filename sanitization, bounded session caching with TTL,
and safe error sanitization.
"""

import os
import re
import socket
import ipaddress
import urllib.parse
import logging
import time
from typing import Optional, Dict, Any
from collections import OrderedDict
import asyncio

logger = logging.getLogger("security")

# ----------------------------------------------------------------------
# 1. SSRF (Server-Side Request Forgery) 防護與 URL 驗證
# ----------------------------------------------------------------------
PRIVATE_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
    ipaddress.ip_network("10.0.0.0/8"),         # Private RFC 1918
    ipaddress.ip_network("100.64.0.0/10"),      # Shared Address Space RFC 6598
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local (AWS/GCP/Cloud metadata)
    ipaddress.ip_network("172.16.0.0/12"),      # Private RFC 1918
    ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1
    ipaddress.ip_network("192.88.99.0/24"),     # 6to4 Relay Anycast
    ipaddress.ip_network("192.168.0.0/16"),     # Private RFC 1918
    ipaddress.ip_network("198.18.0.0/15"),      # Network Interconnect Device Benchmark Testing
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved for Future Use
    ipaddress.ip_network("255.255.255.255/32"), # Broadcast
    # IPv6
    ipaddress.ip_network("::/128"),             # Unspecified
    ipaddress.ip_network("::1/128"),            # Loopback
    ipaddress.ip_network("fc00::/7"),           # Unique Local Address (ULA)
    ipaddress.ip_network("fe80::/10"),          # Link-local
    ipaddress.ip_network("ff00::/8"),           # Multicast
]

def is_safe_url(url: str, allow_private: bool = False) -> bool:
    """
    驗證 URL 是否安全，防止 SSRF 攻擊（阻擋存取 127.0.0.1, 169.254.169.254 等內部網路或雲端 Metadata）。
    """
    if not url or not isinstance(url, str):
        return False

    url = url.strip()
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False

    if parsed.scheme.lower() not in ("http", "https"):
        logger.warning(f"SSRF blocked: Disallowed scheme '{parsed.scheme}' in URL: {url}")
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # 若為 localhost 或常見內部主機名稱直接阻擋
    lower_host = hostname.lower()
    if lower_host in ("localhost", "localhost.localdomain", "broadcasthost", "ip6-localhost", "ip6-loopback"):
        logger.warning(f"SSRF blocked: Localhost host in URL: {url}")
        return False

    if allow_private:
        return True

    # 解析 DNS 取得所有 IP 並檢查是否落在私有/保留網段
    try:
        addr_info = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
        for entry in addr_info:
            ip_str = entry[4][0]
            ip_obj = ipaddress.ip_address(ip_str)
            for net in PRIVATE_NETWORKS:
                if ip_obj in net:
                    logger.warning(f"SSRF blocked: Host '{hostname}' resolved to private/reserved IP {ip_str} in {net}")
                    return False
    except Exception as e:
        logger.debug(f"DNS resolution error for {hostname}: {e}")
        # 如果無法解析 IP，可能為非法或不存在的主機，為保險起見允許標準公共 domain 進入後續由 HTTP client 處理超時
        pass

    return True


# ----------------------------------------------------------------------
# 2. 檔名安全清理 (Path Traversal 防護)
# ----------------------------------------------------------------------
def sanitize_filename(filename: Optional[str], default_prefix: str = "file", default_ext: str = ".txt") -> str:
    """
    清理檔名，防止路徑穿越 (Path Traversal: ../, /etc/passwd 等)
    """
    if not filename:
        return f"{default_prefix}_{int(time.time())}{default_ext}"

    # 取得 base name 移除任何路徑前綴
    base = os.path.basename(filename).strip()

    # 移除特殊控制字元與不可見字元
    cleaned = re.sub(r'[\x00-\x1f\x7f\\/:*?"<>|]', '_', base)
    cleaned = re.sub(r'\.{2,}', '.', cleaned)  # 替換連續點為單點
    cleaned = cleaned.lstrip('.')  # 防止隱藏檔案

    if not cleaned or cleaned == '_':
        return f"{default_prefix}_{int(time.time())}{default_ext}"

    # 長度限制在 128 字元以內
    if len(cleaned) > 128:
        name_part, ext_part = os.path.splitext(cleaned)
        cleaned = name_part[:120] + ext_part

    return cleaned


# ----------------------------------------------------------------------
# 3. 具備 TTL 與 LRU 容量上限的 Session 管理器 (防記憶體耗盡 DoS)
# ----------------------------------------------------------------------
class BoundedSessionManager:
    """
    執行緒安全、具備容量上限 (LRU) 與過期時間 (TTL) 的對話狀態記憶體管理器。
    徹底杜絕高併發或惡意 DoS 時 `user_sessions` 無上限膨脹導致的 OOM 崩潰。
    """

    def __init__(self, max_entries: int = 1000, ttl_seconds: int = 7200):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._store: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        """取得使用者的有效 Session，若過期則自動清除"""
        async with self._lock:
            if user_id not in self._store:
                return None

            entry = self._store[user_id]
            updated_at = entry.get("_updated_at", 0)

            # 檢查是否過期
            if time.time() - updated_at > self.ttl_seconds:
                del self._store[user_id]
                return None

            # 命中後移至最新 (LRU)
            self._store.move_to_end(user_id)
            return entry.get("data")

    async def set(self, user_id: str, data: Dict[str, Any]):
        """寫入或更新 Session，維護 LRU 上限與清理過期項目"""
        async with self._lock:
            # 清理過期項目
            now = time.time()
            expired_keys = [k for k, v in self._store.items() if now - v.get("_updated_at", 0) > self.ttl_seconds]
            for k in expired_keys:
                del self._store[k]

            # 若達到容量上限，淘汰最舊的項目 (LRU)
            while len(self._store) >= self.max_entries:
                self._store.popitem(last=False)

            self._store[user_id] = {
                "data": data,
                "_updated_at": now
            }
            self._store.move_to_end(user_id)

    async def delete(self, user_id: str):
        """刪除指定使用者的 Session"""
        async with self._lock:
            if user_id in self._store:
                del self._store[user_id]

    async def size(self) -> int:
        """取得當前活動 Session 數量"""
        async with self._lock:
            return len(self._store)


# ----------------------------------------------------------------------
# 4. 錯誤資訊脫敏 (防止 CWE-209 敏感路徑與金鑰外洩)
# ----------------------------------------------------------------------
def sanitize_error_message(err: Any, default_fallback: str = "服務處理暫時異常，請稍後再試。") -> str:
    """
    清理對外回傳的錯誤訊息，隱藏內部檔案路徑、API Key 與堆疊細節
    """
    if err is None:
        return default_fallback

    err_str = str(err).strip()
    if not err_str:
        return default_fallback

    # 隱藏任何類似 Bearer token 或 sk-xxx 或 AIzaSy 等 API 金鑰模式
    err_str = re.sub(r'Bearer\s+[A-Za-z0-9_\-\.]{10,}', 'Bearer [REDACTED]', err_str, flags=re.IGNORECASE)
    err_str = re.sub(r'(sk-[A-Za-z0-9]{20,})', '[REDACTED_API_KEY]', err_str)
    err_str = re.sub(r'(AIzaSy[A-Za-z0-9_\-]{30,})', '[REDACTED_API_KEY]', err_str)

    # 隱藏伺服器絕對路徑 (/home/... /Users/... /app/...)
    err_str = re.sub(r'/(home|Users|app|tmp|root|opt)/[A-Za-z0-9_\-\./]+', '[INTERNAL_PATH]', err_str)

    # 限制錯誤字數長度，防止大字串堆疊外洩
    if len(err_str) > 200:
        err_str = err_str[:200] + "..."

    return err_str

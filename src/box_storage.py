"""
Box Storage Client (888box API)
支援多端點容錯 (Primary: box.david888.com, Fallbacks: box.glsoft.ai, box.aiurl.tw)
支援檔案、文字、圖片、影音上傳、遠端 URL 轉存與資產管理
提供同步 (Sync) 與非同步 (Async) 介面
"""

import os
import io
import mimetypes
import logging
import tempfile
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List, Union
import requests

logger = logging.getLogger(__name__)

# 預設端點清單
DEFAULT_BOX_ENDPOINTS = [
    "https://box.david888.com",
    "https://box.glsoft.ai",
    "https://box.aiurl.tw"
]


class BoxStorageClient:
    """888box 雲端儲存客戶端，具備自動容錯切換機制"""

    def __init__(
        self,
        endpoints: Optional[List[str]] = None,
        token: Optional[str] = None,
        timeout: int = 60
    ):
        """
        初始化客戶端

        :param endpoints: 端點列表（優先順序由前至後）
        :param token: API Token（受保護操作時使用）
        :param timeout: 請求逾時時間（秒）
        """
        # 從環境變數或參數讀取端點
        env_endpoints = os.getenv("BOX_ENDPOINTS")
        if env_endpoints:
            self.endpoints = [ep.strip().rstrip("/") for ep in env_endpoints.split(",") if ep.strip()]
        elif endpoints:
            self.endpoints = [ep.rstrip("/") for ep in endpoints]
        else:
            primary = os.getenv("BOX_BASE_URL", "https://box.david888.com").rstrip("/")
            endpoints_list = [primary]
            for fb in DEFAULT_BOX_ENDPOINTS:
                if fb not in endpoints_list:
                    endpoints_list.append(fb)
            self.endpoints = endpoints_list

        self.token = token or os.getenv("BOX_API_TOKEN", "")
        self.timeout = timeout

    # ----------------------------------------------------------------------
    # 核心請求與容錯機制 (Sync)
    # ----------------------------------------------------------------------
    def _request_with_fallback(
        self,
        action: str,
        method: str = "POST",
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """向端點發送請求，若失敗則自動切換至下一個 fallback 端點"""
        last_error = None
        params = params or {}
        data = data or {}

        if self.token and "token" not in data and "token" not in params:
            data["token"] = self.token

        for endpoint in self.endpoints:
            api_url = f"{endpoint}/api.php"
            req_params = dict(params)
            req_params["action"] = action

            try:
                logger.debug(f"[BoxStorage] 嘗試請求端點: {api_url} (action={action})")

                # 如果有 files，需要每次重設 file stream 指標（若為 file 物件）
                if files:
                    for k, v in files.items():
                        if isinstance(v, tuple) and len(v) >= 2 and hasattr(v[1], "seek"):
                            v[1].seek(0)
                        elif hasattr(v, "seek"):
                            v.seek(0)

                headers = {}
                if self.token:
                    headers["Authorization"] = f"Bearer {self.token}"

                if method.upper() == "POST":
                    response = requests.post(
                        api_url,
                        params=req_params,
                        data=data if not files else data,
                        files=files,
                        headers=headers,
                        timeout=self.timeout
                    )
                else:
                    response = requests.get(
                        api_url,
                        params=req_params,
                        headers=headers,
                        timeout=self.timeout
                    )

                if response.status_code == 200:
                    try:
                        res_json = response.json()
                        if res_json.get("result") == "success":
                            res_json["endpoint"] = endpoint
                            return res_json
                        else:
                            err_msg = res_json.get("message", "Unknown error")
                            logger.warning(f"[BoxStorage] 端點 {endpoint} 回應錯誤: {err_msg}")
                            last_error = f"Endpoint {endpoint} returned error: {err_msg}"
                    except Exception as json_err:
                        logger.warning(f"[BoxStorage] 端點 {endpoint} JSON 解析失敗: {json_err}, raw: {response.text[:200]}")
                        last_error = f"Endpoint {endpoint} invalid JSON: {json_err}"
                else:
                    logger.warning(f"[BoxStorage] 端點 {endpoint} 回應 HTTP {response.status_code}")
                    last_error = f"Endpoint {endpoint} HTTP {response.status_code}"

            except Exception as e:
                logger.warning(f"[BoxStorage] 連線端點 {endpoint} 失敗: {e}")
                last_error = str(e)

        # 全部端點皆失敗
        logger.error(f"[BoxStorage] 所有端點請求皆失敗。最後錯誤: {last_error}")
        return {
            "result": "error",
            "message": f"所有儲存端點皆連線失敗: {last_error}"
        }

    # ----------------------------------------------------------------------
    # 核心請求與容錯機制 (Async)
    # ----------------------------------------------------------------------
    async def _request_with_fallback_async(
        self,
        action: str,
        method: str = "POST",
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """非同步向端點發送請求（在線程池中執行 requests 避免阻擋事件迴圈）"""
        return await asyncio.to_thread(
            self._request_with_fallback,
            action=action,
            method=method,
            params=params,
            data=data,
            files=files_data
        )

    # ----------------------------------------------------------------------
    # 公開功能：上傳檔案 (Local File)
    # ----------------------------------------------------------------------
    def upload_file(
        self,
        file_path: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        password: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        上傳本地檔案

        :param file_path: 本地檔案路徑
        :param title: 檔案標題（選填）
        :param description: 檔案描述（選填）
        :param password: 存取密碼（選填）
        :return: {"result": "success", "data": {"id": "...", "url": "...", "share_url": "..."}, "endpoint": "..."}
        """
        if not os.path.isfile(file_path):
            return {"result": "error", "message": f"檔案不存在: {file_path}"}

        filename = os.path.basename(file_path)
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"

        data: Dict[str, Any] = {}
        if title:
            data["title"] = title
        if description:
            data["description"] = description
        if password:
            data["password"] = password

        with open(file_path, "rb") as f:
            files = {"file": (filename, f, mime_type)}
            return self._request_with_fallback("upload", method="POST", data=data, files=files)

    async def upload_file_async(
        self,
        file_path: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        password: Optional[str] = None
    ) -> Dict[str, Any]:
        """非同步上傳本地檔案"""
        return await asyncio.to_thread(
            self.upload_file,
            file_path=file_path,
            title=title,
            description=description,
            password=password
        )

    # ----------------------------------------------------------------------
    # 公開功能：上傳二進位資料 (Bytes / Buffer)
    # ----------------------------------------------------------------------
    def upload_bytes(
        self,
        data_bytes: Union[bytes, io.BytesIO],
        filename: str,
        content_type: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        password: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        上傳二進位資料（如生成的圖片、記憶體中的音訊/影片等）

        :param data_bytes: 二進位資料或 BytesIO 物件
        :param filename: 檔案名稱（包含副檔名，例如 image.png）
        :param content_type: MIME 類型（例如 image/png）
        :param title: 檔案標題（選填）
        :param description: 檔案描述（選填）
        :param password: 存取密碼（選填）
        :return: API 回應字典
        """
        if isinstance(data_bytes, bytes):
            byte_stream = io.BytesIO(data_bytes)
        else:
            byte_stream = data_bytes

        if not content_type:
            mime_type, _ = mimetypes.guess_type(filename)
            content_type = mime_type or "application/octet-stream"

        form_data: Dict[str, Any] = {}
        if title:
            form_data["title"] = title
        if description:
            form_data["description"] = description
        if password:
            form_data["password"] = password

        files = {"file": (filename, byte_stream, content_type)}
        return self._request_with_fallback("upload", method="POST", data=form_data, files=files)

    async def upload_bytes_async(
        self,
        data_bytes: Union[bytes, io.BytesIO],
        filename: str,
        content_type: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        password: Optional[str] = None
    ) -> Dict[str, Any]:
        """非同步上傳二進位資料"""
        return await asyncio.to_thread(
            self.upload_bytes,
            data_bytes=data_bytes,
            filename=filename,
            content_type=content_type,
            title=title,
            description=description,
            password=password
        )

    # ----------------------------------------------------------------------
    # 公開功能：上傳純文字 (Text / TXT)
    # ----------------------------------------------------------------------
    def upload_text(
        self,
        text_content: str,
        filename: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        password: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        上傳文字內容為 .txt 檔案（如摘要記錄、逐字稿等）

        :param text_content: 文字字串
        :param filename: 檔案名稱（預設為 summary_YYYYMMDD_HHMMSS.txt）
        :param title: 標題
        :param description: 描述
        :param password: 密碼
        :return: API 回應字典
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"summary_{timestamp}.txt"
        elif not filename.endswith(".txt"):
            filename += ".txt"

        raw_bytes = text_content.encode("utf-8")
        return self.upload_bytes(
            data_bytes=raw_bytes,
            filename=filename,
            content_type="text/plain; charset=utf-8",
            title=title,
            description=description,
            password=password
        )

    async def upload_text_async(
        self,
        text_content: str,
        filename: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        password: Optional[str] = None
    ) -> Dict[str, Any]:
        """非同步上傳文字內容為 .txt 檔案"""
        return await asyncio.to_thread(
            self.upload_text,
            text_content=text_content,
            filename=filename,
            title=title,
            description=description,
            password=password
        )

    # ----------------------------------------------------------------------
    # 公開功能：從遠端 URL 轉存檔案 (Remote URL Ingest)
    # ----------------------------------------------------------------------
    def upload_url(
        self,
        remote_url: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        password: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        將遠端 URL 資源轉存到儲存庫中。
        優先嘗試 server-side upload_url，若不支援則自動下載至暫存區再透過 upload 上傳。

        :param remote_url: 遠端資源網址
        :param title: 標題
        :param description: 描述
        :param password: 密碼
        :return: API 回應字典
        """
        # 1. 嘗試直接呼叫 upload_url action
        data: Dict[str, Any] = {"url": remote_url}
        if title:
            data["title"] = title
        if description:
            data["description"] = description
        if password:
            data["password"] = password

        res = self._request_with_fallback("upload_url", method="POST", data=data)
        if res.get("result") == "success":
            return res

        # 2. 若 upload_url 失敗，自動透過本機串流下載並上傳
        logger.info(f"[BoxStorage] 遠端轉存失敗，改採本地下載中繼上傳: {remote_url}")
        try:
            with requests.get(remote_url, stream=True, timeout=120) as r:
                r.raise_for_status()
                # 猜測檔名
                content_disposition = r.headers.get("content-disposition", "")
                filename = None
                if "filename=" in content_disposition:
                    filename = content_disposition.split("filename=")[-1].strip('"\'')
                if not filename:
                    url_path = remote_url.split("?")[0].rstrip("/")
                    filename = os.path.basename(url_path) or f"downloaded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

                content_type = r.headers.get("content-type", "application/octet-stream").split(";")[0]

                # 讀取串流或暫存上傳
                with tempfile.NamedTemporaryFile(delete=True) as tmp:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            tmp.write(chunk)
                    tmp.flush()
                    tmp.seek(0)

                    return self.upload_bytes(
                        data_bytes=tmp.read(),
                        filename=filename,
                        content_type=content_type,
                        title=title or filename,
                        description=description,
                        password=password
                    )
        except Exception as e:
            logger.error(f"[BoxStorage] 中繼下載上傳失敗: {e}")
            return {"result": "error", "message": f"URL 轉存失敗: {e}"}

    async def upload_url_async(
        self,
        remote_url: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        password: Optional[str] = None
    ) -> Dict[str, Any]:
        """非同步從遠端 URL 轉存檔案"""
        return await asyncio.to_thread(
            self.upload_url,
            remote_url=remote_url,
            title=title,
            description=description,
            password=password
        )

    # ----------------------------------------------------------------------
    # 公開功能：查詢統計與管理 (Stats, List, Search, Delete)
    # ----------------------------------------------------------------------
    def get_stats(self) -> Dict[str, Any]:
        """取得資產統計數據"""
        return self._request_with_fallback("stats", method="GET")

    async def get_stats_async(self) -> Dict[str, Any]:
        """非同步取得資產統計數據"""
        return await asyncio.to_thread(self.get_stats)

    def list_assets(self, asset_type: str = "all", page: int = 1) -> Dict[str, Any]:
        """取得資產列表（需 Token）"""
        return self._request_with_fallback(
            "list",
            method="GET",
            params={"type": asset_type, "page": page}
        )

    def search_assets(self, query: str, asset_type: str = "all") -> Dict[str, Any]:
        """搜尋資產（需 Token）"""
        return self._request_with_fallback(
            "search",
            method="GET",
            params={"q": query, "type": asset_type}
        )

    def delete_asset(self, asset_id: Union[str, int]) -> Dict[str, Any]:
        """刪除資產（需 Token）"""
        return self._request_with_fallback(
            "delete",
            method="POST",
            data={"id": str(asset_id)}
        )


# ----------------------------------------------------------------------
# 模組級便利函式 (Singleton Instance)
# ----------------------------------------------------------------------
_default_client = BoxStorageClient()

def get_storage_client() -> BoxStorageClient:
    """取得全域 BoxStorageClient 實例"""
    return _default_client

def upload_file(file_path: str, title: Optional[str] = None, description: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
    return _default_client.upload_file(file_path, title=title, description=description, password=password)

def upload_bytes(data_bytes: Union[bytes, io.BytesIO], filename: str, content_type: Optional[str] = None, title: Optional[str] = None, description: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
    return _default_client.upload_bytes(data_bytes, filename, content_type=content_type, title=title, description=description, password=password)

def upload_text(text_content: str, filename: Optional[str] = None, title: Optional[str] = None, description: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
    return _default_client.upload_text(text_content, filename=filename, title=title, description=description, password=password)

def upload_image(image_data_or_path: Union[str, bytes, io.BytesIO], filename: Optional[str] = None, title: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
    if isinstance(image_data_or_path, str) and os.path.isfile(image_data_or_path):
        return _default_client.upload_file(image_data_or_path, title=title, description=description)
    else:
        fn = filename or f"image_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        return _default_client.upload_bytes(image_data_or_path, filename=fn, content_type="image/png", title=title, description=description)

def upload_video(video_data_or_path: Union[str, bytes, io.BytesIO], filename: Optional[str] = None, title: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
    if isinstance(video_data_or_path, str) and os.path.isfile(video_data_or_path):
        return _default_client.upload_file(video_data_or_path, title=title, description=description)
    else:
        fn = filename or f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        return _default_client.upload_bytes(video_data_or_path, filename=fn, content_type="video/mp4", title=title, description=description)

def upload_audio(audio_data_or_path: Union[str, bytes, io.BytesIO], filename: Optional[str] = None, title: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
    if isinstance(audio_data_or_path, str) and os.path.isfile(audio_data_or_path):
        return _default_client.upload_file(audio_data_or_path, title=title, description=description)
    else:
        fn = filename or f"audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
        return _default_client.upload_bytes(audio_data_or_path, filename=fn, content_type="audio/mpeg", title=title, description=description)

def upload_url(remote_url: str, title: Optional[str] = None, description: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
    return _default_client.upload_url(remote_url, title=title, description=description, password=password)

def get_stats() -> Dict[str, Any]:
    return _default_client.get_stats()

def list_assets(asset_type: str = "all", page: int = 1) -> Dict[str, Any]:
    return _default_client.list_assets(asset_type=asset_type, page=page)

def search_assets(query: str, asset_type: str = "all") -> Dict[str, Any]:
    return _default_client.search_assets(query=query, asset_type=asset_type)

def delete_asset(asset_id: Union[str, int]) -> Dict[str, Any]:
    return _default_client.delete_asset(asset_id=asset_id)

# Async versions
async def upload_file_async(file_path: str, title: Optional[str] = None, description: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
    return await _default_client.upload_file_async(file_path, title=title, description=description, password=password)

async def upload_bytes_async(data_bytes: Union[bytes, io.BytesIO], filename: str, content_type: Optional[str] = None, title: Optional[str] = None, description: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
    return await _default_client.upload_bytes_async(data_bytes, filename, content_type=content_type, title=title, description=description, password=password)

async def upload_text_async(text_content: str, filename: Optional[str] = None, title: Optional[str] = None, description: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
    return await _default_client.upload_text_async(text_content, filename=filename, title=title, description=description, password=password)

async def upload_image_async(image_data_or_path: Union[str, bytes, io.BytesIO], filename: Optional[str] = None, title: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
    if isinstance(image_data_or_path, str) and os.path.isfile(image_data_or_path):
        return await _default_client.upload_file_async(image_data_or_path, title=title, description=description)
    else:
        fn = filename or f"image_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        return await _default_client.upload_bytes_async(image_data_or_path, filename=fn, content_type="image/png", title=title, description=description)

async def upload_video_async(video_data_or_path: Union[str, bytes, io.BytesIO], filename: Optional[str] = None, title: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
    if isinstance(video_data_or_path, str) and os.path.isfile(video_data_or_path):
        return await _default_client.upload_file_async(video_data_or_path, title=title, description=description)
    else:
        fn = filename or f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        return await _default_client.upload_bytes_async(video_data_or_path, filename=fn, content_type="video/mp4", title=title, description=description)

async def upload_audio_async(audio_data_or_path: Union[str, bytes, io.BytesIO], filename: Optional[str] = None, title: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
    if isinstance(audio_data_or_path, str) and os.path.isfile(audio_data_or_path):
        return await _default_client.upload_file_async(audio_data_or_path, title=title, description=description)
    else:
        fn = filename or f"audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
        return await _default_client.upload_bytes_async(audio_data_or_path, filename=fn, content_type="audio/mpeg", title=title, description=description)

async def upload_url_async(remote_url: str, title: Optional[str] = None, description: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
    return await _default_client.upload_url_async(remote_url, title=title, description=description, password=password)

async def get_stats_async() -> Dict[str, Any]:
    return await _default_client.get_stats_async()

async def list_assets_async(asset_type: str = "all", page: int = 1) -> Dict[str, Any]:
    return await asyncio.to_thread(_default_client.list_assets, asset_type=asset_type, page=page)

async def search_assets_async(query: str, asset_type: str = "all") -> Dict[str, Any]:
    return await asyncio.to_thread(_default_client.search_assets, query=query, asset_type=asset_type)

async def delete_asset_async(asset_id: Union[str, int]) -> Dict[str, Any]:
    return await asyncio.to_thread(_default_client.delete_asset, asset_id=asset_id)

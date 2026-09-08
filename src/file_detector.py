"""
File Detector Module (Google Magika AI-powered File Identification)
採用 Google Magika 深度學習模型於本地端毫秒級推論檔案 MIME Type 與類型。
具備單例模式 (Singleton)、啟動預熱 (Warmup) 與原生相容容錯機制。
"""

import os
import mimetypes
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional, List, Union, Any

logger = logging.getLogger("file-detector")

try:
    from magika import Magika
    HAS_MAGIKA = True
except ImportError:
    Magika = None
    HAS_MAGIKA = False
    logger.warning("Google Magika 套件未安裝，將自動降級採用標準 mimetypes 模組。")


@dataclass
class ContentTypeResult:
    """檔案內容類型辨識結果物件"""
    mime_type: str
    label: str
    group: str
    description: str
    extensions: List[str] = field(default_factory=list)
    score: float = 1.0
    is_text: bool = False

    @property
    def primary_extension(self) -> str:
        """取得最推薦之副檔名（含小數點，例如 '.png', '.pdf'）"""
        if self.extensions:
            ext = self.extensions[0].lstrip('.')
            return f".{ext}"
        # 嘗試從 mimetypes 反查
        guessed_ext = mimetypes.guess_extension(self.mime_type)
        if guessed_ext:
            return guessed_ext
        return ".bin" if not self.is_text else ".txt"


# 單例管理
_magika_lock = threading.Lock()
_magika_instance: Optional[Any] = None


def get_magika() -> Optional[Any]:
    """
    取得 Magika 全域單例實例。
    線程安全且延遲載入 (Thread-safe Lazy Initialization)。
    """
    global _magika_instance
    if not HAS_MAGIKA:
        return None

    if _magika_instance is None:
        with _magika_lock:
            if _magika_instance is None:
                try:
                    logger.info("Initializing Google Magika AI Model (Singleton)...")
                    _magika_instance = Magika()
                    logger.info("Google Magika AI Model initialized successfully.")
                except Exception as e:
                    logger.error(f"Failed to initialize Magika model: {e}")
                    return None
    return _magika_instance


def warmup_file_detector() -> bool:
    """
    於應用程式啟動時進行預熱，將 ONNX 模型提前載入至記憶體，
    避免首次請求時產生初始化延遲。
    """
    try:
        instance = get_magika()
        if instance:
            # 傳入二進位進行推論預熱
            instance.identify_bytes(b"%PDF-1.4\n%test warmup")
            logger.info("Magika file detector warmed up successfully.")
            return True
    except Exception as e:
        logger.warning(f"File detector warmup warning: {e}")
    return False


def _fallback_from_filename(filename_or_path: str) -> ContentTypeResult:
    """使用標準 mimetypes 作為備援推論"""
    mime_type, _ = mimetypes.guess_type(filename_or_path)
    mime = mime_type or "application/octet-stream"
    ext = os.path.splitext(filename_or_path)[1].lstrip('.').lower()
    extensions = [ext] if ext else []
    is_text = mime.startswith("text/")

    # 簡易分類分組
    if mime.startswith("image/"):
        group = "image"
    elif mime.startswith("audio/"):
        group = "audio"
    elif mime.startswith("video/"):
        group = "video"
    elif mime.startswith("text/") or ext in ["json", "xml", "csv", "md", "py", "sh", "js"]:
        group = "code" if ext in ["py", "sh", "js", "html", "css"] else "text"
        is_text = True
    elif mime in ["application/pdf", "application/msword"] or ext in ["pdf", "docx", "doc", "pptx", "xlsx"]:
        group = "document"
    else:
        group = "unknown"

    return ContentTypeResult(
        mime_type=mime,
        label=ext or "unknown",
        group=group,
        description=f"Standard mime guess ({mime})",
        extensions=extensions,
        score=0.5,
        is_text=is_text
    )


def detect_content_type(file_path: Union[str, os.PathLike]) -> ContentTypeResult:
    """
    精確辨識本地檔案之內容類型 (MIME Type, 標籤, 副檔名)。
    優先使用 Google Magika 深度學習模型，若失敗自動優雅降級。

    :param file_path: 本地檔案路徑
    :return: ContentTypeResult
    """
    path_str = str(file_path)
    if not os.path.exists(path_str):
        return _fallback_from_filename(path_str)

    magika = get_magika()
    if magika:
        try:
            res = magika.identify_path(path_str)
            is_ok = res.ok() if callable(getattr(res, "ok", None)) else getattr(res, "ok", True)
            if res and is_ok:
                out = res.output
                lbl = getattr(out.label, "value", str(out.label))
                return ContentTypeResult(
                    mime_type=str(out.mime_type),
                    label=str(lbl),
                    group=str(getattr(out, "group", "unknown")),
                    description=str(getattr(out, "description", "")),
                    extensions=list(getattr(out, "extensions", []) or []),
                    score=float(getattr(res, "score", 1.0)),
                    is_text=bool(getattr(out, "is_text", False))
                )
        except Exception as e:
            logger.warning(f"Magika identify_path failed for {file_path}: {e}")

    return _fallback_from_filename(path_str)


def detect_content_type_bytes(
    content: bytes,
    filename_hint: Optional[str] = None
) -> ContentTypeResult:
    """
    從記憶體二進位資料 (Bytes) 直接辨識內容類型。
    適用於上傳串流、HTTP 下載緩衝區、生成的圖片或錄音檔。

    :param content: 檔案二進位 bytes
    :param filename_hint: 選填的檔案名稱提示（當二進位特徵不足時提供輔助）
    :return: ContentTypeResult
    """
    if not content:
        if filename_hint:
            return _fallback_from_filename(filename_hint)
        return ContentTypeResult(
            mime_type="application/octet-stream",
            label="empty",
            group="unknown",
            description="Empty content",
            extensions=[],
            score=0.0,
            is_text=False
        )

    magika = get_magika()
    if magika:
        try:
            res = magika.identify_bytes(content)
            is_ok = res.ok() if callable(getattr(res, "ok", None)) else getattr(res, "ok", True)
            if res and is_ok:
                out = res.output
                lbl = getattr(out.label, "value", str(out.label))
                # 若 Magika 信心度合格，或沒有提供檔名提示，直接回傳
                if res.score >= 0.5 or not filename_hint:
                    return ContentTypeResult(
                        mime_type=str(out.mime_type),
                        label=str(lbl),
                        group=str(getattr(out, "group", "unknown")),
                        description=str(getattr(out, "description", "")),
                        extensions=list(getattr(out, "extensions", []) or []),
                        score=float(getattr(res, "score", 1.0)),
                        is_text=bool(getattr(out, "is_text", False))
                    )
        except Exception as e:
            logger.warning(f"Magika identify_bytes failed: {e}")

    # 若 Magika 降級或信心度過低且有檔名提示
    if filename_hint:
        return _fallback_from_filename(filename_hint)

    return ContentTypeResult(
        mime_type="application/octet-stream",
        label="unknown",
        group="unknown",
        description="Unknown binary data",
        extensions=[],
        score=0.0,
        is_text=False
    )


def get_safe_extension(content: Union[bytes, str], fallback: str = ".bin") -> str:
    """
    根據二進位 bytes 或檔案路徑取得安全的標準副檔名（含前綴點，如 .png、.mp3）。
    """
    if isinstance(content, bytes):
        res = detect_content_type_bytes(content)
    else:
        res = detect_content_type(str(content))
    return res.primary_extension or fallback

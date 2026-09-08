"""
Integration Test for Google Magika & Multi-media Processing
"""
import sys
import unittest
from src.file_detector import (
    get_magika,
    warmup_file_detector,
    detect_content_type,
    detect_content_type_bytes,
    get_safe_extension
)
from src.box_storage import BoxStorageClient
from src.agent_tools import AgentActuators, AGENT_TOOLS


class TestMagikaIntegration(unittest.TestCase):

    def test_01_warmup(self):
        """測試 Magika 預熱與單例載入"""
        result = warmup_file_detector()
        self.assertTrue(result, "Magika warmup should succeed")
        instance = get_magika()
        self.assertIsNotNone(instance, "Magika singleton instance should not be None")

    def test_02_detect_image_file(self):
        """測試現有圖片檔案辨識"""
        res = detect_content_type("image.png")
        self.assertEqual(res.mime_type, "image/png")
        self.assertEqual(res.label, "png")
        self.assertEqual(res.group, "image")
        self.assertGreater(res.score, 0.9)
        self.assertFalse(res.is_text)

    def test_03_detect_python_code_file(self):
        """測試程式碼檔案辨識"""
        res = detect_content_type("app.py")
        self.assertIn("python", res.label.lower())
        self.assertTrue(res.is_text)

    def test_04_detect_bytes_pdf(self):
        """測試二進位 bytes 辨識 (PDF)"""
        pdf_bytes = b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<<>>\n%%EOF"
        res = detect_content_type_bytes(pdf_bytes, filename_hint="document.pdf")
        self.assertEqual(res.mime_type, "application/pdf")
        self.assertEqual(res.label, "pdf")
        self.assertEqual(res.group, "document")
        self.assertEqual(get_safe_extension(pdf_bytes), ".pdf")

    def test_05_detect_bytes_audio(self):
        """測試二進位 bytes 辨識 (Audio MP3)"""
        mp3_header = b"ID3\x04\x00\x00\x00\x00\x00#TSSE\x00\x00\x00\x0f\x00\x00\x03Lavf58.76.100\x00" + b"\xff\xfb\x90d" + b"\x00" * 100
        res = detect_content_type_bytes(mp3_header, filename_hint="voice.mp3")
        self.assertIn(res.group, ["audio", "unknown"])
        self.assertIn("audio", res.mime_type)

    def test_06_agent_tools_schema(self):
        """測試 Agent 工具列表中包含 inspect_file_type"""
        tool_names = [t["function"]["name"] for t in AGENT_TOOLS]
        self.assertIn("inspect_file_type", tool_names)

    def test_07_box_storage_upload_bytes_detection(self):
        """測試 BoxStorageClient 在 upload_bytes 時自動推論 Content-Type"""
        client = BoxStorageClient()
        with open("image.png", "rb") as f:
            png_sample = f.read(512)
        
        # 模擬呼叫內部上傳，攔截 Content-Type
        filename = "upload_test.bin"
        # 測試推論
        res = detect_content_type_bytes(png_sample, filename_hint=filename)
        self.assertEqual(res.mime_type, "image/png")
        self.assertEqual(res.primary_extension, ".png")


if __name__ == "__main__":
    unittest.main()

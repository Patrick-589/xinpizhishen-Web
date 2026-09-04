from __future__ import annotations

import tempfile
import unittest
import io
import zipfile
from pathlib import Path
import sys
from unittest.mock import patch


SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from sync_official_rule_knowledge import (  # noqa: E402
    SZSE_OFFICIAL_ATTACHMENT_FALLBACKS,
    csrc_document_text,
    parser_filename,
    parse_szse_article,
    parse_szse_json_detail,
    read_json,
    request_bytes,
)


class OfficialRuleSyncTests(unittest.TestCase):
    def test_szse_article_extracts_body_and_supported_attachments_only(self) -> None:
        html = """
        <html><body>
          <h2>标题元数据不属于正文</h2><div class="time">2026-08-25</div>
          <div class="des-content" id="desContent">
            <p>第一条 上市公司应当真实、准确、完整地披露信息。</p>
            <p><a href="../files/rule.pdf">规则附件</a></p>
            <p><a href="../files/table.xlsx">不支持附件</a></p>
          </div>
        </body></html>
        """
        text, attachments = parse_szse_article(
            html, "https://www.szse.cn/lawrules/rule/stock/example.html",
        )
        self.assertIn("第一条", text)
        self.assertNotIn("标题元数据", text)
        self.assertNotIn("2026-08-25", text)
        self.assertEqual(
            attachments,
            ["https://www.szse.cn/lawrules/rule/files/rule.pdf"],
        )

    def test_csrc_embedding_text_contains_only_official_body_sections(self) -> None:
        record = {
            "title": "标题只作为 metadata",
            "publishedAt": "2026-08-25",
            "sourceStatus": "current-effective",
            "body": "总则正文",
            "sections": [
                {"title": "第一条", "content": "上市公司应当依法披露。"},
                {"title": "第二条", "content": "相关责任人应当勤勉尽责。"},
            ],
        }
        text = csrc_document_text(record)
        self.assertIn("总则正文", text)
        self.assertIn("第一条", text)
        self.assertNotIn("标题只作为 metadata", text)
        self.assertNotIn("2026-08-25", text)
        self.assertNotIn("current-effective", text)

    def test_szse_json_detail_recovers_official_body_and_attachment(self) -> None:
        raw = r'''{
          "code": 0,
          "data": {
            "title": "标题只作为 metadata",
            "content": "<p>第一条 上市公司应当依法披露。</p><p><a href=\"W020_test.docx\">附件</a></p>"
          }
        }'''
        text, attachments = parse_szse_json_detail(
            raw,
            "https://www.szse.cn/lawrules/service/share/t20230909_603416.json",
        )
        self.assertIn("第一条", text)
        self.assertNotIn("标题只作为 metadata", text)
        self.assertEqual(
            attachments,
            ["https://www.szse.cn/lawrules/service/share/W020_test.docx"],
        )

    def test_mislabeled_docx_attachment_uses_its_real_format(self) -> None:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("word/document.xml", "<document/>")
        self.assertEqual(parser_filename("official-rule.doc", output.getvalue()), "official-rule.docx")
        self.assertEqual(parser_filename("legacy.doc", b"\xd0\xcf\x11\xe0"), "legacy.doc")

    def test_corrupt_manifest_falls_back_to_database_reconstruction_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_bytes(b"\x00" * 128)
            fallback = {"schemaVersion": 1, "records": {}}
            self.assertEqual(read_json(path, fallback), fallback)

    def test_empty_official_attachment_is_rejected_before_parsing(self) -> None:
        class Headers:
            @staticmethod
            def get_content_type() -> str:
                return "application/msword"

        class EmptyResponse:
            headers = Headers()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            @staticmethod
            def read() -> bytes:
                return b""

        with patch("sync_official_rule_knowledge.urllib.request.urlopen", return_value=EmptyResponse()):
            with self.assertRaisesRegex(RuntimeError, "官方来源返回空文件"):
                request_bytes("https://www.szse.cn/empty.doc", attempts=1)

    def test_broken_szse_attachment_uses_a_csrc_official_source(self) -> None:
        fallback = SZSE_OFFICIAL_ATTACHMENT_FALLBACKS["555184"]
        self.assertEqual(fallback["source_name"], "中国证券监督管理委员会")
        self.assertTrue(fallback["download_url"].startswith("https://www.csrc.gov.cn/"))
        self.assertTrue(fallback["source_url"].endswith("/content.shtml"))
        self.assertEqual(fallback["filename"], "szse_555184.doc")


if __name__ == "__main__":
    unittest.main()

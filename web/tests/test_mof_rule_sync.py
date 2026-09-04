from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_mof_accounting_knowledge.py"
SPEC = importlib.util.spec_from_file_location("sync_mof_accounting_knowledge_test", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class MofRuleSyncTest(unittest.TestCase):
    def test_list_links_resolve_against_category_page(self) -> None:
        content = b'<ul><li><a href="./202608/t20260805_3994927.htm">title</a></li></ul>'
        records = MODULE.parse_list(
            content,
            "policy",
            "policy",
            "https://kjs.mof.gov.cn/zhengcefabu/",
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0]["url"],
            "https://kjs.mof.gov.cn/zhengcefabu/202608/t20260805_3994927.htm",
        )
        self.assertEqual(records[0]["publishedAt"], "2026-08-05")

    def test_article_body_and_attachment_are_preserved(self) -> None:
        html = """
        <meta name="PubDate" content="2026-08-05 10:01:00">
        <div class="my_doccontent">
          <p>first article</p><p>second article</p>
          <a href="./files/standard.pdf">attachment</a>
        </div>
        """.encode()
        body, attachments, meta = MODULE.parse_article(
            html,
            "https://kjs.mof.gov.cn/zhengcefabu/202608/t20260805_3994927.htm",
        )
        self.assertIn("first article", body)
        self.assertIn("second article", body)
        self.assertEqual(meta["pubdate"], "2026-08-05 10:01:00")
        self.assertEqual(
            attachments,
            ["https://kjs.mof.gov.cn/zhengcefabu/202608/files/standard.pdf"],
        )

    def test_source_index_keeps_only_accounting_material(self) -> None:
        records = [
            {"id": "1", "title": "enterprise accounting standard", "categoryId": "policy", "categoryName": "policy"},
            {"id": "2", "title": "ordinary news", "categoryId": "notice", "categoryName": "notice"},
        ]
        original_terms = MODULE.ACCOUNTING_TERMS
        try:
            MODULE.ACCOUNTING_TERMS = ("accounting standard",)
            payload = MODULE.source_index(records)
        finally:
            MODULE.ACCOUNTING_TERMS = original_terms
        self.assertEqual([record["id"] for record in payload["records"]], ["1"])
        self.assertEqual(payload["records"][0]["reviewScopes"], ["financial-accounting", "periodic-report"])

    def test_status_distinguishes_drafts_and_interpretations(self) -> None:
        self.assertEqual(
            MODULE.status_for_title("公开征求某准则意见", "policy")[0],
            "draft-consultation",
        )
        self.assertEqual(
            MODULE.status_for_title("某准则答记者问", "interpretation")[0],
            "official-interpretation",
        )
        self.assertEqual(
            MODULE.status_for_title("关于印发某准则的通知", "policy")[0],
            "official-published",
        )


if __name__ == "__main__":
    unittest.main()

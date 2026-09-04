from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1]
import sys
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from backend.chunking import ChunkRecord  # noqa: E402
from backend.database import Database, utc_now  # noqa: E402
from backend.structured_facts import (  # noqa: E402
    MATTER_BUSINESS,
    MATTER_RESTRUCTURING,
    StructuredFactEngine,
)


class StructuredFactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "facts.db")
        self.db.migrate()
        now = utc_now()
        self.db.execute(
            "INSERT INTO users (id,username,password_hash,display_name,role,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            ("user-1", "fact-user", "hash", "Fact User", "user", now, now),
        )
        self.engine = StructuredFactEngine(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _knowledge(self, doc_id: str, title: str, published: str) -> None:
        now = utc_now()
        self.db.execute(
            """INSERT INTO knowledge_documents (
                   id,owner_user_id,title,document_type,company,source,publication_date,file_path,
                   file_hash,status,created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, None, title, "announcements", "创业黑马科技集团股份有限公司", "巨潮资讯网",
             published, str(Path(self.tmp.name) / f"{doc_id}.pdf"), doc_id, "active", now, now),
        )

    def _chunks(self, doc_id: str, text: str, page: int = 3) -> list[ChunkRecord]:
        return [ChunkRecord(
            id=f"chunk-{doc_id}", content=text, page=page, section="重大事项", paragraph=1,
            chunk_index=0, content_hash=f"hash-{doc_id}", metadata={"file_name": f"{doc_id}.pdf"},
        )]

    def test_extracts_status_amount_date_and_business_facts(self) -> None:
        self._knowledge("doc-1", "创业黑马重大资产重组进展公告", "2026-08-21")
        facts = self.engine.replace_document_facts(
            "doc-1",
            self._chunks("doc-1", "公司拟发行股份及支付现金购买资产，交易作价为8,000万元。截至2026年8月21日，申请已获受理。后续尚需监管机构审核。"),
            knowledge=True,
        )
        self.assertGreaterEqual(facts, 4)
        rows = self.db.fetch_all("SELECT * FROM structured_facts WHERE knowledge_document_id=?", ("doc-1",))
        statuses = {row["status"] for row in rows if row["fact_type"] == "status"}
        self.assertIn("已受理", statuses)
        self.assertIn("尚需审批", statuses)
        self.assertTrue(any(row["fact_key"] == "transaction_price" and row["normalized_value"] == "80000000" for row in rows))
        self.assertTrue(any(row["matter"] == MATTER_RESTRUCTURING and row["page"] == 3 for row in rows))

    def test_status_requires_transaction_context_and_accepts_ocr_date_spacing(self) -> None:
        self._knowledge("ocr", "创业黑马重大资产重组进展公告", "2026-08-21")
        self.engine.replace_document_facts(
            "ocr",
            self._chunks(
                "ocr",
                "公司于 2025 年 6 月 30 日收到深交所出具的发行股份购买资产申请已受理。订单提交、审核出证、费用结算均通过。",
            ),
            knowledge=True,
        )
        rows = self.db.fetch_all("SELECT * FROM structured_facts WHERE knowledge_document_id=?", ("ocr",))
        status_rows = [row for row in rows if row["fact_type"] == "status"]
        self.assertTrue(any(row["status"] == "已受理" and row["event_date"] == "2025-06-30" for row in status_rows))
        self.assertFalse(any(row["status"] == "已提交" for row in status_rows))

    def test_latest_fact_is_current_and_conflicting_values_are_retained(self) -> None:
        self._knowledge("old", "创业黑马重大资产重组公告", "2026-06-30")
        self._knowledge("new", "创业黑马重大资产重组进展公告", "2026-08-21")
        self.engine.replace_document_facts(
            "old", self._chunks("old", "公司发行股份及支付现金购买资产，交易作价为8,000万元，申请已提交。"), knowledge=True,
        )
        self.engine.replace_document_facts(
            "new", self._chunks("new", "公司发行股份及支付现金购买资产，交易作价为9,000万元，申请已获受理。"), knowledge=True,
        )
        current = self.db.fetch_all(
            "SELECT * FROM structured_facts WHERE fact_key='transaction_price' AND is_current=1 ORDER BY publication_date",
        )
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["normalized_value"], "90000000")
        conflicts = self.db.fetch_all("SELECT * FROM structured_fact_conflicts WHERE fact_key='transaction_price'")
        self.assertEqual(len(conflicts), 1)
        self.assertIn("80000000", conflicts[0]["values_json"])
        self.assertIn("90000000", conflicts[0]["values_json"])

    def test_bundle_distinguishes_history_current_status_and_evidence(self) -> None:
        self._knowledge("business", "创业黑马2025年年度报告", "2026-04-25")
        self._knowledge("restructuring", "创业黑马重组进展公告", "2026-08-21")
        self.engine.replace_document_facts(
            "business", self._chunks("business", "公司主要从事企业服务业务，上市以来持续完善业务布局。"), knowledge=True,
        )
        self.engine.replace_document_facts(
            "restructuring", self._chunks("restructuring", "发行股份及支付现金购买资产的申请已获受理，尚需审核。"), knowledge=True,
        )
        bundle = self.engine.build_bundle("创业黑马重大资产重组截至2026年8月的最新进展是什么", user_id="user-1")
        self.assertEqual(bundle["current_status"]["status"], "尚需审批")
        self.assertTrue(bundle["timeline"])
        self.assertTrue(any(not item["historical"] for item in bundle["timeline"]))
        self.assertTrue(bundle["evidence_chains"])
        self.assertEqual(bundle["evidence_chains"][0]["evidence"]["page"], 3)
        self.assertTrue(any(fact["matter"] == MATTER_RESTRUCTURING for fact in bundle["facts"]))

    def test_business_history_question_returns_business_facts_and_provenance(self) -> None:
        self._knowledge("history", "创业黑马2025年年度报告", "2026-04-25")
        self.engine.replace_document_facts(
            "history",
            self._chunks("history", "公司成立于2011年，主要从事企业服务业务，上市以来持续完善业务布局。"),
            knowledge=True,
        )
        bundle = self.engine.build_bundle("创业黑马公司业务发展历史是什么", user_id="user-1")
        self.assertTrue(bundle["facts"])
        self.assertTrue(any(fact["matter"] == MATTER_BUSINESS for fact in bundle["facts"]))
        self.assertTrue(any(fact["fact_type"] == "business_history" for fact in bundle["facts"]))
        self.assertTrue(bundle["citations"])
        self.assertEqual(bundle["citations"][0]["page"], 3)


if __name__ == "__main__":
    unittest.main()

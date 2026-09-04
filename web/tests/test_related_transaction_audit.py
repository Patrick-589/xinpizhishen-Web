import sys
import unittest
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from backend.parsers import parse_document  # noqa: E402
from backend.related_transaction_audit import analyze_major_related_transactions  # noqa: E402


class MajorRelatedTransactionAuditTests(unittest.TestCase):
    def _audit(self, body: str) -> list[dict]:
        parsed = parse_document("2025年年度报告.txt", body.encode("utf-8"))
        return analyze_major_related_transactions(parsed)

    def test_missing_major_section_is_located_and_needs_review(self) -> None:
        risks = self._audit(
            "创业黑马科技集团股份有限公司2025年年度报告\n"
            "第十节 关联方及关联交易\n"
            "交易性质：设立子公司；交易对方：黑马子公司；交易金额：1,000万元\n"
        )
        self.assertEqual(len(risks), 1)
        risk = risks[0]
        self.assertEqual(risk["level"], "needs_review")
        self.assertIn("可能未在重大关联交易章节", risk["title"])
        self.assertEqual(len(risk["location"]["items"]), 1)
        self.assertIn("1,000万元", risk["evidence"])
        self.assertEqual(risk["calculation"]["status"], "related_without_major_match")

    def test_amount_and_nature_mismatch_keep_both_original_locations(self) -> None:
        risks = self._audit(
            "创业黑马科技集团股份有限公司2025年年度报告\n"
            "第十节 关联方及关联交易\n"
            "交易性质：设立子公司；交易对方：黑马子公司；交易金额：1,000万元\n"
            "第十一节 重大关联交易\n"
            "交易性质：对外投资；交易对方：黑马子公司；交易金额：800万元\n"
        )
        titles = [risk["title"] for risk in risks]
        self.assertIn("关联交易金额跨章节不一致", titles)
        self.assertIn("关联交易性质跨章节表述不一致", titles)
        for risk in risks:
            self.assertEqual(len(risk["location"]["items"]), 2)
            self.assertEqual(
                {item["section"] for item in risk["location"]["items"]},
                {"第十节 关联方及关联交易", "第十一节 重大关联交易"},
            )

    def test_matching_transaction_does_not_create_finding(self) -> None:
        risks = self._audit(
            "2025年年度报告\n"
            "第十节 关联方及关联交易\n"
            "交易性质：子公司增资；交易对方：甲公司；交易金额：2,500万元\n"
            "第十一节 重大关联交易\n"
            "交易性质：子公司增资；交易对方：甲公司；交易金额：2,500万元\n"
        )
        self.assertEqual(risks, [])

    def test_related_section_headers_are_not_treated_as_transactions(self) -> None:
        risks = self._audit(
            "2025年年度报告\n"
            "第十节 关联方及关联交易\n"
            "交易类型 | 关联方 | 交易金额 | 交易性质\n"
            "第十一节 重大关联交易\n"
            "重大关联交易情况如下：无。\n"
        )
        self.assertEqual(risks, [])


if __name__ == "__main__":
    unittest.main()

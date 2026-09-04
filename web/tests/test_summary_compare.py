import sys
import unittest
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from backend.parsers import parse_document  # noqa: E402
from backend.summary_compare import compare_summary_to_original, is_summary_document  # noqa: E402


class SummaryFulltextCompareTests(unittest.TestCase):
    def _parse(self, filename: str, text: str):
        return parse_document(filename, text.encode("utf-8"))

    def test_summary_upload_order_does_not_matter_and_locations_are_preserved(self) -> None:
        summary = self._parse(
            "创业黑马2026年半年度报告摘要.txt",
            "创业黑马科技集团股份有限公司2026年半年度报告摘要\n"
            "二、公司基本情况\n股票代码 | 300689\n"
            "三、主要会计数据和财务指标\n营业收入（元） | 46,865,344.28 | 70,559,075.39 | -33.58%\n",
        )
        original = self._parse(
            "创业黑马2026年半年度报告.txt",
            "创业黑马科技集团股份有限公司2026年半年度报告\n"
            "二、公司基本情况\n股票代码 | 300688\n"
            "三、主要会计数据和财务指标\n营业收入（元） | 46,865,344.28 | 70,559,075.39 | -33.58%\n",
        )
        self.assertTrue(is_summary_document(summary.filename, summary))
        risks, report = compare_summary_to_original(
            original, summary,
            primary_filename=original.filename,
            comparison_filename=summary.filename,
            primary_document_id="original-id",
            comparison_document_id="summary-id",
        )
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["summaryDocument"], summary.filename)
        self.assertEqual(report["originalDocument"], original.filename)
        self.assertEqual(report["mismatches"], 1)
        risk = risks[0]
        self.assertIn("基本信息不一致", risk["title"])
        self.assertEqual([item["label"] for item in risk["location"]["items"]], ["摘要位置", "原文位置"])
        self.assertEqual(
            [item["documentId"] for item in risk["location"]["items"]],
            ["summary-id", "original-id"],
        )
        self.assertEqual(risk["calculation"]["summaryValue"], "300689")
        self.assertEqual(risk["calculation"]["originalValue"], "300688")

    def test_matching_metrics_and_facts_produce_no_risk(self) -> None:
        body = (
            "创业黑马科技集团股份有限公司2026年半年度报告摘要\n"
            "股票代码 | 300688\n"
            "主要会计数据和财务指标\n"
            "营业收入（元） | 100.00 | 80.00 | 25.00%\n"
        )
        summary = self._parse("2026年半年度报告摘要.txt", body)
        original = self._parse("2026年半年度报告.txt", body.replace("报告摘要", "报告"))
        risks, report = compare_summary_to_original(
            summary, original,
            primary_filename=summary.filename,
            comparison_filename=original.filename,
        )
        self.assertEqual(risks, [])
        self.assertEqual(report["checkedItems"], 2)
        self.assertEqual(report["mismatches"], 0)

    def test_two_non_summary_documents_are_not_compared_as_summary(self) -> None:
        left = self._parse("2026年半年度报告.txt", "2026年半年度报告\n主要会计数据和财务指标\n")
        right = self._parse("2025年半年度报告.txt", "2025年半年度报告\n主要会计数据和财务指标\n")
        risks, report = compare_summary_to_original(
            left, right,
            primary_filename=left.filename,
            comparison_filename=right.filename,
        )
        self.assertEqual(risks, [])
        self.assertEqual(report["status"], "not_summary_pair")


if __name__ == "__main__":
    unittest.main()

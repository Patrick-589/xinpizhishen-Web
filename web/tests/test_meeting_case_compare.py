from __future__ import annotations

import sys
import unittest
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from backend.meeting_case_compare import MeetingCaseComparator, baseline_score
from backend.parsers import parse_document
from backend.services import detect_review_configuration, is_meeting_governance_document


APPROVED_TEXT = """创业黑马科技集团股份有限公司
第四届董事会第二十四次会议决议公告
本公司及董事会全体成员保证信息披露的内容真实、准确、完整，没有虚假记载、误导性陈述或重大遗漏。
一、董事会会议召开情况
1、会议通知于2026年8月23日通过现场口头及通讯方式送达。
2、本次董事会于2026年8月28日在公司会议室召开。
二、董事会会议审议情况
1、审议通过《关于作废部分已授予但尚未归属的限制性股票的议案》
鉴于2024年限制性股票激励计划相关对象不再符合资格，公司拟作废4名激励对象共计74.50万股。
2、审议通过《关于<2026年限制性股票激励计划（草案）>及摘要的议案》
关联董事牛文文、刘义伟、罗鼎回避表决。
表决结果：同意2票，回避3票，0票反对，0票弃权。
本议案尚需提交公司股东会审议。
3、审议通过《关于<2026年限制性股票激励计划考核管理办法>的议案》
关联董事牛文文、刘义伟、罗鼎回避表决。
4、审议通过《关于提请股东会授权董事会办理2026年限制性股票激励计划有关事项的议案》
关联董事牛文文、刘义伟、罗鼎回避表决。
5、审议通过《关于变更经营范围并修订<公司章程>》
本议案尚需提交股东会审议。
6、审议通过《关于召开公司2026年第五次临时股东会的议案》
公司拟于2026年9月15日召开股东会。
"""

DRAFT_TEXT = """创业黑马科技集团股份有限公司
第四届董事会第二十四次会议决议
一、董事会会议召开情况
1、会议通知于2026年8月24日通过现场口头及通讯方式送达。
2、本次董事会于2025年8月28日在公司会议室召开。
二、董事会会议审议情况
审议通过《关于作废部分已授予但尚未归属及预留部分的限制性股票》
根据2024年计划和2025年授权，公司2021年限制性股票激励计划的1名对象离职，拟作废105.84万股。
审议通过《关于向激励对象首次授予限制性股票》
同意确定首次授予日为年月日，并向5名对象授予万股，授予价格为元/股。
审议通过《关于变更经营范围并修订<公司章程>》
本议案尚需提交股东会再议。
"""


class MeetingCaseCompareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.approved = parse_document("正确案例.txt", APPROVED_TEXT.encode("utf-8"))
        self.draft = parse_document("会议决议草稿.txt", DRAFT_TEXT.encode("utf-8"))
        self.baseline = {
            "id": "approved-case-1",
            "title": "第四届董事会第二十四次会议决议公告（已确认正确案例）",
            "source": "证券部确认案例",
            "source_name": "证券部确认案例",
            "version": "已确认正确版本",
            "file_hash": "approved-hash",
            "updated_at": "2026-08-27T00:00:00+00:00",
        }

    def test_approved_file_itself_has_zero_risks(self) -> None:
        risks, summary = MeetingCaseComparator().review(
            self.approved,
            "第四届董事会第二十四次会议决议公告.docx",
            "approved-hash",
            self.baseline,
            self.approved,
        )
        self.assertEqual(risks, [])
        self.assertTrue(summary["exactReference"])
        self.assertEqual(summary["status"], "approved_reference")

    def test_draft_is_compared_with_same_meeting_approved_case(self) -> None:
        risks, summary = MeetingCaseComparator().review(
            self.draft,
            "第四届董事会第二十四次会议决议（草稿）.docx",
            "draft-hash",
            self.baseline,
            self.approved,
        )
        titles = {risk["title"] for risk in risks}
        self.assertTrue(summary["sameMeeting"])
        self.assertIn("会议通知及召开日期与已确认案例不一致", titles)
        self.assertIn("本次会议议案清单与已确认案例不一致", titles)
        self.assertIn("限制性股票作废议案关键事实与已确认案例不一致", titles)
        self.assertIn("限制性股票授予议案存在未填写关键事实", titles)
        self.assertIn("关联董事回避及股东会召集衔接缺失", titles)
        self.assertIn("“提交股东会再议”表述与已确认案例不一致", titles)
        self.assertTrue(all(risk["calculation"]["engine"] == "meeting_case_compare_v1" for risk in risks))
        self.assertTrue(all(risk["source_documents"][0]["document_id"] == "approved-case-1" for risk in risks))
        self.assertTrue(all(
            risk["source_documents"][0]["source_url"]
            == "/api/knowledge/approved-case-1/document"
            for risk in risks
        ))

    def test_baseline_selection_prefers_exact_file_then_same_meeting(self) -> None:
        self.assertEqual(
            baseline_score("任意.docx", self.approved, "approved-hash", self.baseline, self.approved),
            100,
        )
        self.assertEqual(
            baseline_score(
                "第四届董事会第二十四次会议决议（草稿）.docx",
                self.draft,
                "draft-hash",
                self.baseline,
                self.approved,
            ),
            90,
        )

    def test_meeting_documents_use_case_and_rule_pack(self) -> None:
        selected = detect_review_configuration(
            "第四届董事会第二十四次会议决议（草稿）.docx", self.draft,
        )
        self.assertEqual(selected["taskType"], "会议决议与公告审查")
        self.assertEqual(selected["rulePack"], "已确认案例与现行规则包")

    def test_periodic_report_never_uses_meeting_case_review(self) -> None:
        parsed = parse_document(
            "2026年半年度报告.txt",
            "2026年半年度报告\n董事会审议通过，关联董事回避表决。".encode("utf-8"),
        )
        selected = detect_review_configuration("2026年半年度报告.docx", parsed)
        self.assertEqual(selected["taskType"], "定期报告一致性审查")
        self.assertFalse(is_meeting_governance_document("2026年半年度报告.docx"))


if __name__ == "__main__":
    unittest.main()

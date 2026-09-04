from __future__ import annotations

import sys
import unittest
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from backend.parsers import ParsedBlock, ParsedDocument  # noqa: E402
from backend.rule_compare import compare_documents, extract_clauses  # noqa: E402


def document(*blocks: tuple[str, int, str]) -> ParsedDocument:
    return ParsedDocument(
        filename="rule.pdf",
        file_type="pdf",
        page_count=max((page for _, page, _ in blocks), default=1),
        blocks=[
            ParsedBlock(text=text, page=page, section=section, paragraph_index=index)
            for index, (text, page, section) in enumerate(blocks)
        ],
    )


class RuleComparisonTests(unittest.TestCase):
    def test_added_removed_and_modified_clauses_keep_locations(self) -> None:
        old = document(
            ("1.1 旧版适用范围。", 3, "第一章"),
            ("2.1 旧版审批要求。", 8, "第二章"),
            ("3.2 仅旧版条款。", 12, "第三章"),
        )
        new = document(
            ("1.1 新版适用范围，增加创业板主体。", 4, "第一章"),
            ("2.1 旧版审批要求。", 9, "第二章"),
            ("4.1 新增信息披露要求。", 15, "第四章"),
        )

        result = compare_documents(old, new)
        changes = {item["article"]: item for item in result["changes"]}
        self.assertEqual(changes["1.1"]["changeType"], "modified")
        self.assertEqual(changes["1.1"]["oldPage"], 3)
        self.assertEqual(changes["1.1"]["newPage"], 4)
        self.assertEqual(changes["3.2"]["changeType"], "removed")
        self.assertEqual(changes["4.1"]["changeType"], "added")
        self.assertEqual(result["summary"]["added"], 1)
        self.assertEqual(result["summary"]["removed"], 1)
        self.assertEqual(result["summary"]["modified"], 1)
        self.assertTrue(any(part["type"] == "added" for part in changes["1.1"]["diff"]))
        self.assertTrue(any(part["type"] == "removed" for part in changes["1.1"]["diff"]))

    def test_chinese_clause_numbers_are_supported(self) -> None:
        parsed = document(
            ("第一条 本规则适用于上市公司。", 2, "总则"),
            ("第二条 本规则自发布之日起施行。", 3, "总则"),
        )
        clauses = extract_clauses(parsed)
        self.assertEqual([clause.number for clause in clauses], ["第一条", "第二条"])
        result = compare_documents(parsed, document(
            ("第一条 本规则适用于上市公司。", 2, "总则"),
            ("第二条 本规则自修订发布之日起施行。", 5, "总则"),
        ))
        self.assertEqual(result["summary"]["modified"], 1)
        self.assertEqual(result["changes"][0]["articleLabel"], "第二条")

    def test_fallback_compares_unmarked_paragraphs(self) -> None:
        old = document(("第一段旧内容", 1, "正文"), ("第二段内容", 2, "正文"))
        new = document(("第一段新内容", 1, "正文"), ("第二段内容", 2, "正文"))
        result = compare_documents(old, new)
        self.assertEqual(result["summary"]["modified"], 1)
        self.assertEqual(result["changes"][0]["article"], "段落-1")


if __name__ == "__main__":
    unittest.main()

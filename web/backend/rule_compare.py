"""Local, deterministic comparison of versioned regulatory documents.

The exchange PDFs are structured as numbered clauses (for example ``1.1``
and ``2.1.3``), rather than always using the Chinese ``第 X 条`` form.  This
module compares those clauses without an external service and keeps page
locations for both versions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable

from .parsers import ParsedDocument, ParsedBlock, normalize_text


_NUMERIC_CLAUSE = re.compile(
    r"(?m)^[ \t]*(?P<number>\d+(?:\.\d+)+)(?=\D|$)"
)
_CHINESE_CLAUSE = re.compile(
    r"(?m)^[ \t]*(?P<number>第[一二三四五六七八九十百千万零〇0-9]+条)(?=\D|$)"
)
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Clause:
    number: str
    text: str
    page: int | None
    section: str


def _clause_matches(text: str) -> list[re.Match[str]]:
    matches = list(_NUMERIC_CLAUSE.finditer(text))
    matches.extend(_CHINESE_CLAUSE.finditer(text))
    return sorted(matches, key=lambda item: item.start())


def _clean_clause_text(value: str) -> str:
    return _WHITESPACE.sub(" ", normalize_text(value)).strip()


def extract_clauses(document: ParsedDocument) -> list[Clause]:
    """Extract numbered clauses while retaining the first source location."""
    values: dict[str, Clause] = {}
    order: list[str] = []
    current_number: str | None = None
    current_text: list[str] = []
    current_page: int | None = None
    current_section = ""

    def flush() -> None:
        nonlocal current_number, current_text, current_page, current_section
        if not current_number:
            return
        text = _clean_clause_text(" ".join(current_text))
        if not text:
            return
        existing = values.get(current_number)
        if existing:
            # A clause can be split by PDF layout or repeated in an appendix.
            # Keep the first location and append only genuinely new text.
            if text not in existing.text:
                values[current_number] = Clause(
                    existing.number,
                    _clean_clause_text(f"{existing.text} {text}"),
                    existing.page,
                    existing.section or current_section,
                )
        else:
            values[current_number] = Clause(
                current_number, text, current_page, current_section,
            )
            order.append(current_number)

    for block in document.blocks:
        text = str(block.text or "")
        if not text.strip():
            continue
        matches = _clause_matches(text)
        if not matches:
            if current_number:
                current_text.append(text)
            continue
        prefix = text[: matches[0].start()].strip()
        if prefix and current_number:
            current_text.append(prefix)
        for index, match in enumerate(matches):
            flush()
            current_number = match.group("number")
            current_text = [text[match.start(): matches[index + 1].start() if index + 1 < len(matches) else len(text)]]
            current_page = int(block.page) if block.page else None
            current_section = str(block.section or "")
    flush()

    clauses = [values[number] for number in order]
    if clauses:
        return clauses
    return _fallback_line_clauses(document.blocks)


def _fallback_line_clauses(blocks: Iterable[ParsedBlock]) -> list[Clause]:
    """Keep comparison useful for an unusual document without clause markers."""
    values: list[Clause] = []
    for index, block in enumerate(blocks, 1):
        text = _clean_clause_text(block.text)
        if not text:
            continue
        values.append(Clause(
            f"段落-{index}", text, int(block.page) if block.page else None,
            str(block.section or ""),
        ))
    return values


def _diff_segments(old_text: str, new_text: str, limit: int = 12000) -> list[dict[str, str]]:
    """Return a compact word-level diff for the UI's red/green highlights."""
    matcher = SequenceMatcher(None, old_text, new_text, autojunk=False)
    segments: list[dict[str, str]] = []
    consumed = 0
    for opcode, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        old_value = old_text[old_start:old_end]
        new_value = new_text[new_start:new_end]
        if opcode == "equal":
            # Keep context around edits, but avoid repeating a whole unchanged
            # clause when only one sentence changed.
            if len(old_value) > 220:
                old_value = old_value[:100] + " … " + old_value[-100:]
                new_value = old_value
            value = old_value
            kind = "equal"
        elif opcode == "delete":
            value = old_value
            kind = "removed"
        elif opcode == "insert":
            value = new_value
            kind = "added"
        else:
            if old_value:
                segments.append({"type": "removed", "text": old_value})
                consumed += len(old_value)
            value = new_value
            kind = "added"
        if value:
            segments.append({"type": kind, "text": value})
            consumed += len(value)
        if consumed >= limit:
            segments.append({"type": "equal", "text": "（差异文本已压缩显示）"})
            break
    return segments


def compare_documents(old_document: ParsedDocument, new_document: ParsedDocument) -> dict[str, Any]:
    """Compare two parsed rule versions by clause number."""
    old_clauses = extract_clauses(old_document)
    new_clauses = extract_clauses(new_document)
    old_by_number = {clause.number: clause for clause in old_clauses}
    new_by_number = {clause.number: clause for clause in new_clauses}
    ordered_numbers = list(dict.fromkeys([clause.number for clause in new_clauses] + [clause.number for clause in old_clauses]))
    changes: list[dict[str, Any]] = []
    for number in ordered_numbers:
        old_clause = old_by_number.get(number)
        new_clause = new_by_number.get(number)
        if old_clause and new_clause:
            if old_clause.text == new_clause.text:
                continue
            change_type = "modified"
        elif new_clause:
            change_type = "added"
        else:
            change_type = "removed"
        changes.append({
            "article": number,
            "articleLabel": number if number.startswith("第") else f"第{number}条",
            "changeType": change_type,
            "oldText": old_clause.text if old_clause else "",
            "newText": new_clause.text if new_clause else "",
            "oldPage": old_clause.page if old_clause else None,
            "newPage": new_clause.page if new_clause else None,
            "oldSection": old_clause.section if old_clause else "",
            "newSection": new_clause.section if new_clause else "",
            "diff": _diff_segments(
                old_clause.text if old_clause else "",
                new_clause.text if new_clause else "",
            ),
        })
    return {
        "summary": {
            "oldClauses": len(old_clauses),
            "newClauses": len(new_clauses),
            "comparedClauses": len(set(old_by_number) & set(new_by_number)),
            "added": sum(item["changeType"] == "added" for item in changes),
            "removed": sum(item["changeType"] == "removed" for item in changes),
            "modified": sum(item["changeType"] == "modified" for item in changes),
            "unchanged": len(set(old_by_number) & set(new_by_number)) - sum(item["changeType"] == "modified" for item in changes),
        },
        "changes": changes,
    }

from __future__ import annotations

"""Utilities for confirmed financial review cases.

The case corpus is calibration data, not model fine-tuning data.  It keeps the
reviewer's original annotation and anchor while exposing a small, reusable
pattern vocabulary to the deterministic audit engine.
"""

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from ..parsers import WORD_NAMESPACE, normalize_text


W = f"{{{WORD_NAMESPACE}}}"
CASE_SCHEMA_VERSION = 1


def _local_name(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1]


def _element_text(element: Any) -> str:
    values: list[str] = []
    for node in element.iter():
        name = _local_name(node.tag)
        if name == "t":
            values.append(node.text or "")
        elif name == "tab":
            values.append("\t")
        elif name in {"br", "cr"}:
            values.append("\n")
    return normalize_text("".join(values))


def extract_docx_comments(content: bytes, filename: str = "") -> dict[str, Any]:
    """Extract Word comments and the text enclosed by each comment range.

    Word comments are stored separately from the visible document body.  This
    function walks the OOXML document in order, so an anchor remains tied to
    the original paragraph/table text rather than to a flattened copy.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            comments_root = etree.fromstring(archive.read("word/comments.xml"))
            document_root = etree.fromstring(archive.read("word/document.xml"))
    except (KeyError, zipfile.BadZipFile, etree.XMLSyntaxError) as error:
        raise ValueError(f"无法读取 DOCX 批注：{filename or '文件'}。") from error

    comments: dict[str, dict[str, Any]] = {}
    for node in comments_root.findall(f"{W}comment"):
        comment_id = str(node.get(f"{W}id") or "")
        if not comment_id:
            continue
        text = _element_text(node)
        comments[comment_id] = {
            "id": comment_id,
            "author": str(node.get(f"{W}author") or ""),
            "date": str(node.get(f"{W}date") or ""),
            "text": text,
            "anchor_text": "",
            "anchor_blocks": [],
        }

    active: dict[str, list[str]] = {}
    blocks: list[str] = []
    body = document_root.find(f".//{W}body")
    if body is not None:
        for node in body.iter():
            name = _local_name(node.tag)
            if name == "commentRangeStart":
                comment_id = str(node.get(f"{W}id") or "")
                if comment_id in comments:
                    active[comment_id] = []
            elif name in {"t", "tab", "br", "cr"}:
                value = _element_text(node)
                if value:
                    for values in active.values():
                        values.append(value)
            elif name == "commentRangeEnd":
                comment_id = str(node.get(f"{W}id") or "")
                values = active.pop(comment_id, None)
                if values is not None and comment_id in comments:
                    anchor = normalize_text("".join(values))
                    comments[comment_id]["anchor_text"] = anchor
                    if anchor:
                        comments[comment_id]["anchor_blocks"] = [anchor]
                        blocks.append(anchor)

    return {
        "schema_version": CASE_SCHEMA_VERSION,
        "filename": filename,
        "comment_count": len(comments),
        "comments": list(comments.values()),
        "anchor_count": len(blocks),
    }


def load_financial_cases(root: Path | None = None) -> list[dict[str, Any]]:
    """Load validated case JSON files from the local knowledge corpus."""
    case_root = root or (Path(__file__).resolve().parents[2] / "knowledge" / "cases")
    if not case_root.is_dir():
        return []
    cases: list[dict[str, Any]] = []
    for path in sorted(case_root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict) or int(payload.get("schema_version", 0)) != CASE_SCHEMA_VERSION:
            continue
        payload.setdefault("case_id", path.stem)
        payload.setdefault("source_file", str(path))
        cases.append(payload)
    return cases


def annotation_reference(case: dict[str, Any], annotation: dict[str, Any]) -> dict[str, Any]:
    """Return the compact citation attached to an audit check/risk."""
    return {
        "case_id": str(case.get("case_id") or ""),
        "title": str(case.get("title") or "已确认财务审阅案例"),
        "source": str(case.get("source") or case.get("annotated_file") or ""),
        "pattern": str(annotation.get("pattern") or ""),
        "annotation": str(annotation.get("text") or ""),
        "anchor_text": str(annotation.get("anchor_text") or ""),
        "validated": bool(case.get("validated", True)),
    }


__all__ = ["CASE_SCHEMA_VERSION", "annotation_reference", "extract_docx_comments", "load_financial_cases"]

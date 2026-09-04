from __future__ import annotations

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from lxml import etree

from .parsers import (
    MAX_TEXT_CHARACTERS,
    OFFICE_RELATIONSHIP_NAMESPACE,
    WORD_NAMESPACE,
    _docx_text,
    _load_alt_chunks,
    normalize_text,
)


RELATIONSHIPS_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
W = f"{{{WORD_NAMESPACE}}}"
R = f"{{{OFFICE_RELATIONSHIP_NAMESPACE}}}"


class AnnotatedDocumentError(ValueError):
    pass


@dataclass
class _Candidate:
    index: int
    text: str
    kind: str
    element: Any
    alt_relationship_id: str = ""
    alt_block_index: int = -1


@dataclass
class _CommentTarget:
    risk: dict[str, Any]
    location: dict[str, Any]
    candidate: _Candidate


def _iter_body_blocks(element: Any):
    supported = {f"{W}p", f"{W}tbl", f"{W}altChunk"}
    for child in list(element):
        if child.tag in supported:
            yield child
        else:
            yield from _iter_body_blocks(child)


def _table_text(table: Any) -> str:
    rows: list[str] = []
    for row in table.findall(f".//{W}tr"):
        cells = [_docx_text(cell).strip() for cell in row.findall(f"./{W}tc")]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _relationship_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    try:
        root = etree.fromstring(archive.read("word/_rels/document.xml.rels"))
    except (KeyError, etree.XMLSyntaxError) as error:
        raise AnnotatedDocumentError("DOCX 缺少有效的正文关系文件。") from error
    targets: dict[str, str] = {}
    for relationship in root.findall(f"{{{RELATIONSHIPS_NAMESPACE}}}Relationship"):
        relationship_id = relationship.get("Id", "")
        target = relationship.get("Target", "")
        relationship_type = relationship.get("Type", "")
        if not relationship_id or not target or not relationship_type.casefold().endswith("/afchunk"):
            continue
        if relationship.get("TargetMode", "").casefold() == "external":
            continue
        targets[relationship_id] = (
            posixpath.normpath(target.lstrip("/"))
            if target.startswith("/")
            else posixpath.normpath(posixpath.join("word", target))
        )
    return targets


def _build_candidates(
    root: Any,
    alt_chunks: dict[str, list[tuple[str, str]]],
) -> list[_Candidate]:
    body = root.find(f".//{W}body")
    if body is None:
        raise AnnotatedDocumentError("DOCX 中没有可批注的正文。")
    candidates: list[_Candidate] = []
    total = 0

    def append(text: str, kind: str, element: Any, relationship_id: str = "", block_index: int = -1) -> bool:
        nonlocal total
        normalized = normalize_text(text)
        if not normalized:
            return True
        remaining = MAX_TEXT_CHARACTERS - total
        if remaining <= 0:
            return False
        normalized = normalized[:remaining]
        candidates.append(_Candidate(
            len(candidates), normalized, kind, element, relationship_id, block_index,
        ))
        total += len(normalized)
        return total < MAX_TEXT_CHARACTERS

    for element in _iter_body_blocks(body):
        if element.tag == f"{W}p":
            if not append(_docx_text(element), "paragraph", element):
                break
        elif element.tag == f"{W}tbl":
            if not append(_table_text(element), "table", element):
                break
        else:
            relationship_id = element.get(f"{R}id", "")
            for block_index, (text, _block_type) in enumerate(alt_chunks.get(relationship_id, [])):
                if not append(text, "altchunk", element, relationship_id, block_index):
                    return candidates
    return candidates


def _compact_text(value: str) -> str:
    value = normalize_text(value).casefold()
    return re.sub(r"[\s|,，。；;：:（）()【】\[\]]+", "", value)


def _candidate_score(target: str, candidate: str) -> float:
    target_compact = _compact_text(target)
    candidate_compact = _compact_text(candidate)
    if not target_compact:
        return 0.0
    if target_compact in candidate_compact or candidate_compact in target_compact:
        shorter = min(len(target_compact), len(candidate_compact))
        longer = max(len(target_compact), len(candidate_compact))
        return 0.8 + (0.2 * shorter / max(longer, 1))
    target_tokens = set(re.findall(r"[\w.%+-]+", target_compact))
    candidate_tokens = set(re.findall(r"[\w.%+-]+", candidate_compact))
    if not target_tokens:
        return 0.0
    return len(target_tokens & candidate_tokens) / len(target_tokens)


def _resolve_candidate(location: dict[str, Any], candidates: list[_Candidate]) -> _Candidate | None:
    try:
        paragraph_index = int(location.get("paragraphIndex"))
    except (TypeError, ValueError):
        paragraph_index = -1
    if 0 <= paragraph_index < len(candidates):
        return candidates[paragraph_index]
    target_text = str(location.get("text") or "")
    scored = sorted(
        ((_candidate_score(target_text, candidate.text), candidate) for candidate in candidates),
        key=lambda item: item[0],
        reverse=True,
    )
    return scored[0][1] if scored and scored[0][0] >= 0.72 else None


def _word_run(text: str) -> Any:
    run = OxmlElement("w:r")
    parts = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for index, part in enumerate(parts):
        if index:
            run.append(OxmlElement("w:br"))
        node = OxmlElement("w:t")
        if part.startswith(" ") or part.endswith(" "):
            node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        node.text = part
        run.append(node)
    return run


def _word_paragraph(text: str, heading: bool = False) -> Any:
    paragraph = OxmlElement("w:p")
    properties = OxmlElement("w:pPr")
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:after"), "0")
    spacing.set(qn("w:line"), "360")
    spacing.set(qn("w:lineRule"), "auto")
    properties.append(spacing)
    if heading:
        style = OxmlElement("w:pStyle")
        style.set(qn("w:val"), "Heading2")
        properties.insert(0, style)
    paragraph.append(properties)
    paragraph.append(_word_run(text))
    return paragraph


def _word_table(text: str) -> tuple[Any, list[Any]]:
    rows = [line for line in text.splitlines() if line.strip()]
    split_rows = [[cell.strip() for cell in line.strip(" |").split("|")] for line in rows]
    width = max((len(row) for row in split_rows), default=1)
    table = OxmlElement("w:tbl")
    properties = OxmlElement("w:tblPr")
    style = OxmlElement("w:tblStyle")
    style.set(qn("w:val"), "TableGrid")
    properties.append(style)
    table.append(properties)
    grid = OxmlElement("w:tblGrid")
    for _ in range(width):
        column = OxmlElement("w:gridCol")
        column.set(qn("w:w"), str(max(900, 9000 // width)))
        grid.append(column)
    table.append(grid)
    anchors: list[Any] = []
    for row_values in split_rows:
        row = OxmlElement("w:tr")
        first_nonempty: Any | None = None
        for value in row_values + ([""] * (width - len(row_values))):
            cell = OxmlElement("w:tc")
            cell_properties = OxmlElement("w:tcPr")
            cell_width = OxmlElement("w:tcW")
            cell_width.set(qn("w:w"), str(max(900, 9000 // width)))
            cell_width.set(qn("w:type"), "dxa")
            cell_properties.append(cell_width)
            cell.append(cell_properties)
            paragraph = _word_paragraph(value)
            cell.append(paragraph)
            row.append(cell)
            if first_nonempty is None and value:
                first_nonempty = paragraph
        table.append(row)
        anchors.append(first_nonempty if first_nonempty is not None else row.find(f".//{W}p"))
    if not anchors:
        paragraph = _word_paragraph("")
        cell = OxmlElement("w:tc")
        cell.append(paragraph)
        row = OxmlElement("w:tr")
        row.append(cell)
        table.append(row)
        anchors.append(paragraph)
    return table, anchors


def _best_table_anchor(table: Any, target_text: str) -> Any | None:
    rows = table.findall(f".//{W}tr")
    if not rows:
        return table.find(f".//{W}p")
    scored: list[tuple[float, Any]] = []
    for row in rows:
        row_text = " | ".join(_docx_text(cell).strip() for cell in row.findall(f"./{W}tc"))
        scored.append((_candidate_score(target_text, row_text), row))
    best_row = max(scored, key=lambda item: item[0])[1]
    for paragraph in best_row.findall(f".//{W}p"):
        if normalize_text(_docx_text(paragraph)):
            return paragraph
    return best_row.find(f".//{W}p")


def _convert_target_alt_chunks(
    targets: list[_CommentTarget],
    alt_chunks: dict[str, list[tuple[str, str]]],
) -> dict[tuple[str, int], Any]:
    relationships = {target.candidate.alt_relationship_id for target in targets if target.candidate.kind == "altchunk"}
    anchors: dict[tuple[str, int], Any] = {}
    elements = {
        target.candidate.alt_relationship_id: target.candidate.element
        for target in targets if target.candidate.kind == "altchunk"
    }
    for relationship_id in relationships:
        alt_element = elements[relationship_id]
        parent = alt_element.getparent()
        if parent is None:
            raise AnnotatedDocumentError("DOCX 嵌入正文位置无效，无法添加批注。")
        insertion_index = parent.index(alt_element)
        for block_index, (text, block_type) in enumerate(alt_chunks.get(relationship_id, [])):
            if block_type == "table":
                replacement, row_anchors = _word_table(text)
                relevant = [
                    target for target in targets
                    if target.candidate.alt_relationship_id == relationship_id
                    and target.candidate.alt_block_index == block_index
                ]
                anchor = row_anchors[0]
                if relevant:
                    matched_anchor = _best_table_anchor(
                        replacement, str(relevant[0].location.get("text") or text),
                    )
                    anchor = matched_anchor if matched_anchor is not None else anchor
            else:
                replacement = _word_paragraph(text, heading=block_type == "heading")
                anchor = replacement
            parent.insert(insertion_index, replacement)
            insertion_index += 1
            anchors[(relationship_id, block_index)] = anchor
        parent.remove(alt_element)
    return anchors


def _basis_label(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    title = str(value.get("title") or value.get("document_name") or value.get("source") or "").strip()
    article = str(value.get("article") or value.get("section") or "").strip()
    return " ".join(part for part in (title, article) if part)


def _comment_text(risks: list[dict[str, Any]]) -> str:
    level_labels = {"high": "高风险", "medium": "中风险", "low": "低风险", "needs_review": "待人工核验"}
    status_labels = {
        "pending": "待复核", "confirmed": "已确认", "false_positive": "误报",
        "needs_material": "补充材料", "resolved": "已完成",
    }
    sections: list[str] = []
    for risk in risks:
        basis = []
        regulation_basis = risk.get("primaryRegulationBasis") or risk.get("primary_regulation_basis")
        if regulation_basis is None:
            regulation_basis = risk.get("regulation_basis", [])
        basis.extend(filter(None, (_basis_label(item) for item in (regulation_basis or []))))
        # Keep Word comments concise: add at most one company rule and one
        # confirmed case after the primary regulation, while the full list
        # remains available in the application report.
        for values in (risk.get("company_basis", []), risk.get("internal_rule_basis", []), risk.get("historical_cases", [])):
            label = next(filter(None, (_basis_label(item) for item in (values or []))), "")
            if label:
                basis.append(label)
        basis = list(dict.fromkeys(basis))[:3]
        basis_text = "；".join(dict.fromkeys(basis)) or "当前知识库未检索到直接依据，请人工进一步确认。"
        sections.append("\n".join((
            f"【{level_labels.get(str(risk.get('level') or risk.get('severity')), '待人工核验')}】{risk.get('title') or '未命名风险'}",
            f"问题说明：{risk.get('description') or risk.get('reason') or '请人工核验。'}",
            f"修改建议：{risk.get('recommendation') or risk.get('suggestion') or '请人工进一步确认。'}",
            f"依据：{basis_text}",
            f"复核状态：{status_labels.get(str(risk.get('status') or 'pending'), str(risk.get('status') or '待复核'))}",
        )))
    return "\n\n--------------------\n\n".join(sections)


def _revision_text(risk: dict[str, Any]) -> str:
    """Return a short, reviewable insertion without replacing unverified text."""
    explicit = (
        risk.get("revision_text")
        or risk.get("suggested_text")
        or risk.get("replacement_text")
    )
    if explicit:
        text = str(explicit).strip()
    else:
        recommendation = str(risk.get("recommendation") or risk.get("suggestion") or "请结合依据核对并修改该处。")
        text = re.split(r"[\r\n。；;]", recommendation, maxsplit=1)[0].strip()
        text = f"AI修订建议：{text}"
    text = re.sub(r"\s+", " ", text).strip()
    return text[:240] or "AI修订建议：请结合依据核对并修改该处。"


def _build_revision(risk: dict[str, Any], revision_id: int) -> Any:
    revision = OxmlElement("w:ins")
    revision.set(qn("w:id"), str(revision_id))
    revision.set(qn("w:author"), "信披智审")
    revision.set(qn("w:date"), datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
    run = _word_run(f"【修订建议】{_revision_text(risk)}")
    run_properties = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "C00000")
    run_properties.append(color)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    run_properties.append(underline)
    run.insert(0, run_properties)
    revision.append(run)
    return revision


def _copy_with_document_xml(source: bytes, document_xml: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as archive, zipfile.ZipFile(output, "w") as destination:
        for item in archive.infolist():
            payload = document_xml if item.filename == "word/document.xml" else archive.read(item.filename)
            destination.writestr(item, payload)
    return output.getvalue()


def _enable_track_revisions(content: bytes) -> bytes:
    """Enable Word's revision UI while preserving every original package part."""
    output = io.BytesIO()
    settings_updated = False
    with zipfile.ZipFile(io.BytesIO(content)) as archive, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as destination:
        for item in archive.infolist():
            payload = archive.read(item.filename)
            if item.filename == "word/settings.xml":
                try:
                    settings = etree.fromstring(payload)
                    if settings.find(f".//{W}trackRevisions") is None:
                        settings.insert(0, etree.Element(f"{W}trackRevisions"))
                    payload = etree.tostring(settings, xml_declaration=True, encoding="UTF-8", standalone=True)
                    settings_updated = True
                except etree.XMLSyntaxError as error:
                    raise AnnotatedDocumentError("Word 设置文件结构无效，未生成修订版。") from error
            destination.writestr(item, payload)
        if not settings_updated:
            settings = etree.Element(f"{W}settings", nsmap={"w": WORD_NAMESPACE})
            settings.append(etree.Element(f"{W}trackRevisions"))
            destination.writestr("word/settings.xml", etree.tostring(settings, xml_declaration=True, encoding="UTF-8", standalone=True))
    return output.getvalue()


def _validate_comments(content: bytes, expected_ids: list[str]) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            comments_root = etree.fromstring(archive.read("word/comments.xml"))
            document_root = etree.fromstring(archive.read("word/document.xml"))
            relationships = etree.fromstring(archive.read("word/_rels/document.xml.rels"))
            content_types = etree.fromstring(archive.read("[Content_Types].xml"))
    except (KeyError, zipfile.BadZipFile, etree.XMLSyntaxError) as error:
        raise AnnotatedDocumentError("批注版 DOCX 结构校验失败。") from error
    comment_ids = [node.get(qn("w:id")) for node in comments_root.findall(f"{W}comment")]
    if any(comment_id not in comment_ids for comment_id in expected_ids):
        raise AnnotatedDocumentError("批注版 DOCX 的批注数量不完整。")
    for comment_id in expected_ids:
        checks = (
            document_root.xpath(f".//w:commentRangeStart[@w:id='{comment_id}']", namespaces={"w": WORD_NAMESPACE}),
            document_root.xpath(f".//w:commentRangeEnd[@w:id='{comment_id}']", namespaces={"w": WORD_NAMESPACE}),
            document_root.xpath(f".//w:commentReference[@w:id='{comment_id}']", namespaces={"w": WORD_NAMESPACE}),
        )
        if not all(checks):
            raise AnnotatedDocumentError(f"批注 {comment_id} 未完整关联到原文。")
    has_relationship = any(
        str(node.get("Type") or "").endswith("/comments")
        for node in relationships.findall(f"{{{RELATIONSHIPS_NAMESPACE}}}Relationship")
    )
    has_content_type = any(
        node.get("PartName") == "/word/comments.xml"
        for node in content_types
    )
    if not has_relationship or not has_content_type:
        raise AnnotatedDocumentError("批注版 DOCX 缺少批注关系或内容类型。")


def _validate_revisions(content: bytes, expected_ids: list[str]) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            settings_root = etree.fromstring(archive.read("word/settings.xml"))
            document_root = etree.fromstring(archive.read("word/document.xml"))
    except (KeyError, zipfile.BadZipFile, etree.XMLSyntaxError) as error:
        raise AnnotatedDocumentError("修订版 DOCX 结构校验失败。") from error
    if settings_root.find(f".//{W}trackRevisions") is None:
        raise AnnotatedDocumentError("修订版 DOCX 未启用 Word 修订追踪。")
    revisions = document_root.findall(f".//{W}ins")
    revision_ids = {node.get(qn("w:id")) for node in revisions}
    if any(identifier not in revision_ids for identifier in expected_ids):
        raise AnnotatedDocumentError("修订版 DOCX 的修订标记数量不完整。")
    expected_set = set(expected_ids)
    for revision in revisions:
        if revision.get(qn("w:id")) not in expected_set:
            continue
        if not revision.get(qn("w:author")) or not revision.get(qn("w:date")):
            raise AnnotatedDocumentError("修订标记缺少作者或时间。")


def create_annotated_docx(source: bytes, filename: str, risks: list[dict[str, Any]]) -> bytes:
    if Path(filename).suffix.casefold() != ".docx":
        raise AnnotatedDocumentError("当前仅支持为 DOCX 原件生成 Word 批注版；PDF 等格式请先转换为 DOCX。")
    active_risks = [risk for risk in risks if str(risk.get("status") or "pending") != "false_positive"]
    if not active_risks:
        raise AnnotatedDocumentError("当前没有需要写入批注版的有效风险。")
    try:
        with zipfile.ZipFile(io.BytesIO(source)) as archive:
            root = etree.fromstring(archive.read("word/document.xml"))
            alt_chunks = _load_alt_chunks(archive)
            _relationship_targets(archive)
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as error:
        raise AnnotatedDocumentError("上传的 DOCX 文件结构无效或已损坏。") from error

    candidates = _build_candidates(root, alt_chunks)
    targets: list[_CommentTarget] = []
    missing: list[str] = []
    for risk in active_risks:
        locations = risk.get("originalLocations") or risk.get("original_locations") or []
        if not locations:
            locations = [{
                "paragraphIndex": risk.get("paragraphIndex", risk.get("paragraph_index")),
                "text": risk.get("sourceText") or risk.get("evidence") or "",
                "label": risk.get("title") or "原文位置",
            }]
        for location in locations:
            if not isinstance(location, dict):
                continue
            candidate = _resolve_candidate(location, candidates)
            if candidate is None:
                missing.append(f"{risk.get('title') or '未命名风险'}：{location.get('label') or '原文位置'}")
                continue
            targets.append(_CommentTarget(risk, location, candidate))
    if missing:
        raise AnnotatedDocumentError("以下风险位置无法回带原文，未生成残缺批注版：" + "；".join(missing))
    if not targets:
        raise AnnotatedDocumentError("风险结果没有可用的原文位置，无法生成批注版。")

    alt_anchors = _convert_target_alt_chunks(targets, alt_chunks)
    anchor_groups: dict[int, tuple[Any, list[dict[str, Any]]]] = {}
    for target in targets:
        candidate = target.candidate
        if candidate.kind == "paragraph":
            anchor = candidate.element
        elif candidate.kind == "table":
            anchor = _best_table_anchor(candidate.element, str(target.location.get("text") or candidate.text))
        else:
            anchor = alt_anchors.get((candidate.alt_relationship_id, candidate.alt_block_index))
        if anchor is None:
            missing.append(f"{target.risk.get('title') or '未命名风险'}：{target.location.get('label') or '原文位置'}")
            continue
        identity = id(anchor)
        if identity not in anchor_groups:
            anchor_groups[identity] = (anchor, [])
        if all(item.get("id") != target.risk.get("id") for item in anchor_groups[identity][1]):
            anchor_groups[identity][1].append(target.risk)
    if missing:
        raise AnnotatedDocumentError("以下风险位置无法回带原文，未生成残缺批注版：" + "；".join(missing))

    bookmark_id = max(
        [int(node.get(qn("w:id"), "0")) for node in root.findall(f".//{W}bookmarkStart") if str(node.get(qn("w:id"), "")).isdigit()]
        or [0]
    ) + 1
    bookmark_groups: dict[str, list[dict[str, Any]]] = {}
    for sequence, (anchor, grouped_risks) in enumerate(anchor_groups.values(), start=1):
        name = f"XZS_AI_COMMENT_{sequence}"
        start = OxmlElement("w:bookmarkStart")
        start.set(qn("w:id"), str(bookmark_id))
        start.set(qn("w:name"), name)
        end = OxmlElement("w:bookmarkEnd")
        end.set(qn("w:id"), str(bookmark_id))
        bookmark_id += 1
        insert_at = 1 if len(anchor) and anchor[0].tag == f"{W}pPr" else 0
        anchor.insert(insert_at, start)
        anchor.append(end)
        bookmark_groups[name] = grouped_risks

    converted = _copy_with_document_xml(
        source,
        etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True),
    )
    document = Document(io.BytesIO(converted))
    comments_added = 0
    new_comment_ids: list[str] = []
    revision_ids: list[str] = []
    existing_revision_ids = [
        int(node.get(qn("w:id")))
        for node in list(document.element.xpath(".//w:ins")) + list(document.element.xpath(".//w:del"))
        if str(node.get(qn("w:id"), "")).isdigit()
    ]
    next_revision_id = max(existing_revision_ids or [0]) + 1
    for bookmark in document.element.xpath(".//w:bookmarkStart"):
        name = bookmark.get(qn("w:name"), "")
        if name not in bookmark_groups:
            continue
        paragraph_element = bookmark.getparent()
        paragraph = Paragraph(paragraph_element, document._body)
        runs = paragraph.runs
        if not runs:
            raise AnnotatedDocumentError(f"批注位置 {name} 没有可关联的原文文字。")
        comment = document.add_comment(
            runs=runs,
            text=_comment_text(bookmark_groups[name]),
            author="信披智审",
            initials="AI",
        )
        new_comment_ids.append(str(comment.comment_id))
        comments_added += 1
        bookmark_end = next(
            (child for child in paragraph_element if child.tag == f"{W}bookmarkEnd"),
            None,
        )
        insert_index = paragraph_element.index(bookmark_end) if bookmark_end is not None else len(paragraph_element)
        for risk in bookmark_groups[name]:
            revision = _build_revision(risk, next_revision_id)
            paragraph_element.insert(insert_index, revision)
            insert_index += 1
            revision_ids.append(str(next_revision_id))
            next_revision_id += 1
    generated_bookmark_ids = {
        bookmark.get(qn("w:id"), "")
        for bookmark in document.element.xpath(".//w:bookmarkStart")
        if bookmark.get(qn("w:name"), "").startswith("XZS_AI_COMMENT_")
    }
    for tag in ("bookmarkStart", "bookmarkEnd"):
        for bookmark in list(document.element.xpath(f".//w:{tag}")):
            if bookmark.get(qn("w:id"), "") in generated_bookmark_ids:
                bookmark.getparent().remove(bookmark)
    if comments_added != len(bookmark_groups):
        raise AnnotatedDocumentError("部分风险原文未成功写入 Word 批注。")

    output = io.BytesIO()
    document.save(output)
    result = _enable_track_revisions(output.getvalue())
    _validate_comments(result, new_comment_ids)
    _validate_revisions(result, revision_ids)
    return result

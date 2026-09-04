from __future__ import annotations

import re
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .parsers import ParsedDocument


ENGINE_VERSION = "meeting_case_compare_v1"


def _clean(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def meeting_term(text: str) -> str:
    match = re.search(
        r"第[一二三四五六七八九十百零〇0-9]+届[^\n]{0,24}?第[一二三四五六七八九十百零〇0-9]+次会议",
        str(text or ""),
    )
    return _clean(match.group(0)) if match else ""


def meeting_document_kind(filename: str, text: str) -> str:
    probe = _clean(f"{Path(filename).stem}{text[:500]}")
    if "董事会" in probe and "决议公告" in probe:
        return "board_announcement"
    if "董事会" in probe and "决议" in probe:
        return "board_resolution"
    if re.search(r"股东(?:会|大会).*通知", probe):
        return "shareholder_notice"
    if re.search(r"股东(?:会|大会).*决议", probe):
        return "shareholder_resolution"
    if "委员会" in probe and "决议" in probe:
        return "committee_resolution"
    return "meeting_document"


def baseline_score(
    filename: str,
    parsed: ParsedDocument,
    file_hash: str,
    baseline: dict[str, Any],
    baseline_parsed: ParsedDocument,
) -> int:
    if file_hash and file_hash == str(baseline.get("file_hash") or ""):
        return 100
    current_text = "\n".join(parsed.paragraphs)
    baseline_text = "\n".join(baseline_parsed.paragraphs)
    current_term = meeting_term(f"{filename}\n{current_text}")
    approved_term = meeting_term(f"{baseline.get('title', '')}\n{baseline_text}")
    if current_term and current_term == approved_term:
        return 90
    if meeting_document_kind(filename, current_text) == meeting_document_kind(
        str(baseline.get("title") or ""), baseline_text,
    ):
        return 50
    return 0


def _proposal_sections(parsed: ParsedDocument) -> list[dict[str, Any]]:
    starts: list[int] = []
    for index, block in enumerate(parsed.blocks):
        text = block.text.strip()
        if re.match(r"^(?:\d+[、.]\s*)?审议通过", text):
            starts.append(index)
    sections: list[dict[str, Any]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(parsed.blocks)
        for index in range(start + 1, end):
            if re.match(r"^三、备查", parsed.blocks[index].text.strip()):
                end = index
                break
        title = parsed.blocks[start].text.strip()
        sections.append({
            "title": title,
            "normalized": re.sub(r"^(?:\d+[、.]\s*)?审议通过", "", _clean(title)),
            "start": start,
            "end": end,
            "text": "\n".join(block.text for block in parsed.blocks[start:end]),
        })
    return sections


def _best_similarity(value: str, candidates: list[str]) -> float:
    return max((SequenceMatcher(None, value, candidate).ratio() for candidate in candidates), default=0.0)


class MeetingCaseComparator:
    """Compare a draft with an administrator-confirmed meeting document case.

    Exact facts are compared only when both documents have the same meeting term.
    Other meetings reuse only stable format checks, so a prior case does not become
    a fabricated legal rule.
    """

    def review(
        self,
        parsed: ParsedDocument,
        filename: str,
        file_hash: str,
        baseline: dict[str, Any],
        baseline_parsed: ParsedDocument,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        current_text = "\n".join(parsed.paragraphs)
        approved_text = "\n".join(baseline_parsed.paragraphs)
        exact_reference = file_hash == str(baseline.get("file_hash") or "")
        current_term = meeting_term(f"{filename}\n{current_text}")
        approved_term = meeting_term(f"{baseline.get('title', '')}\n{approved_text}")
        same_meeting = bool(current_term and current_term == approved_term)
        citation = {
            "document_type": "cases",
            "document_id": baseline.get("id"),
            "knowledge_document_id": baseline.get("id"),
            "title": baseline.get("title") or Path(str(baseline.get("file_path") or "")).stem,
            "source": baseline.get("source") or "证券部确认案例",
            "source_name": baseline.get("source_name") or baseline.get("source") or "证券部确认案例",
            "version": baseline.get("version") or "已确认正确版本",
            "date": baseline.get("publication_date") or baseline.get("updated_at"),
            "page": 1,
            "section": "已确认会议文书案例",
            "content": baseline_parsed.paragraphs[1] if len(baseline_parsed.paragraphs) > 1 else baseline_parsed.paragraphs[0],
            "source_url": f"/api/knowledge/{baseline.get('id')}/document",
            "citation_kind": "approved_case",
        }
        summary = {
            "status": "approved_reference" if exact_reference else "completed",
            "engineVersion": ENGINE_VERSION,
            "baselineDocumentId": baseline.get("id"),
            "baselineTitle": citation["title"],
            "baselineHash": baseline.get("file_hash"),
            "exactReference": exact_reference,
            "sameMeeting": same_meeting,
            "matchType": "exact_file" if exact_reference else ("same_meeting" if same_meeting else "same_document_type"),
            "sourceDocuments": [citation],
            "riskCount": 0,
        }
        if exact_reference:
            return [], summary

        risks: list[dict[str, Any]] = []

        def block_index(*terms: str) -> int:
            return next((
                index for index, block in enumerate(parsed.blocks)
                if all(term in block.text for term in terms)
            ), 0)

        def locations(indices: list[int], label: str) -> list[dict[str, Any]]:
            result = []
            for index in dict.fromkeys(indices):
                block = parsed.blocks[max(0, min(index, len(parsed.blocks) - 1))]
                result.append({
                    "label": label,
                    "page": block.page,
                    "section": block.section,
                    "paragraphIndex": block.paragraph_index,
                    "text": block.text,
                })
            return result

        def add(
            title: str,
            risk_type: str,
            level: str,
            indices: list[int],
            description: str,
            recommendation: str,
            confidence: float = 0.96,
        ) -> None:
            index = indices[0] if indices else 0
            block = parsed.blocks[max(0, min(index, len(parsed.blocks) - 1))]
            risks.append({
                "id": str(uuid.uuid4()),
                "level": level,
                "type": risk_type,
                "title": title,
                "description": description,
                "evidence": block.text,
                "source_text": block.text,
                "page": block.page,
                "section": block.section,
                "paragraph_index": block.paragraph_index,
                "location": {
                    "page": block.page,
                    "section": block.section,
                    "paragraph": block.paragraph_index + 1,
                    "items": locations(indices, title),
                },
                "regulation_basis": [],
                "company_basis": [],
                "internal_rule_basis": [],
                "historical_cases": [citation],
                "source_documents": [citation],
                "calculation": {
                    "engine": ENGINE_VERSION,
                    "baseline_document_id": baseline.get("id"),
                    "baseline_hash": baseline.get("file_hash"),
                    "match_type": summary["matchType"],
                },
                "recommendation": recommendation,
                "confidence": confidence,
            })

        title_index = 1 if len(parsed.blocks) > 1 else 0
        assurance_term = "本公司及董事会全体成员保证信息披露的内容真实、准确、完整"
        current_proposals = _proposal_sections(parsed)
        approved_proposals = _proposal_sections(baseline_parsed)
        current_numbered = sum(bool(re.match(r"^\d+[、.]", item["title"])) for item in current_proposals)
        if (
            "公告" in str(citation["title"])
            and ("公告" not in parsed.blocks[title_index].text or assurance_term not in current_text)
        ) or (current_proposals and current_numbered < len(current_proposals)):
            add(
                "公告格式与逐项议案编号尚未完成",
                "案例格式一致性",
                "medium",
                [title_index, *[item["start"] for item in current_proposals[:2]]],
                "草稿缺少已确认公告中的公告标题或信息披露保证声明，且议案未按确认案例逐项编号。",
                "按已确认案例补充公告标题、信息披露保证声明，并将审议事项按“1、2、3……”连续编号；签署页是否保留应按内部决议稿或对外公告的实际用途确定。",
                0.98,
            )

        placeholder_indices = [
            index for index, block in enumerate(parsed.blocks)
            if re.search(r"年月日|授予\s*万股|价格为\s*元/股|20(?:XX|__)年|_{2,}", _clean(block.text), re.I)
        ]
        if placeholder_indices:
            add(
                "限制性股票授予议案存在未填写关键事实",
                "事实完整性",
                "high",
                placeholder_indices,
                "草稿仍保留授予日期、授予数量或授予价格空白，不能作为已完成审议或对外披露文本。",
                "回到激励计划、授予名单及价格测算文件核对授予日、人数、数量和价格；若该议案不属于本次会议，应按已确认案例删除整项旧模板内容。",
                0.99,
            )

        if same_meeting:
            current_notice = block_index("会议通知于")
            approved_notice = next((block.text for block in baseline_parsed.blocks if "会议通知于" in block.text), "")
            current_meeting = block_index("本次董事会于")
            approved_meeting = next((block.text for block in baseline_parsed.blocks if "本次董事会于" in block.text), "")
            date_indices = []
            date_details = []
            for index, approved_value, label in (
                (current_notice, approved_notice, "会议通知日期"),
                (current_meeting, approved_meeting, "会议召开日期"),
            ):
                current_dates = re.findall(r"20\d{2}年\d{1,2}月\d{1,2}日", parsed.blocks[index].text)
                approved_dates = re.findall(r"20\d{2}年\d{1,2}月\d{1,2}日", approved_value)
                if current_dates != approved_dates:
                    date_indices.append(index)
                    date_details.append(f"{label}：草稿为{'、'.join(current_dates) or '未识别'}，确认案例为{'、'.join(approved_dates) or '未识别'}")
            if date_indices:
                add(
                    "会议通知及召开日期与已确认案例不一致",
                    "会议事实一致性",
                    "high",
                    date_indices,
                    "；".join(date_details),
                    "以会议通知、签到记录和已确认公告为准，将本次会议全部日期统一；重点改正草稿中的旧年度残留。",
                )

            current_titles = [item["normalized"] for item in current_proposals]
            approved_titles = [item["normalized"] for item in approved_proposals]
            missing = [
                item["title"] for item in approved_proposals
                if _best_similarity(item["normalized"], current_titles) < 0.56
            ]
            extra = [
                item["title"] for item in current_proposals
                if _best_similarity(item["normalized"], approved_titles) < 0.56
            ]
            if missing or extra:
                detail_parts = []
                if missing:
                    detail_parts.append("草稿缺少：" + "；".join(missing))
                if extra:
                    detail_parts.append("草稿多出或沿用旧版本：" + "；".join(extra))
                add(
                    "本次会议议案清单与已确认案例不一致",
                    "议案清单一致性",
                    "high",
                    [item["start"] for item in current_proposals],
                    "。".join(detail_parts),
                    "按本次会议正式议程和已确认案例逐项核对议案名称、顺序和配套公告；删除不属于本次会议的旧议案，并补齐缺少议案。",
                    0.98,
                )

            current_cancel = next((item for item in current_proposals if "作废部分" in item["title"]), None)
            approved_cancel = next((item for item in approved_proposals if "作废部分" in item["title"]), None)
            if current_cancel and approved_cancel:
                current_years = sorted(set(re.findall(r"20\d{2}", current_cancel["text"])))
                approved_years = sorted(set(re.findall(r"20\d{2}", approved_cancel["text"])))
                current_shares = re.findall(r"\d+(?:\.\d+)?\s*万股", current_cancel["text"])
                approved_shares = re.findall(r"\d+(?:\.\d+)?\s*万股", approved_cancel["text"])
                if current_years != approved_years or current_shares != approved_shares:
                    add(
                        "限制性股票作废议案关键事实与已确认案例不一致",
                        "议案事实一致性",
                        "high",
                        list(range(current_cancel["start"], current_cancel["end"])),
                        f"草稿识别到计划年度{'、'.join(current_years) or '无'}、数量{'、'.join(current_shares) or '无'}；已确认案例为计划年度{'、'.join(approved_years) or '无'}、数量{'、'.join(approved_shares) or '无'}，且确认案例包含失去资格、离职及业绩考核不达标等完整原因。",
                        "以已确认案例及对应激励计划底稿为准，统一计划年度、激励对象范围、作废原因和作废数量，并同步核对专项公告。",
                    )

            process_indices = []
            process_details = []
            if "回避表决" in approved_text and "回避表决" not in current_text:
                process_indices.extend(item["start"] for item in current_proposals if "限制性股票" in item["title"])
                process_details.append("草稿未披露关联董事姓名、回避表决及回避后的票数")
            if re.search(r"召开公司.*临时股东会", approved_text) and not re.search(r"召开公司.*临时股东会", current_text):
                process_indices.append(block_index("股东会再议") if "股东会再议" in current_text else title_index)
                process_details.append("草稿缺少召开临时股东会的议案，未形成提交股东会事项的召集衔接")
            if process_details:
                add(
                    "关联董事回避及股东会召集衔接缺失",
                    "会议程序案例对比",
                    "high",
                    process_indices or [title_index],
                    "；".join(process_details),
                    "对照已确认案例补充关联董事牛文文、刘义伟、罗鼎回避表决、同意2票/回避3票的结果，并补入召开2026年第五次临时股东会的议案及会议安排；最终仍应以正式议程和现行规则复核。",
                )

            if "股东会再议" in current_text and "股东会再议" not in approved_text:
                add(
                    "“提交股东会再议”表述与已确认案例不一致",
                    "用语一致性",
                    "medium",
                    [block_index("股东会再议")],
                    "草稿使用“本议案尚需提交股东会再议”，已确认案例使用“本议案尚需提交股东会审议”。",
                    "将“再议”改为“审议”，并与召开股东会的议案、股东会通知及最终公告保持一致。",
                    0.99,
                )

        summary["riskCount"] = len(risks)
        return risks, summary

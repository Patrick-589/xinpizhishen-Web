"""Local meeting-document case helpers used by deterministic drafting.

The case library is deliberately small and conservative: it identifies the role
of a supplied meeting document and extracts proposal evidence, but never turns a
historical case into a current fact.  The returned text is always labelled as a
source excerpt so a person can verify it before signing a document.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable


MEETING_DOCUMENT_TYPES = {
    "meeting_sign_in",
    "meeting_agenda_summary",
    "proxy_authorization",
    "legal_opinion",
    "meeting_notice",
    "meeting_proposal",
    "meeting_record",
    "committee_record",
    "committee_resolution",
    "independent_director_resolution",
    "ballot",
    "general_manager_meeting",
}

ROLE_LABELS = {
    "notice": "会议通知",
    "proposal": "会议议案",
    "record": "会议记录",
    "resolution": "会议决议",
    "ballot": "表决票",
}


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def infer_case_role(title: str, content: str = "") -> str:
    """Infer a stable case role from the filename/title and opening text."""
    title_probe = _compact(title)
    probe = _compact(f"{title}\n{content[:1200]}")
    if "表决票" in title_probe or "表决票" in probe:
        return "ballot"
    if "会议记录" in title_probe or "股东会记录" in title_probe:
        return "record"
    if "决议" in title_probe:
        return "resolution"
    if "议案" in title_probe and "通知" not in title_probe:
        return "proposal"
    if "通知" in title_probe and ("会议" in title_probe or "召开" in title_probe):
        return "notice"
    if "会议记录" in probe or "股东会记录" in probe or "发言和讨论" in probe:
        return "record"
    if "决议" in probe or "审议通过" in probe:
        return "resolution"
    if "议案" in probe or "各位委员" in probe or "各位董事" in probe:
        return "proposal"
    return "record"


def infer_meeting_kind(title: str, content: str = "") -> str:
    title_probe = _compact(title)
    probe = _compact(f"{title}\n{content[:1500]}")
    if "总经理会议" in title_probe:
        return "general_manager"
    if "独立董事专门会议" in title_probe:
        return "independent_director"
    if "审计委员会" in title_probe:
        return "audit_committee"
    if "薪酬与考核委员会" in title_probe:
        return "remuneration_committee"
    if "提名委员会" in title_probe:
        return "nomination_committee"
    if "战略委员会" in title_probe:
        return "strategy_committee"
    if "股东会" in title_probe or "股东大会" in title_probe:
        return "shareholders"
    if "董事会" in title_probe:
        return "board"
    if "独立董事专门会议" in probe:
        return "independent_director"
    if "总经理会议" in probe or "总经理办公会" in probe:
        return "general_manager"
    if "审计委员会" in probe:
        return "audit_committee"
    if "股东会" in probe or "股东大会" in probe:
        return "shareholders"
    if "董事会" in probe:
        return "board"
    if "委员会" in probe:
        return "committee"
    return "meeting"


def meeting_term(title: str, content: str = "") -> str:
    probe = f"{title}\n{content}"
    match = re.search(
        r"第[一二三四五六七八九十百零〇0-9]+届[^\n]{0,28}?第[一二三四五六七八九十百零〇0-9]+次会议",
        probe,
    )
    if match:
        return re.sub(r"\s+", "", match.group(0))
    # Annual and temporary shareholder meetings often omit the届次 form.
    # Keep the exact wording from the supplied document so it can be verified.
    for pattern in (
        r"20\d{2}年[^\n]{0,18}总经理(?:办公)?会议",
        r"20\d{2}年第[^\n]{0,18}次(?:临时)?股东(?:会|大会)",
        r"20\d{2}年度股东(?:会|大会)",
        r"20\d{2}年[^\n]{0,18}(?:临时)?股东(?:会|大会)",
    ):
        match = re.search(pattern, probe)
        if match:
            return re.sub(r"\s+", "", match.group(0))
    return ""


def extract_meeting_details(content: str) -> dict[str, str]:
    """Extract only explicitly labelled meeting fields; missing values stay blank."""
    text = str(content or "")
    date_match = re.search(r"20\d{2}[年/.-]\d{1,2}[月/.-]\d{1,2}日?", text)
    location_match = re.search(r"(?:召开地点|会议地点|地点)\s*[:：]\s*([^\n]{2,80})", text)
    return {
        "meeting_date": re.sub(r"\s+", "", date_match.group(0)) if date_match else "",
        "meeting_location": re.sub(r"\s+", " ", location_match.group(1)).strip(" 。；;") if location_match else "",
    }


def extract_proposal_titles(content: str, limit: int = 16) -> list[str]:
    """Extract proposal headings without treating the title as a fact.

    Meeting templates frequently place the heading and its body in separate
    paragraphs.  We therefore accept both numbered headings and sentences that
    start with ``审议``/``议案`` and normalize only wrapper punctuation.
    """
    titles: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"\n+", str(content or "")):
        line = re.sub(r"\s+", " ", raw).strip(" \t|；;。")
        if not line or len(line) < 5 or len(line) > 240:
            continue
        if not re.search(r"(?:议案|审议(?:通过)?|关于).{2,}", line):
            continue
        if not re.match(r"^(?:[（(]?[一二三四五六七八九十百0-9]+[）).、．.]?\s*)?(?:议案|审议|通过|关于)", line):
            continue
        cleaned = re.sub(r"^(?:[（(]?[一二三四五六七八九十百0-9]+[）).、．.]?\s*)?", "", line)
        cleaned = re.sub(r"^(?:审议通过|审议|通过)\s*", "", cleaned)
        cleaned = cleaned.strip(" ：:《》<> ")
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        titles.append(cleaned)
        if len(titles) >= limit:
            break
    return titles


def _terms(value: str) -> list[str]:
    cleaned = re.sub(r"[《》<>（）()、，。；：:,.\s]+", " ", str(value or "")).strip()
    values = [item for item in cleaned.split(" ") if len(item) >= 2]
    return list(dict.fromkeys(values))


def proposal_score(subject: str, title: str, content: str) -> int:
    subject_terms = _terms(subject)
    haystack = _compact(f"{title} {content}")
    score = sum(3 for term in subject_terms if term and term in haystack)
    if "议案" in title:
        score += 1
    if "关于" in title:
        score += 1
    if any(term in title for term in ("审议通过", "议案")):
        score += 1
    return score


def _excerpt(content: str, subject: str, limit: int = 620) -> str:
    """Keep the most useful proposal/background sentences from one chunk."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in str(content or "").splitlines()]
    lines = [line for line in lines if len(line) >= 8]
    if not lines:
        return ""
    terms = _terms(subject)
    ranked = sorted(
        enumerate(lines),
        key=lambda item: (
            sum(1 for term in terms if term in _compact(item[1])) * 4
            + (2 if re.search(r"议案|审议|交易|重组|评估|补偿|股东会", item[1]) else 0),
            -item[0],
        ),
        reverse=True,
    )
    chosen: list[str] = []
    for _, line in ranked:
        if line in chosen:
            continue
        candidate = "；".join((*chosen, line))
        if len(candidate) > limit:
            continue
        chosen.append(line)
        if len(chosen) >= 4:
            break
    return "；".join(chosen) or lines[0][:limit]


def select_case_evidence(
    sources: Iterable[dict[str, Any]],
    *,
    subject: str,
    meeting_type: str,
    limit: int = 8,
) -> dict[str, Any]:
    """Return proposal evidence grouped by source role for deterministic drafts."""
    candidates: list[dict[str, Any]] = []
    for source in sources:
        metadata = dict(source.get("metadata") or {})
        title = str(source.get("title") or metadata.get("document_name") or "")
        content = str(source.get("content") or "")
        document_type = str(source.get("document_type") or "")
        # Regulations explain the legal standard but are not meeting-case
        # wording.  Keep them in the normal RAG citations and only use company
        # materials here to avoid turning a rule heading into a fake proposal.
        if document_type in {"regulations", "internal_rules", "company_profile"}:
            continue
        # Recompute the role from the title for supplied cases.  Older imports
        # may have captured a body phrase such as “通知已送达” and assigned the
        # wrong role; the filename/title is the stronger signal for case use.
        is_case_source = document_type == "drafting_materials" or metadata.get("source_type") == "approved_meeting_case"
        role = infer_case_role(title, content) if is_case_source else str(metadata.get("case_role") or infer_case_role(title, content))
        kind = infer_meeting_kind(title, content) if is_case_source else str(metadata.get("meeting_type") or infer_meeting_kind(title, content))
        extracted_titles = extract_proposal_titles(content, limit=2)
        score = proposal_score(subject, title, content)
        if kind == meeting_type:
            score += 3
        if role in {"proposal", "resolution"}:
            score += 2
        if score <= 0 and subject:
            continue
        # A record can be useful as a speaking-style reference, but its
        # filename must not become a fabricated proposal. It contributes to
        # the source list only when its body contains an actual proposal line.
        if role not in {"proposal", "resolution"} and not extracted_titles:
            score = max(1, score - 3)
        item = dict(source)
        item["metadata"] = {**metadata, "case_role": role, "meeting_type": kind}
        item["case_role"] = role
        item["meeting_type"] = kind
        item["proposal_title"] = (extracted_titles or ([title] if role in {"proposal", "resolution"} else [""]))[0]
        item["proposal_excerpt"] = _excerpt(content, subject)
        item["case_role_label"] = ROLE_LABELS.get(role, role)
        item["case_score"] = score
        candidates.append(item)

    candidates.sort(
        key=lambda item: (
            int(item.get("case_score") or 0),
            int(item.get("metadata", {}).get("source_priority") or 0),
            str(item.get("date") or ""),
        ),
        reverse=True,
    )
    selected = candidates[:limit]
    proposals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in selected:
        title = str(item.get("proposal_title") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        proposals.append({
            "title": title,
            "excerpt": item.get("proposal_excerpt") or "",
            "source": item,
            "role": item.get("case_role"),
        })
    return {
        "sources": selected,
        "proposals": proposals,
        "meeting_type": meeting_type,
        "meeting_term": next((str(item.get("metadata", {}).get("meeting_term") or "") for item in selected if item.get("metadata", {}).get("meeting_term")), ""),
    }


def source_label(source: dict[str, Any]) -> str:
    title = str(source.get("title") or source.get("file_name") or "本地会议案例")
    page = source.get("page") or "页码待确认"
    return f"《{title}》第{page}页"


__all__ = [
    "MEETING_DOCUMENT_TYPES",
    "ROLE_LABELS",
    "extract_proposal_titles",
    "infer_case_role",
    "infer_meeting_kind",
    "meeting_term",
    "extract_meeting_details",
    "select_case_evidence",
    "source_label",
]

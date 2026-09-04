"""Sync accounting standards and related official material from mof.gov.cn.

The Ministry of Finance page is an official source, but its list pages are
server-rendered static HTML.  This script keeps a small, deterministic crawler
for those pages and sends only downloaded official bodies/attachments through
the existing local knowledge import and embedding pipeline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from server import create_runtime  # noqa: E402
from scripts import sync_official_rule_knowledge as official  # noqa: E402


SITE_ROOT = "https://kjs.mof.gov.cn/"
INDEX_PATH = WEB_ROOT / "data" / "mof-rules.json"
SCRIPT_PATH = WEB_ROOT / "mof-rules-data.js"
MANIFEST_PATH = WEB_ROOT / "runtime" / "imports" / "mof-accounting-knowledge.json"
DOWNLOAD_ROOT = WEB_ROOT / "runtime" / "official-rules" / "mof"
SUPPORTED_ATTACHMENTS = {".pdf", ".doc", ".docx", ".txt", ".md", ".json", ".csv", ".xls", ".xlsx"}
LIST_PAGES = (
    ("policy", "政策发布", "zhengcefabu"),
    ("notice", "工作通知", "gongzuotongzhi"),
    ("interpretation", "政策解读", "zhengcejiedu"),
)
ACCOUNTING_TERMS = (
    "会计准则", "会计准则解释", "企业会计", "政府会计", "会计制度", "会计核算",
    "财务报表", "财务报告", "可持续披露", "会计信息", "会计师事务所职业责任",
    "注册会计师法", "资产评估", "内部控制",
)


def status_for_title(title: str, category_id: str) -> tuple[str, str]:
    if any(term in title for term in ("征求意见", "意见稿", "公开征求")):
        return "draft-consultation", "征求意见稿（非现行规则）"
    if category_id == "interpretation" or any(term in title for term in ("答记者问", "解读", "问答", "应用案例", "分析报告")):
        return "official-interpretation", "官方解读/参考材料"
    return "official-published", "财政部正式发布"


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalize_text(value: str) -> str:
    lines: list[str] = []
    for raw in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[ \t\f\v\u00a0]+", " ", raw).strip()
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def request_bytes(url: str, attempts: int) -> tuple[bytes, str]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
                    "Referer": SITE_ROOT,
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                content = response.read()
                if not content:
                    raise RuntimeError("财政部官网返回空内容。")
                return content, str(response.headers.get_content_type() or "")
        except Exception as error:  # pragma: no cover - network failures vary by host
            last_error = error
            if attempt < attempts:
                time.sleep(attempt * 1.5)
    raise RuntimeError(f"财政部官网下载失败：{last_error}")


class MofListParser(HTMLParser):
    """Extract dated detail links from a category page."""

    def __init__(self, category_id: str, category_name: str, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.category_id = category_id
        self.category_name = category_name
        self.base_url = base_url
        self.current_href = ""
        self.current_text: list[str] = []
        self.records: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attributes = {key.lower(): value or "" for key, value in attrs}
        href = attributes.get("href", "").strip()
        absolute = urllib.parse.urljoin(self.base_url, href)
        path = urllib.parse.urlparse(absolute).path
        if re.search(r"/20\d{4}/t20\d{6}_\d+\.htm$", path, re.I):
            self.current_href = absolute
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.current_href:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self.current_href:
            return
        href = self.current_href
        match = re.search(r"/t(20\d{6})_(\d+)\.htm$", urllib.parse.urlparse(href).path, re.I)
        if match:
            published = f"{match.group(1)[:4]}-{match.group(1)[4:6]}-{match.group(1)[6:]}"
            record_id = match.group(2)
            title = normalize_text("".join(self.current_text))
            if title:
                source_status, status_label = status_for_title(title, self.category_id)
                self.records.append({
                    "id": record_id,
                    "title": title,
                    "summary": "",
                    "url": href,
                    "publishedAt": published,
                    "effectiveAt": None,
                    "ineffectiveAt": None,
                    "fileNumber": "",
                    "source": "财政部会计司",
                    "sourceType": "mof",
                    "sourceStatus": source_status,
                    "statusLabel": status_label,
                    "categoryId": self.category_id,
                    "categoryName": self.category_name,
                })
        self.current_href = ""
        self.current_text = []


class MofArticleParser(HTMLParser):
    """Read the visible article body and official attachments."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.content_depth = 0
        self.skip_depth = 0
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        lower_tag = tag.lower()
        if lower_tag == "meta":
            key = attributes.get("name", "").lower()
            if key in {"pubdate", "contentsource", "keywords"}:
                self.meta[key] = attributes.get("content", "")
        if lower_tag in {"style", "script", "noscript"}:
            self.skip_depth += 1
            return
        if lower_tag == "div":
            classes = set(attributes.get("class", "").split())
            if self.content_depth == 0 and ({"my_doccontent", "trs_editor"} & classes):
                self.content_depth = 1
            elif self.content_depth:
                self.content_depth += 1
        if not self.content_depth or self.skip_depth:
            return
        href = attributes.get("href", "").strip()
        if href:
            self.links.append(href)
        if lower_tag in {"br", "hr"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.lower()
        if lower_tag in {"style", "script", "noscript"}:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if not self.content_depth or self.skip_depth:
            return
        if lower_tag in {"p", "li", "tr", "table", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.text_parts.append("\n")
        if lower_tag == "div":
            self.content_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.content_depth and not self.skip_depth and data:
            self.text_parts.append(data)

    def result(self, page_url: str) -> tuple[str, list[str], dict[str, str]]:
        links: list[str] = []
        seen: set[str] = set()
        for href in self.links:
            absolute = urllib.parse.urljoin(page_url, href)
            suffix = Path(urllib.parse.urlparse(absolute).path).suffix.lower()
            if suffix not in SUPPORTED_ATTACHMENTS or absolute in seen:
                continue
            seen.add(absolute)
            links.append(absolute)
        return normalize_text("".join(self.text_parts)), links, self.meta


def parse_list(content: bytes, category_id: str, category_name: str, base_url: str) -> list[dict[str, Any]]:
    parser = MofListParser(category_id, category_name, base_url)
    parser.feed(content.decode("utf-8", errors="replace"))
    return parser.records


def parse_article(content: bytes, page_url: str) -> tuple[str, list[str], dict[str, str]]:
    parser = MofArticleParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    return parser.result(page_url)


def relevant(record: dict[str, Any]) -> bool:
    title = str(record.get("title") or "")
    return any(term in title for term in ACCOUNTING_TERMS)


def source_index(records: list[dict[str, Any]]) -> dict[str, Any]:
    selected = []
    for record in records:
        if not relevant(record):
            continue
        selected.append({
            **record,
            "categories": [{
                "id": f"mof:{record.get('categoryId')}",
                "name": record.get("categoryName"),
                "group": "财政部会计司",
            }],
            "reviewScopes": ["financial-accounting", "periodic-report"],
        })
    categories: list[dict[str, Any]] = []
    for category_id, category_name, _ in LIST_PAGES:
        count = sum(1 for record in selected if record.get("categoryId") == category_id)
        categories.append({
            "id": f"mof:{category_id}",
            "group": "财政部会计司",
            "name": category_name,
            "count": count,
            "sourceType": "mof",
        })
    return {
        "generatedAt": utc_now(),
        "sourceUrl": SITE_ROOT,
        "note": "财政部会计司官方栏目中与企业会计、财务报告和会计制度相关的公开正文索引；详情正文由本地同步并建立 RAG 向量。",
        "categories": categories,
        "records": selected,
        "totalDiscovered": len(records),
    }


def write_script(payload: dict[str, Any]) -> None:
    SCRIPT_PATH.write_text(
        "window.MOF_RULES_DATA = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def base_metadata(record: dict[str, Any], source_url: str, title: str | None = None) -> dict[str, Any]:
    return {
        "document_type": "regulations",
        "title": title or record.get("title"),
        "source": "财政部会计司",
        "source_name": "财政部会计司",
        "source_url": source_url,
        "date": record.get("publishedAt"),
        "effective_date": record.get("effectiveAt"),
        "expiry_date": record.get("ineffectiveAt"),
        "version": record.get("statusLabel") or "财政部官方披露版本",
        "source_type": "official_mof",
        "review_scopes": ["financial-accounting", "periodic-report"],
    }


def store_download(url: str, content: bytes, source_id: str) -> Path:
    parsed = urllib.parse.urlparse(url)
    filename = official.safe_name(urllib.parse.unquote(Path(parsed.path).name)) or f"{source_id}.bin"
    digest = hashlib.sha256(content).hexdigest()
    destination = DOWNLOAD_ROOT / digest[:2] / f"{source_id}_{filename}"
    if not destination.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f"{destination.name}.{os.getpid()}.tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
    return destination


def import_record(record: dict[str, Any], platform: Any, database: Any, admin: dict[str, Any], attempts: int) -> list[dict[str, Any]]:
    record_id = str(record.get("id") or "")
    page_url = str(record.get("url") or "")
    raw = b""
    body = ""
    attachments: list[str] = []
    meta: dict[str, str] = {}
    # The site occasionally returns a short gateway page with HTTP 200 while
    # the article is still available.  Retry at the article level and only
    # continue once the expected article container has been parsed.
    for attempt in range(max(2, attempts)):
        raw, _ = request_bytes(page_url, attempts)
        body, attachments, meta = parse_article(raw, page_url)
        if body:
            break
        if attempt + 1 < max(2, attempts):
            time.sleep((attempt + 1) * 2)
    if meta.get("pubdate"):
        record["publishedAt"] = meta["pubdate"][:10].replace("/", "-")
    if not body:
        raise RuntimeError(f"财政部详情页未提取到正文（下载 {len(raw)} 字节：{page_url}）。")
    documents: list[dict[str, Any]] = []
    documents.append(official.import_with_recovery(
        platform, database, admin, f"mof_{record_id}_正文.txt", body.encode("utf-8"),
        base_metadata(record, page_url),
    ))
    for attachment_url in attachments:
        try:
            attachment, _ = request_bytes(attachment_url, attempts)
            destination = store_download(attachment_url, attachment, record_id)
            metadata = base_metadata(record, attachment_url, f"{record.get('title')}（附件：{destination.stem}）")
            documents.append(official.import_with_recovery(
                platform, database, admin, official.parser_filename(destination.name, attachment), attachment, metadata,
            ))
        except Exception as error:
            print(f"附件跳过 {record_id} {attachment_url}: {error}", file=sys.stderr)
    return documents


def active_documents(database: Any, state: dict[str, Any]) -> bool:
    documents = state.get("documents") or []
    if not documents:
        return False
    for item in documents:
        row = database.fetch_one(
            """SELECT k.status,(SELECT COUNT(*) FROM chunks c WHERE c.knowledge_document_id=k.id AND c.embedding_status='ready') AS chunks
               FROM knowledge_documents k WHERE k.id=?""",
            (item.get("knowledgeDocumentId"),),
        )
        if not row or row.get("status") != "active" or int(row.get("chunks") or 0) <= 0:
            return False
    return True


def update_document_status(database: Any, state: dict[str, Any], record: dict[str, Any]) -> None:
    version = str(record.get("statusLabel") or "财政部官方披露版本")
    for item in state.get("documents") or []:
        document_id = item.get("knowledgeDocumentId")
        if document_id:
            database.execute(
                "UPDATE knowledge_documents SET version=?,source_type=?,source_name=? WHERE id=?",
                (version, "official_mof", "财政部会计司", document_id),
            )


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="同步财政部会计司官方规则正文到本地 RAG")
    parser.add_argument("--all", action="store_true", help="导入全部发现的栏目内容；默认仅导入会计/财务相关内容")
    parser.add_argument("--ids", default="", help="逗号分隔的财政部详情 ID")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.1)
    parser.add_argument("--index-only", action="store_true", help="只更新财政部规则索引，不下载正文")
    parser.add_argument("--use-index", action="store_true", help="使用已有本地索引导入，跳过栏目重新抓取")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()

    discovered: list[dict[str, Any]] = []
    if args.use_index and INDEX_PATH.is_file():
        existing = official.read_json(INDEX_PATH, {})
        discovered = list(existing.get("records") or []) if isinstance(existing, dict) else []
        # The generated index is intentionally scoped to relevant accounting
        # items, so --all cannot widen an index-only import.
    else:
        for category_id, category_name, path in LIST_PAGES:
            first_url = urllib.parse.urljoin(SITE_ROOT, f"{path}/")
            raw, _ = request_bytes(first_url, args.attempts)
            discovered.extend(parse_list(raw, category_id, category_name, first_url))
            # Static pages expose index_1.htm ... index_36.htm.  Stop when a page
            # has no matching links so a future site redesign remains bounded.
            for page in range(1, 100):
                page_url = urllib.parse.urljoin(first_url, f"index_{page}.htm")
                try:
                    page_raw, _ = request_bytes(page_url, args.attempts)
                except RuntimeError:
                    break
                page_records = parse_list(page_raw, category_id, category_name, page_url)
                if not page_records:
                    break
                discovered.extend(page_records)

    unique: dict[str, dict[str, Any]] = {}
    for record in discovered:
        unique[str(record["id"])] = record
    all_records = sorted(unique.values(), key=lambda item: (str(item.get("publishedAt") or ""), str(item.get("id") or "")), reverse=True)
    payload = source_index(all_records)
    write_json_atomic(INDEX_PATH, payload)
    write_script(payload)
    if args.index_only:
        print(json.dumps({"discovered": len(all_records), "indexed": len(payload["records"]), "index": str(INDEX_PATH)}, ensure_ascii=False))
        return

    selected = all_records if args.all else [record for record in all_records if relevant(record)]
    requested_ids = {value.strip() for value in args.ids.split(",") if value.strip()}
    if requested_ids:
        selected = [record for record in selected if str(record.get("id")) in requested_ids]
    if args.limit > 0:
        selected = selected[:args.limit]
    if not selected:
        raise SystemExit("没有符合条件的财政部会计资料。")

    settings, database, _, platform, _ = create_runtime()
    admin = database.fetch_one(
        "SELECT id,username,display_name,role FROM users WHERE role='admin' AND active=1 AND deleted_at IS NULL ORDER BY created_at LIMIT 1"
    )
    if not admin:
        raise RuntimeError("没有有效管理员账号，无法记录财政部规则知识库导入审计。")

    manifest_path = args.manifest
    manifest = official.read_json(manifest_path, {"schemaVersion": 1, "records": {}})
    if not isinstance(manifest, dict):
        manifest = {"schemaVersion": 1, "records": {}}
    manifest.setdefault("schemaVersion", 1)
    manifest.setdefault("records", {})
    manifest["sourceGeneratedAt"] = payload.get("generatedAt")
    manifest["updatedAt"] = utc_now()
    manifest["selected"] = len(selected)
    write_json_atomic(manifest_path, manifest)

    imported = skipped = failed = 0
    with platform.vector_store.batch_updates():
        for position, record in enumerate(selected, start=1):
            record_id = str(record.get("id") or "")
            state = manifest["records"].setdefault(record_id, {})
            if state.get("status") == "imported" and active_documents(database, state):
                update_document_status(database, state, record)
                skipped += 1
                print(f"[{position}/{len(selected)}] EXISTS mof:{record_id} {record.get('title')}")
                continue
            if state.get("status") == "failed" and not args.retry_failed:
                skipped += 1
                print(f"[{position}/{len(selected)}] HOLD mof:{record_id} 失败记录需 --retry-failed")
                continue
            state.update({"source": "mof", "ruleId": record_id, "title": record.get("title"), "sourceUrl": record.get("url"), "status": "processing", "attemptedAt": utc_now(), "error": ""})
            write_json_atomic(manifest_path, manifest)
            try:
                documents = import_record(record, platform, database, admin, args.attempts)
                state.update({"status": "imported", "documents": documents, "updatedAt": utc_now(), "error": ""})
                update_document_status(database, state, record)
                imported += 1
                print(f"[{position}/{len(selected)}] OK mof:{record_id} {record.get('title')} ({sum(item['chunks'] for item in documents)} chunks)")
            except Exception as error:
                state.update({"status": "failed", "error": str(error), "updatedAt": utc_now()})
                failed += 1
                print(f"[{position}/{len(selected)}] FAIL mof:{record_id} {error}", file=sys.stderr)
            finally:
                manifest["updatedAt"] = utc_now()
                write_json_atomic(manifest_path, manifest)
                if args.delay > 0:
                    time.sleep(args.delay)

    print(json.dumps({"discovered": len(all_records), "selected": len(selected), "imported": imported, "skipped": skipped, "failed": failed, "manifest": str(manifest_path), "database": str(settings.database_path)}, ensure_ascii=False))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

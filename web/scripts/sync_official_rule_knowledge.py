from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from server import create_runtime  # noqa: E402


SZSE_INDEX_PATH = WEB_ROOT / "data" / "szse-rules.json"
SZSE_SCRIPT_PATH = WEB_ROOT / "rules-data.js"
CSRC_INDEX_PATH = WEB_ROOT / "data" / "csrc-rules.json"
DEFAULT_MANIFEST = WEB_ROOT / "runtime" / "imports" / "official-rule-knowledge.json"
DOWNLOAD_ROOT = WEB_ROOT / "runtime" / "official-rules" / "all"
SUPPORTED_ATTACHMENTS = {".pdf", ".doc", ".docx", ".txt", ".md", ".json", ".csv"}
SZSE_OFFICIAL_ATTACHMENT_FALLBACKS = {
    # The SZSE attachment currently returns HTTP 200 with an empty body. The
    # CSRC publication page retains the same official rule as a readable DOC.
    "555184": {
        "download_url": (
            "https://www.csrc.gov.cn/csrc/c101802/c1004876/1004876/files/"
            "%E5%88%9B%E4%B8%9A%E6%9D%BF%E5%86%8D%E8%9E%8D%E8%B5%84"
            "%E5%8B%9F%E9%9B%86%E8%AF%B4%E6%98%8E%E4%B9%A6%E5%87%86"
            "%E5%88%99.doc.docx"
        ),
        "source_url": "https://www.csrc.gov.cn/csrc/c101802/c1004876/content.shtml",
        "source_name": "中国证券监督管理委员会",
        "filename": "szse_555184.doc",
    },
}


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def read_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return fallback


def read_szse_index() -> dict[str, Any]:
    payload = read_json(SZSE_INDEX_PATH, None)
    if isinstance(payload, dict):
        return payload
    raw = SZSE_SCRIPT_PATH.read_text(encoding="utf-8-sig")
    raw = re.sub(r"^\s*window\.SZSE_RULES_DATA\s*=\s*", "", raw, count=1)
    raw = re.sub(r";\s*$", "", raw)
    return json.loads(raw)


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def safe_name(value: str, limit: int = 110) -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value).strip(" ._")
    return (cleaned or "official-rule")[:limit]


def parser_filename(filename: str, content: bytes) -> str:
    """Correct official attachments whose .doc suffix actually contains DOCX data."""

    if Path(filename).suffix.lower() != ".doc" or not content.startswith(b"PK"):
        return filename
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if "word/document.xml" in archive.namelist():
                return f"{Path(filename).stem}.docx"
    except zipfile.BadZipFile:
        pass
    return filename


def normalize_text(value: str) -> str:
    lines = []
    for raw_line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[ \t\f\v\u00a0]+", " ", raw_line).strip()
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip()


class SzseArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_content = False
        self.content_div_depth = 0
        self.text_parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "div":
            if self.in_content:
                self.content_div_depth += 1
            elif attributes.get("id") == "desContent":
                self.in_content = True
                self.content_div_depth = 1
        if not self.in_content:
            return
        href = attributes.get("href", "").strip()
        if href:
            self.links.append(href)
        if tag.lower() in {"br", "hr"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self.in_content:
            return
        if tag.lower() in {"p", "li", "tr", "table", "section", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.text_parts.append("\n")
        if tag.lower() == "div":
            self.content_div_depth -= 1
            if self.content_div_depth <= 0:
                self.in_content = False
                self.content_div_depth = 0

    def handle_data(self, data: str) -> None:
        if self.in_content and data:
            self.text_parts.append(data)

    def result(self, page_url: str) -> tuple[str, list[str]]:
        attachments: list[str] = []
        seen: set[str] = set()
        for href in self.links:
            absolute = urllib.parse.urljoin(page_url, href)
            suffix = Path(urllib.parse.urlparse(absolute).path).suffix.lower()
            if suffix not in SUPPORTED_ATTACHMENTS or absolute in seen:
                continue
            seen.add(absolute)
            attachments.append(absolute)
        return normalize_text("".join(self.text_parts)), attachments


def parse_szse_article(raw_html: str, page_url: str) -> tuple[str, list[str]]:
    parser = SzseArticleParser()
    parser.feed(raw_html)
    return parser.result(page_url)


def parse_szse_json_detail(raw_json: str, detail_url: str) -> tuple[str, list[str]]:
    """Extract the same official body when a retired HTML route only exposes JSON."""

    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as error:
        raise RuntimeError("深交所官方 JSON 详情无法解析。") from error
    data = payload.get("data") if isinstance(payload, dict) else None
    content = data.get("content") if isinstance(data, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("深交所官方 JSON 详情没有正文。")
    return parse_szse_article(f'<div id="desContent">{content}</div>', detail_url)


def csrc_document_text(record: dict[str, Any]) -> str:
    parts: list[str] = []
    body = normalize_text(str(record.get("body") or ""))
    if body:
        parts.append(body)
    for section in record.get("sections") or []:
        title = normalize_text(str(section.get("title") or ""))
        content = normalize_text(str(section.get("content") or ""))
        if title:
            parts.append(title)
        if content:
            parts.append(content)
    return normalize_text("\n".join(parts))


def request_bytes(url: str, attempts: int) -> tuple[bytes, str]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Xinpizhishen/2.0)",
                    "Referer": "https://www.szse.cn/",
                },
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                content = response.read()
                if not content:
                    raise RuntimeError("官方来源返回空文件。")
                return content, str(response.headers.get_content_type() or "")
        except Exception as error:
            last_error = error
            if attempt < attempts:
                time.sleep(attempt * 1.5)
    raise RuntimeError(f"下载失败：{last_error}")


def request_szse_json_detail(page_url: str, attempts: int) -> tuple[bytes, str, str]:
    """Try both official HTTPS and HTTP JSON routes used by legacy SZSE pages."""

    json_url = re.sub(r"\.html?$", ".json", page_url, flags=re.IGNORECASE)
    candidates = [json_url]
    if json_url.startswith("https://www.szse.cn/"):
        candidates.append("http://www.szse.cn/" + json_url.split("/", 3)[-1])
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            raw, content_type = request_bytes(candidate, attempts)
            return raw, content_type, candidate
        except Exception as error:
            last_error = error
    raise RuntimeError(f"下载失败：{last_error}")


def store_download(url: str, content: bytes, source_id: str) -> Path:
    parsed = urllib.parse.urlparse(url)
    filename = safe_name(urllib.parse.unquote(Path(parsed.path).name))
    if not Path(filename).suffix:
        filename = f"{source_id}.bin"
    digest = hashlib.sha256(content).hexdigest()
    destination = DOWNLOAD_ROOT / digest[:2] / f"{source_id}_{filename}"
    if not destination.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f"{destination.name}.{os.getpid()}.tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
    return destination


def import_with_recovery(
    platform: Any,
    database: Any,
    admin: dict[str, Any],
    filename: str,
    content: bytes,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    result = platform.import_knowledge(filename, content, metadata, admin, "official-rule-sync")
    document = result.get("document") or {}
    if result.get("status") == "skipped" and (
        document.get("status") in {"failed", "inactive", "processing"}
        or int(document.get("chunk_count") or 0) == 0
    ):
        rebuilt = platform.rebuild_knowledge(str(document["id"]), admin, "official-rule-sync")
        document = {**document, "chunks": rebuilt.get("chunks", 0), "status": "active"}
    row = database.fetch_one(
        """SELECT k.id,k.status,k.file_hash,
                  (SELECT COUNT(*) FROM chunks c WHERE c.knowledge_document_id=k.id AND c.embedding_status='ready') AS chunk_count
             FROM knowledge_documents k WHERE k.id=?""",
        (document.get("id"),),
    ) or {}
    if row.get("status") != "active" or int(row.get("chunk_count") or 0) <= 0:
        raise RuntimeError("规则正文未生成有效向量块。")
    return {
        "knowledgeDocumentId": row["id"],
        "chunks": int(row["chunk_count"]),
        "fileHash": row.get("file_hash"),
        "status": result.get("status"),
    }


def record_documents_active(database: Any, record: dict[str, Any]) -> bool:
    documents = record.get("documents") or []
    if not documents:
        return False
    for document in documents:
        row = database.fetch_one(
            """SELECT k.status,
                      (SELECT COUNT(*) FROM chunks c WHERE c.knowledge_document_id=k.id AND c.embedding_status='ready') AS chunk_count
                 FROM knowledge_documents k WHERE k.id=?""",
            (document.get("knowledgeDocumentId"),),
        )
        if not row or row.get("status") != "active" or int(row.get("chunk_count") or 0) <= 0:
            return False
    return True


def base_metadata(record: dict[str, Any], *, source_name: str, source_url: str) -> dict[str, Any]:
    return {
        "document_type": "regulations",
        "title": record.get("title"),
        "source": source_name,
        "source_name": source_name,
        "source_url": source_url,
        "date": record.get("publishedAt"),
        "effective_date": record.get("effectiveAt"),
        "expiry_date": record.get("ineffectiveAt"),
        "version": record.get("statusLabel") or record.get("sourceStatus") or "官方披露版本",
        "source_type": "official",
    }


def import_szse_record(
    record: dict[str, Any], platform: Any, database: Any, admin: dict[str, Any], attempts: int,
) -> list[dict[str, Any]]:
    record_id = str(record.get("id") or "")
    page_url = str(record.get("url") or "")
    suffix = Path(urllib.parse.urlparse(page_url).path).suffix.lower()
    detail_url = page_url
    download_url = page_url
    source_url = page_url
    source_name = "深圳证券交易所"
    parser_name = f"szse_{record_id}{suffix}"
    json_fallback = False
    try:
        raw, content_type = request_bytes(page_url, attempts)
    except RuntimeError:
        official_fallback = SZSE_OFFICIAL_ATTACHMENT_FALLBACKS.get(record_id)
        if official_fallback:
            download_url = str(official_fallback["download_url"])
            source_url = str(official_fallback["source_url"])
            source_name = str(official_fallback["source_name"])
            parser_name = str(official_fallback["filename"])
            raw, content_type = request_bytes(download_url, attempts)
        else:
            if suffix not in {".html", ".htm"}:
                raise
            raw, content_type, detail_url = request_szse_json_detail(page_url, attempts)
            json_fallback = True
    documents: list[dict[str, Any]] = []
    if suffix in SUPPORTED_ATTACHMENTS and "html" not in content_type:
        store_download(download_url, raw, record_id)
        documents.append(import_with_recovery(
            platform, database, admin, parser_filename(parser_name, raw), raw,
            base_metadata(record, source_name=source_name, source_url=source_url),
        ))
        return documents

    decoded = raw.decode("utf-8", errors="replace")
    article_text, attachments = (
        parse_szse_json_detail(decoded, detail_url)
        if json_fallback
        else parse_szse_article(decoded, page_url)
    )
    if not json_fallback and not article_text and not attachments and suffix in {".html", ".htm"}:
        detail_raw, _, detail_url = request_szse_json_detail(page_url, attempts)
        article_text, attachments = parse_szse_json_detail(
            detail_raw.decode("utf-8", errors="replace"),
            detail_url,
        )
    if article_text:
        documents.append(import_with_recovery(
            platform, database, admin, f"szse_{record_id}_正文.txt", article_text.encode("utf-8"),
            base_metadata(record, source_name="深圳证券交易所", source_url=detail_url),
        ))
    for attachment_url in attachments:
        try:
            attachment, _ = request_bytes(attachment_url, attempts)
            destination = store_download(attachment_url, attachment, record_id)
            metadata = base_metadata(record, source_name="深圳证券交易所", source_url=attachment_url)
            metadata["title"] = f"{record.get('title')}（附件：{destination.stem}）"
            documents.append(import_with_recovery(
                platform, database, admin, parser_filename(destination.name, attachment), attachment, metadata,
            ))
        except Exception as error:
            # A withdrawn historical attachment must not discard an otherwise valid official body.
            print(f"附件跳过 {record_id} {attachment_url}: {error}", file=sys.stderr)
    if not documents:
        raise RuntimeError("官方详情页未提取到正文或可解析附件。")
    return documents


def import_csrc_record(
    record: dict[str, Any], platform: Any, database: Any, admin: dict[str, Any], attempts: int,
) -> list[dict[str, Any]]:
    del attempts
    text = csrc_document_text(record)
    if not text:
        raise RuntimeError("证监会索引尚无正文，请先以 CSRC_INCLUDE_FULL_TEXT=1 同步。")
    record_id = str(record.get("id") or "")
    metadata = base_metadata(
        record,
        source_name=str(record.get("source") or "中国证券监督管理委员会"),
        source_url=str(record.get("url") or "https://neris.csrc.gov.cn/falvfagui/"),
    )
    return [import_with_recovery(
        platform, database, admin, f"csrc_{record_id}_正文.txt", text.encode("utf-8"), metadata,
    )]


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="将深交所和证监会官方规则正文同步到本地向量知识库")
    parser.add_argument("--sources", default="szse,csrc", help="逗号分隔：szse,csrc")
    parser.add_argument("--ids", default="", help="逗号分隔的规则 ID；留空表示全部")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.1)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    requested_sources = {value.strip().lower() for value in args.sources.split(",") if value.strip()}
    if not requested_sources or not requested_sources.issubset({"szse", "csrc"}):
        raise SystemExit("sources 仅支持 szse,csrc。")
    requested_ids = {value.strip() for value in args.ids.split(",") if value.strip()}

    selected: list[tuple[str, dict[str, Any]]] = []
    generated_at: dict[str, Any] = {}
    if "szse" in requested_sources:
        payload = read_szse_index()
        generated_at["szse"] = payload.get("generatedAt")
        selected.extend(("szse", record) for record in payload.get("records") or [])
    if "csrc" in requested_sources:
        payload = read_json(CSRC_INDEX_PATH, {})
        generated_at["csrc"] = payload.get("generatedAt")
        selected.extend(("csrc", record) for record in payload.get("records") or [])
    if requested_ids:
        selected = [(source, record) for source, record in selected if str(record.get("id") or "") in requested_ids]
    if args.limit > 0:
        selected = selected[:args.limit]
    if not selected:
        raise SystemExit("没有符合条件的官方规则。")

    settings, database, _, platform, _ = create_runtime()
    admin = database.fetch_one(
        "SELECT id,username,display_name,role FROM users WHERE role='admin' AND active=1 AND deleted_at IS NULL ORDER BY created_at LIMIT 1"
    )
    if not admin:
        raise RuntimeError("没有有效管理员账号，无法记录规则知识库导入审计。")

    manifest = read_json(args.manifest, {"schemaVersion": 1, "records": {}})
    if not isinstance(manifest, dict):
        manifest = {"schemaVersion": 1, "records": {}}
    manifest.setdefault("schemaVersion", 1)
    manifest.setdefault("records", {})
    manifest["sourceGeneratedAt"] = generated_at
    manifest["updatedAt"] = utc_now()
    manifest["selected"] = len(selected)
    write_json_atomic(args.manifest, manifest)

    imported = skipped = failed = 0
    with platform.vector_store.batch_updates():
        for position, (source, record) in enumerate(selected, start=1):
            record_id = str(record.get("id") or "")
            manifest_id = f"{source}:{record_id}"
            state = manifest["records"].setdefault(manifest_id, {})
            if state.get("status") == "imported" and record_documents_active(database, state):
                skipped += 1
                print(f"[{position}/{len(selected)}] EXISTS {manifest_id} {record.get('title')}")
                continue
            if state.get("status") == "failed" and not args.retry_failed:
                skipped += 1
                print(f"[{position}/{len(selected)}] HOLD {manifest_id} 失败记录需 --retry-failed")
                continue

            state.update({
                "source": source,
                "ruleId": record_id,
                "title": record.get("title"),
                "sourceUrl": record.get("url"),
                "status": "processing",
                "attemptedAt": utc_now(),
                "error": "",
            })
            write_json_atomic(args.manifest, manifest)
            try:
                if source == "szse":
                    documents = import_szse_record(record, platform, database, admin, args.attempts)
                else:
                    documents = import_csrc_record(record, platform, database, admin, args.attempts)
                state.update({"status": "imported", "documents": documents, "updatedAt": utc_now(), "error": ""})
                imported += 1
                print(f"[{position}/{len(selected)}] OK {manifest_id} {record.get('title')} ({sum(item['chunks'] for item in documents)} chunks)")
            except Exception as error:
                state.update({"status": "failed", "error": str(error), "updatedAt": utc_now()})
                failed += 1
                print(f"[{position}/{len(selected)}] FAIL {manifest_id} {error}", file=sys.stderr)
            finally:
                manifest["updatedAt"] = utc_now()
                write_json_atomic(args.manifest, manifest)
                if args.delay > 0:
                    time.sleep(args.delay)

    print(json.dumps({
        "selected": len(selected), "imported": imported, "skipped": skipped, "failed": failed,
        "manifest": str(args.manifest), "database": str(settings.database_path),
    }, ensure_ascii=False))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

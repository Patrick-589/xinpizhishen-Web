from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from server import create_runtime  # noqa: E402


INDEX_PATH = WEB_ROOT / "data" / "company-announcements.json"
DEFAULT_MANIFEST = WEB_ROOT / "runtime" / "imports" / "company-announcement-knowledge.json"
DOWNLOAD_ROOT = WEB_ROOT / "runtime" / "cninfo-announcements"


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def read_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return fallback


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def select_announcements(
    announcements: list[dict[str, Any]],
    *,
    ids: set[str],
    categories: set[str],
    year_from: int,
    year_to: int,
    limit: int,
) -> list[dict[str, Any]]:
    selected = []
    for item in announcements:
        item_id = str(item.get("id") or "")
        year = int(item.get("year") or str(item.get("publishedAt") or "0")[:4] or 0)
        if ids and item_id not in ids:
            continue
        if categories and str(item.get("categoryId") or "") not in categories:
            continue
        if year < year_from or year > year_to:
            continue
        if not str(item.get("pdfUrl") or "").startswith("https://static.cninfo.com.cn/"):
            continue
        selected.append(item)
    selected.sort(key=lambda item: (str(item.get("publishedAt") or ""), str(item.get("id") or "")), reverse=True)
    return selected[:limit] if limit > 0 else selected


def download_pdf(url: str, destination: Path, attempts: int) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Xinpizhishen/2.0)",
                    "Referer": "https://www.cninfo.com.cn/",
                },
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                content = response.read()
            if len(content) < 500 or not content.startswith(b"%PDF"):
                raise RuntimeError("下载内容不是有效 PDF")
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".pdf.tmp")
            temporary.write_bytes(content)
            temporary.replace(destination)
            return content
        except Exception as error:
            last_error = error
            if attempt < attempts:
                time.sleep(attempt * 1.5)
    raise RuntimeError(f"下载失败：{last_error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="将创业黑马巨潮公告正文断点同步到共享本地知识库")
    parser.add_argument("--ids", default="", help="逗号分隔的公告 ID；留空按筛选条件同步")
    parser.add_argument("--categories", default="", help="逗号分隔分类，如 periodic,transaction；留空表示全部")
    parser.add_argument("--year-from", type=int, default=2017)
    parser.add_argument("--year-to", type=int, default=datetime.now().year)
    parser.add_argument("--limit", type=int, default=0, help="最多处理数量；0 表示不限制")
    parser.add_argument("--retry-failed", action="store_true", help="重新处理清单中失败的记录")
    parser.add_argument("--delay", type=float, default=0.2, help="公告之间的最小等待秒数")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    if args.year_from > args.year_to:
        raise SystemExit("year-from 不能大于 year-to")

    index = read_json(INDEX_PATH, {})
    announcements = list(index.get("announcements") or [])
    selected = select_announcements(
        announcements,
        ids={item.strip() for item in args.ids.split(",") if item.strip()},
        categories={item.strip() for item in args.categories.split(",") if item.strip()},
        year_from=args.year_from,
        year_to=args.year_to,
        limit=args.limit,
    )
    if not selected:
        raise SystemExit("没有符合条件的公告。")

    settings, database, _, platform, _ = create_runtime()
    admin = database.fetch_one(
        "SELECT id,username,display_name,role FROM users WHERE role='admin' AND active=1 AND deleted_at IS NULL ORDER BY created_at LIMIT 1"
    )
    if not admin:
        raise RuntimeError("没有有效管理员账号，无法记录公告知识库导入审计。")

    manifest = read_json(args.manifest, {"schemaVersion": 1, "records": {}})
    manifest.setdefault("schemaVersion", 1)
    manifest.setdefault("records", {})
    manifest["sourceIndex"] = str(INDEX_PATH)
    manifest["sourceGeneratedAt"] = index.get("generatedAt")
    manifest["updatedAt"] = utc_now()
    manifest["selection"] = {
        "count": len(selected), "ids": args.ids, "categories": args.categories,
        "yearFrom": args.year_from, "yearTo": args.year_to,
    }
    write_json_atomic(args.manifest, manifest)

    succeeded = skipped = failed = 0
    def process_announcement(position: int, announcement: dict[str, Any]) -> None:
        nonlocal succeeded, skipped, failed
        announcement_id = str(announcement["id"])
        record = manifest["records"].setdefault(announcement_id, {})
        existing = database.fetch_one(
            """SELECT k.id,k.title,k.status,k.file_path,k.file_hash,
                      (SELECT COUNT(*) FROM chunks c
                       WHERE c.knowledge_document_id=k.id AND c.embedding_status='ready') AS chunk_count
                 FROM knowledge_documents k
                WHERE k.announcement_id=? AND k.document_type='announcements'
                ORDER BY k.updated_at DESC LIMIT 1""",
            (announcement_id,),
        )
        if existing and existing.get("status") == "active" and int(existing.get("chunk_count") or 0) > 0:
            record.update({
                "status": "imported", "knowledgeDocumentId": existing["id"],
                "fileHash": existing["file_hash"], "localPath": existing["file_path"],
                "chunks": int(existing.get("chunk_count") or 0),
                "updatedAt": utc_now(), "sourceUrl": announcement.get("pdfUrl"),
            })
            write_json_atomic(args.manifest, manifest)
            skipped += 1
            print(f"[{position}/{len(selected)}] EXISTS {announcement_id} {announcement.get('title')}")
            return
        if record.get("status") == "failed" and not args.retry_failed:
            skipped += 1
            print(f"[{position}/{len(selected)}] HOLD {announcement_id} 失败记录需 --retry-failed")
            return

        destination = DOWNLOAD_ROOT / str(announcement.get("year") or "unknown") / f"{announcement_id}.pdf"
        record.update({
            "announcementId": announcement_id,
            "title": announcement.get("title"),
            "publicationDate": announcement.get("publishedAt"),
            "categoryId": announcement.get("categoryId"),
            "sourceUrl": announcement.get("pdfUrl"),
            "status": "downloading",
            "attemptedAt": utc_now(),
        })
        write_json_atomic(args.manifest, manifest)
        try:
            content = destination.read_bytes() if destination.is_file() else download_pdf(
                str(announcement["pdfUrl"]), destination, args.attempts,
            )
            if not content.startswith(b"%PDF"):
                destination.unlink(missing_ok=True)
                content = download_pdf(str(announcement["pdfUrl"]), destination, args.attempts)
            digest = hashlib.sha256(content).hexdigest()
            record.update({"status": "downloaded", "downloadPath": str(destination), "fileHash": digest, "updatedAt": utc_now()})
            write_json_atomic(args.manifest, manifest)

            last_progress = -1

            def embedding_progress(completed: int, total: int, cached: int) -> None:
                nonlocal last_progress
                percent = int(completed / max(1, total) * 100)
                if percent == 100 or percent >= last_progress + 5:
                    last_progress = percent
                    print(
                        f"[{position}/{len(selected)}] EMBED {announcement_id} "
                        f"{completed}/{total} ({percent}%，缓存 {cached})",
                        flush=True,
                    )

            result = platform.import_knowledge(
                f"{announcement_id}_{announcement.get('title')}.pdf",
                content,
                {
                    "title": announcement.get("title"),
                    "document_type": "announcements",
                    "company": "创业黑马科技集团股份有限公司",
                    "source": "巨潮资讯网",
                    "source_url": announcement.get("pdfUrl"),
                    "announcement_id": announcement_id,
                    "date": announcement.get("publishedAt"),
                    "version": "巨潮资讯网披露版本",
                    "source_type": "official",
                    "source_name": "巨潮资讯网",
                },
                admin,
                "cninfo-sync",
                progress_callback=embedding_progress,
            )
            document = result.get("document") or {}
            if result.get("status") == "skipped" and (
                document.get("status") in {"failed", "inactive", "processing"}
                or int(document.get("chunk_count") or 0) == 0
            ):
                rebuilt = platform.rebuild_knowledge(str(document["id"]), admin, "cninfo-sync")
                document = {**document, "chunks": rebuilt.get("chunks", 0)}
            if document.get("id"):
                database.execute(
                    """UPDATE knowledge_documents SET
                           company=COALESCE(NULLIF(company,''),?),
                           source_url=COALESCE(NULLIF(source_url,''),?),
                           announcement_id=COALESCE(NULLIF(announcement_id,''),?),
                           publication_date=COALESCE(NULLIF(publication_date,''),?),
                           source_type=COALESCE(NULLIF(source_type,''),'official'),
                           source_name=COALESCE(NULLIF(source_name,''),'巨潮资讯网'),
                           updated_at=? WHERE id=?""",
                    (
                        "创业黑马科技集团股份有限公司", announcement.get("pdfUrl"), announcement_id,
                        announcement.get("publishedAt"), utc_now(), document["id"],
                    ),
                )
            database_row = database.fetch_one(
                "SELECT id,file_path,file_hash,status FROM knowledge_documents WHERE id=?",
                (document.get("id"),),
            ) or {}
            record.update({
                "status": "imported",
                "knowledgeDocumentId": document.get("id"),
                "chunks": document.get("chunks", 0),
                "pages": document.get("page_count", 0),
                "fileHash": database_row.get("file_hash", digest),
                "localPath": database_row.get("file_path", ""),
                "updatedAt": utc_now(),
                "error": "",
            })
            destination.unlink(missing_ok=True)
            succeeded += 1
            print(f"[{position}/{len(selected)}] OK {announcement_id} {announcement.get('title')} ({record['chunks']} chunks)")
        except Exception as error:
            record.update({"status": "failed", "error": str(error), "updatedAt": utc_now()})
            failed += 1
            print(f"[{position}/{len(selected)}] FAIL {announcement_id} {error}", file=sys.stderr)
        finally:
            manifest["updatedAt"] = utc_now()
            write_json_atomic(args.manifest, manifest)
            if args.delay > 0:
                time.sleep(args.delay)

    with platform.vector_store.batch_updates():
        for position, announcement in enumerate(selected, start=1):
            process_announcement(position, announcement)

    summary = {
        "selected": len(selected), "imported": succeeded, "skipped": skipped, "failed": failed,
        "manifest": str(args.manifest), "database": str(settings.database_path),
    }
    print(json.dumps(summary, ensure_ascii=False))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

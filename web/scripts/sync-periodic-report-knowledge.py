from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any


WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from server import create_runtime  # noqa: E402


RULES: tuple[dict[str, str], ...] = (
    {
        "filename": "深圳证券交易所创业板股票上市规则（2026年修订）.pdf",
        "title": "深圳证券交易所创业板股票上市规则（2026年修订）",
        "download_url": "https://docs.static.szse.cn/www/lawrules/rule/stock/supervision/chinext/W020260424688875101057.pdf",
        "source_url": "https://www.szse.cn/lawrules/rule/stock/supervision/chinext/t20260424_620189.html",
        "date": "2026-04-24",
        "version": "2026年修订",
    },
    {
        "filename": "深圳证券交易所上市公司自律监管指引第2号——创业板上市公司规范运作（2026年修订）.pdf",
        "title": "深圳证券交易所上市公司自律监管指引第2号——创业板上市公司规范运作（2026年修订）",
        "download_url": "https://docs.static.szse.cn/www/lawrules/rule/stock/supervision/chinext/W020260424700512000800.pdf",
        "source_url": "https://www.szse.cn/lawrules/rule/stock/supervision/chinext/t20260424_620195.html",
        "date": "2026-04-24",
        "version": "2026年修订",
    },
    {
        "filename": "深圳证券交易所创业板上市公司自律监管指南第1号——业务办理（2026年修订）.docx",
        "title": "深圳证券交易所创业板上市公司自律监管指南第1号——业务办理（2026年修订）",
        "download_url": "https://docs.static.szse.cn/www/lawrules/service/share/W020260205668091710608.docx",
        "source_url": "https://www.szse.cn/lawrules/service/share/t20260130_618825.html",
        "date": "2026-01-30",
        "version": "2026年修订",
    },
    {
        "filename": "深圳证券交易所创业板上市公司自律监管指南第2号——公告格式（2026年7月修订）.docx",
        "title": "深圳证券交易所创业板上市公司自律监管指南第2号——公告格式（2026年7月修订）",
        "download_url": "https://docs.static.szse.cn/www/lawrules/service/share/W020260703565317987567.docx",
        "source_url": "https://www.szse.cn/lawrules/service/share/t20260703_621506.html",
        "date": "2026-07-03",
        "version": "2026年7月修订",
    },
    {
        "filename": "公开发行证券的公司信息披露内容与格式准则第2号——年度报告的内容与格式.pdf",
        "title": "公开发行证券的公司信息披露内容与格式准则第2号——年度报告的内容与格式",
        "download_url": "https://www.szse.cn/lawrules/csrcrules/notice/P020250519344652102565.pdf",
        "source_url": "https://www.szse.cn/lawrules/csrcrules/notice/P020250519344652102565.pdf",
        "date": "2025-03-28",
        "version": "2025年发布",
    },
    {
        "filename": "公开发行证券的公司信息披露内容与格式准则第3号——半年度报告的内容与格式.pdf",
        "title": "公开发行证券的公司信息披露内容与格式准则第3号——半年度报告的内容与格式",
        "download_url": "https://www.szse.cn/lawrules/csrcrules/notice/P020250519344477160571.pdf",
        "source_url": "https://www.szse.cn/lawrules/csrcrules/notice/P020250519344477160571.pdf",
        "date": "2025-03-28",
        "version": "2025年发布",
    },
    {
        "filename": "公开发行证券的公司信息披露编报规则第15号——财务报告的一般规定（2023年修订）.pdf",
        "title": "公开发行证券的公司信息披露编报规则第15号——财务报告的一般规定（2023年修订）",
        "download_url": "https://www.szse.cn/lawrules/csrcrules/notice/P020240802356168930071.pdf",
        "source_url": "https://www.szse.cn/lawrules/csrcrules/notice/P020240802356168930071.pdf",
        "date": "2023-12-22",
        "version": "2023年修订",
    },
    {
        "filename": "公开发行证券的公司信息披露编报规则第13号——季度报告的内容与格式（2016年修订）.pdf",
        "title": "公开发行证券的公司信息披露编报规则第13号——季度报告的内容与格式（2016年修订）",
        "download_url": "https://www.szse.cn/lawrules/csrcrules/notice/P020180919396121441521.pdf",
        "source_url": "https://www.szse.cn/lawrules/csrcrules/notice/P020180919396121441521.pdf",
        "date": "2016-12-08",
        "version": "2016年修订（官方目录当前收录）",
    },
    {
        "filename": "监管规则适用指引——会计类第1号.docx",
        "title": "监管规则适用指引——会计类第1号",
        "download_url": "https://www.szse.cn/lawrules/csrcrules/guide/P020201118501457915596.docx",
        "source_url": "https://www.szse.cn/lawrules/csrcrules/guide/P020201118501457915596.docx",
        "date": "2020-11-12",
        "version": "官方现行收录版本",
        "authority": "中国证券监督管理委员会",
    },
    {
        "filename": "监管规则适用指引——会计类第2号.pdf",
        "title": "监管规则适用指引——会计类第2号",
        "download_url": "https://www.szse.cn/lawrules/csrcrules/guide/P020220928547505507966.pdf",
        "source_url": "https://www.szse.cn/lawrules/csrcrules/guide/P020220928547505507966.pdf",
        "date": "2021-12-23",
        "version": "官方现行收录版本",
        "authority": "中国证券监督管理委员会",
    },
    {
        "filename": "监管规则适用指引——会计类第3号.pdf",
        "title": "监管规则适用指引——会计类第3号",
        "download_url": "https://www.szse.cn/lawrules/csrcrules/guide/P020230406510977147437.pdf",
        "source_url": "https://www.szse.cn/lawrules/csrcrules/guide/P020230406510977147437.pdf",
        "date": "2023-02-03",
        "version": "官方现行收录版本",
        "authority": "中国证券监督管理委员会",
    },
    {
        "filename": "监管规则适用指引——会计类第4号.pdf",
        "title": "监管规则适用指引——会计类第4号",
        "download_url": "https://www.szse.cn/lawrules/csrcrules/guide/P020240802361881526199.pdf",
        "source_url": "https://www.szse.cn/lawrules/csrcrules/guide/P020240802361881526199.pdf",
        "date": "2024-02-08",
        "version": "官方现行收录版本",
        "authority": "中国证券监督管理委员会",
    },
)


def download(url: str, destination: Path) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Xinpizhishen/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read()
    if len(content) < 1000:
        raise RuntimeError(f"官方文件内容异常：{url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(destination)
    return content


def main() -> None:
    settings, database, _, platform, _ = create_runtime()
    admin = database.fetch_one(
        "SELECT id,username,display_name,role FROM users WHERE role='admin' AND active=1 AND deleted_at IS NULL ORDER BY created_at LIMIT 1"
    )
    if not admin:
        raise RuntimeError("没有有效管理员账号，无法记录规则知识库导入审计。")

    download_root = WEB_ROOT / "runtime" / "official-rules" / "periodic-report"
    results: list[dict[str, Any]] = []
    for rule in RULES:
        destination = download_root / rule["filename"]
        try:
            content = download(rule["download_url"], destination)
            imported = platform.import_knowledge(
                rule["filename"],
                content,
                {
                    "title": rule["title"],
                    "document_type": "regulations",
                    "source": rule.get("authority", "深圳证券交易所"),
                    "source_url": rule["source_url"],
                    "date": rule["date"],
                    "version": rule["version"],
                    "source_type": "official",
                    "source_name": rule.get("authority", "深圳证券交易所"),
                },
                admin,
                "local-rule-sync",
            )
            results.append({
                "title": rule["title"],
                "status": imported["status"],
                "chunks": imported.get("document", {}).get("chunks", 0),
                "source_url": rule["source_url"],
            })
            print(f"{imported['status'].upper():7} {rule['title']}")
        except Exception as error:
            results.append({"title": rule["title"], "status": "failed", "error": str(error)})
            print(f"FAILED  {rule['title']}: {error}", file=sys.stderr)

    report_path = WEB_ROOT / "runtime" / "imports" / "periodic-report-rules.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    failures = [item for item in results if item["status"] == "failed"]
    print(json.dumps({
        "selected": len(results),
        "imported": sum(item["status"] == "success" for item in results),
        "skipped": sum(item["status"] == "skipped" for item in results),
        "failed": len(failures),
        "report": str(report_path),
        "database": str(settings.database_path),
    }, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

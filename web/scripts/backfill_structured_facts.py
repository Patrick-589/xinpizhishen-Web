from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from server import create_runtime  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="从本地已索引 Chunk 回填结构化事实和冲突检测")
    parser.add_argument("--limit", type=int, default=0, help="最多处理知识文档数；0 表示全部")
    parser.add_argument("--shared-only", action="store_true", help="只处理共享知识库")
    args = parser.parse_args()
    _settings, _database, _auth, platform, _bootstrap = create_runtime()
    result = platform.backfill_structured_facts(limit=args.limit, include_private=not args.shared_only)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

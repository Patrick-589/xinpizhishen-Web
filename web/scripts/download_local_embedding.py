from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from backend.config import load_settings  # noqa: E402
from backend.embeddings import LocalEmbeddingProvider  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="下载并验证本地 Embedding 模型")
    parser.add_argument("--model", default="", help="覆盖 LOCAL_EMBEDDING_MODEL")
    parser.add_argument("--model-dir", default="", help="覆盖 LOCAL_EMBEDDING_MODEL_DIR")
    parser.add_argument("--offline-check", action="store_true", help="禁止下载，仅从本地目录加载并计算测试向量")
    args = parser.parse_args()

    settings = load_settings()
    if args.model:
        settings = replace(settings, local_embedding_model=args.model)
    if args.model_dir:
        settings = replace(settings, local_embedding_model_dir=Path(args.model_dir).expanduser().resolve())
    settings = replace(settings, local_embedding_allow_download=not args.offline_check)
    provider = LocalEmbeddingProvider(settings)
    vector = provider.embed_text("上市公司关联交易是否达到审议和信息披露标准")
    print(f"MODEL: {provider.model_name()}")
    print(f"MODEL_PATH: {provider.local_model_path()}")
    print(f"DIMENSION: {len(vector)}")
    print("MODE: OFFLINE_READY")


if __name__ == "__main__":
    main()

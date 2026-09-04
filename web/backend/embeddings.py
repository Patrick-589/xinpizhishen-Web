from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterable

from .config import Settings


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        raise NotImplementedError

    def embed_batch(self, texts: Iterable[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]

    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def dimension(self) -> int:
        raise NotImplementedError

    def local_model_path(self) -> str:
        return ""


class MockEmbeddingProvider(EmbeddingProvider):
    """Small deterministic offline provider used by tests and as an explicit fallback."""

    def __init__(self, dimensions: int = 384):
        self._dimensions = dimensions

    def model_name(self) -> str:
        return "local-hash-ngram-v1"

    def dimension(self) -> int:
        return self._dimensions

    @staticmethod
    def _features(text: str) -> list[str]:
        normalized = re.sub(r"\s+", "", text.lower())
        features: list[str] = []
        for size in (2, 3):
            features.extend(normalized[index:index + size] for index in range(max(0, len(normalized) - size + 1)))
        features.extend(re.findall(r"[a-z0-9_.%-]{2,}", text.lower()))
        return features or [normalized or "empty"]

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for feature in self._features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            vector[value % self._dimensions] += -1.0 if value & 1 else 1.0
        norm = math.sqrt(sum(item * item for item in vector)) or 1.0
        return [item / norm for item in vector]


class LocalEmbeddingProvider(EmbeddingProvider):
    """Sentence Transformers provider that always computes embeddings in this process."""

    def __init__(self, settings: Settings):
        self.model_id = settings.local_embedding_model
        self.model_dir = settings.local_embedding_model_dir.resolve()
        self.allow_download = settings.local_embedding_allow_download
        self.device = settings.local_embedding_device
        self.batch_size = max(1, settings.embedding_batch_size)
        self._model: Any | None = None
        self._dimension = self._read_dimension()
        self._lock = threading.Lock()
        self._encode_lock = threading.Lock()

    def model_name(self) -> str:
        return f"local:{self.model_id}"

    def local_model_path(self) -> str:
        return str(self.model_dir)

    def dimension(self) -> int:
        if self._dimension <= 0:
            self._ensure_model()
        return self._dimension

    def _read_dimension(self) -> int:
        for relative in ("config.json", "1_Pooling/config.json"):
            path = self.model_dir / relative
            if not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for key in ("hidden_size", "word_embedding_dimension"):
                value = payload.get(key)
                if isinstance(value, int) and value > 0:
                    return value
        return 0

    def _snapshot_ready(self) -> bool:
        weight_files = (
            "model.safetensors",
            "pytorch_model.bin",
            "model.safetensors.index.json",
            "pytorch_model.bin.index.json",
        )
        return (
            self.model_dir.is_dir()
            and (self.model_dir / "modules.json").is_file()
            and any((self.model_dir / name).is_file() for name in weight_files)
        )

    def _download_snapshot(self) -> None:
        if not self.allow_download:
            raise EmbeddingError(
                f"本地 Embedding 模型尚未下载：{self.model_dir}。"
                "请联网运行 web/scripts/download_local_embedding.py，完成后可断网使用。"
            )
        try:
            from huggingface_hub import snapshot_download
        except ImportError as error:
            raise EmbeddingError("缺少 huggingface-hub，无法下载本地 Embedding 模型。") from error
        self.model_dir.mkdir(parents=True, exist_ok=True)
        try:
            snapshot_download(
                repo_id=self.model_id,
                local_dir=str(self.model_dir),
                ignore_patterns=["*.onnx", "onnx/*", "openvino/*", "*.h5", "*.ot"],
            )
        except Exception as error:
            raise EmbeddingError(f"本地 Embedding 模型下载失败：{self.model_id}") from error
        if not self._snapshot_ready():
            raise EmbeddingError("模型下载结果不完整，缺少 Sentence Transformers 配置或模型权重。")

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            if not self._snapshot_ready():
                self._download_snapshot()
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as error:
                raise EmbeddingError("缺少 sentence-transformers，无法运行本地 Embedding。") from error
            try:
                self._model = SentenceTransformer(
                    str(self.model_dir),
                    device=self.device,
                    local_files_only=True,
                )
                self._dimension = int(self._model.get_sentence_embedding_dimension())
            except Exception as error:
                raise EmbeddingError(f"无法从本地目录加载 Embedding 模型：{self.model_dir}") from error
            return self._model

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: Iterable[str]) -> list[list[float]]:
        values = [str(value) for value in texts]
        if not values:
            return []
        model = self._ensure_model()
        try:
            with self._encode_lock:
                vectors = model.encode(
                    values,
                    batch_size=self.batch_size,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
        except Exception as error:
            raise EmbeddingError("本地 Embedding 计算失败。") from error
        return [[float(item) for item in vector] for vector in vectors]


def create_embedding_provider(settings: Settings, *, force_local: bool = False) -> EmbeddingProvider:
    """Create an offline-only provider; cloud credentials never affect embedding selection."""

    del force_local
    if settings.local_embedding_provider == "mock":
        return MockEmbeddingProvider()
    return LocalEmbeddingProvider(settings)

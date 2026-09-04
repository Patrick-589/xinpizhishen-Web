from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]


def _load_development_env() -> None:
    """Load local .env files without overriding deployment environment variables."""
    for path in (WEB_ROOT.parent / ".env", WEB_ROOT / ".env"):
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            os.environ.setdefault(key, value)


def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    return Path(value).expanduser().resolve() if value else default.resolve()


@dataclass(frozen=True)
class Settings:
    app_env: str
    ai_mode: str
    database_path: Path
    upload_root: Path
    knowledge_root: Path
    max_upload_bytes: int
    session_hours: int
    bootstrap_admin_username: str
    bootstrap_admin_password: str
    app_secret: str
    aliyun_api_key: str
    aliyun_base_url: str
    aliyun_model: str
    aliyun_chat_path: str
    request_timeout_seconds: int
    embedding_batch_size: int
    vector_backend: str
    database_url: str
    vector_db_url: str
    input_cost_per_million: float
    output_cost_per_million: float
    allow_registration: bool = True
    local_ocr_enabled: bool = True
    ocr_language: str = "zh-Hans-CN"
    ocr_dpi: int = 200
    ocr_max_pages: int = 80
    pdftoppm_path: str = ""
    local_embedding_provider: str = "mock"
    local_embedding_model: str = "BAAI/bge-m3"
    local_embedding_model_dir: Path = WEB_ROOT / "runtime" / "models" / "bge-m3"
    local_embedding_allow_download: bool = False
    local_embedding_device: str = "cpu"
    faiss_index_root: Path = WEB_ROOT / "runtime" / "faiss"
    retrieval_mode: str = "semantic"
    local_llm_base_url: str = "http://127.0.0.1:11434/v1"
    local_llm_model: str = ""
    local_llm_chat_path: str = "/chat/completions"
    fast_review_background_embedding: bool = False

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cloud_configured(self) -> bool:
        return bool(self.aliyun_api_key and self.aliyun_base_url and self.aliyun_model)

def load_settings() -> Settings:
    _load_development_env()
    app_env = os.getenv("APP_ENV", "development").strip().lower() or "development"
    ai_mode = os.getenv("AI_MODE", "local_rag").strip().lower() or "local_rag"
    if ai_mode not in {"cloud", "local_rag", "local_llm"}:
        raise RuntimeError("AI_MODE 仅支持 cloud、local_rag 或 local_llm。")

    vector_backend = os.getenv("VECTOR_BACKEND", "faiss").strip().lower() or "faiss"
    if vector_backend not in {"faiss", "sqlite", "pgvector"}:
        raise RuntimeError("VECTOR_BACKEND 仅支持 faiss、sqlite 或 pgvector。")

    local_embedding_provider = os.getenv("LOCAL_EMBEDDING_PROVIDER", "bge_m3").strip().lower() or "bge_m3"
    if local_embedding_provider not in {"bge_m3", "sentence_transformers", "mock"}:
        raise RuntimeError("LOCAL_EMBEDDING_PROVIDER 仅支持 bge_m3、sentence_transformers 或 mock。")
    retrieval_mode = os.getenv("RETRIEVAL_MODE", "semantic").strip().lower() or "semantic"
    if retrieval_mode not in {"semantic", "keyword", "hybrid"}:
        raise RuntimeError("RETRIEVAL_MODE 仅支持 semantic、keyword 或 hybrid。")

    runtime_root = WEB_ROOT / "runtime"
    settings = Settings(
        app_env=app_env,
        ai_mode=ai_mode,
        database_path=_path_from_env("SQLITE_DATABASE_PATH", runtime_root / "xinpizhishen.db"),
        upload_root=_path_from_env("UPLOAD_ROOT", runtime_root / "uploads"),
        knowledge_root=_path_from_env("KNOWLEDGE_ROOT", WEB_ROOT / "knowledge"),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024))),
        session_hours=int(os.getenv("SESSION_HOURS", "12")),
        bootstrap_admin_username=os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin").strip() or "admin",
        bootstrap_admin_password=os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "").strip(),
        app_secret=os.getenv("APP_SECRET", "").strip(),
        aliyun_api_key=os.getenv("ALIYUN_API_KEY", "").strip(),
        aliyun_base_url=os.getenv("ALIYUN_BASE_URL", "").strip(),
        aliyun_model=os.getenv("ALIYUN_MODEL", "").strip(),
        aliyun_chat_path=os.getenv("ALIYUN_CHAT_PATH", "/chat/completions").strip() or "/chat/completions",
        request_timeout_seconds=int(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "60")),
        embedding_batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "16")),
        vector_backend=vector_backend,
        database_url=os.getenv("DATABASE_URL", "").strip(),
        vector_db_url=os.getenv("VECTOR_DB_URL", "").strip(),
        input_cost_per_million=float(os.getenv("AI_INPUT_COST_PER_MILLION", "2")),
        output_cost_per_million=float(os.getenv("AI_OUTPUT_COST_PER_MILLION", "8")),
        allow_registration=os.getenv("ALLOW_REGISTRATION", "true").strip().lower() in {"1", "true", "yes", "on"},
        local_ocr_enabled=os.getenv("LOCAL_OCR_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
        ocr_language=os.getenv("OCR_LANGUAGE", "zh-Hans-CN").strip() or "zh-Hans-CN",
        ocr_dpi=int(os.getenv("OCR_DPI", "200")),
        ocr_max_pages=int(os.getenv("OCR_MAX_PAGES", "80")),
        pdftoppm_path=os.getenv("PDFTOPPM_PATH", "").strip(),
        local_embedding_provider=local_embedding_provider,
        local_embedding_model=os.getenv("LOCAL_EMBEDDING_MODEL", "BAAI/bge-m3").strip() or "BAAI/bge-m3",
        local_embedding_model_dir=_path_from_env(
            "LOCAL_EMBEDDING_MODEL_DIR", runtime_root / "models" / "bge-m3"
        ),
        local_embedding_allow_download=os.getenv("LOCAL_EMBEDDING_ALLOW_DOWNLOAD", "true").strip().lower()
        in {"1", "true", "yes", "on"},
        local_embedding_device=os.getenv("LOCAL_EMBEDDING_DEVICE", "cpu").strip() or "cpu",
        faiss_index_root=_path_from_env("FAISS_INDEX_ROOT", runtime_root / "faiss"),
        retrieval_mode=retrieval_mode,
        local_llm_base_url=os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434/v1").strip()
        or "http://127.0.0.1:11434/v1",
        local_llm_model=os.getenv("LOCAL_LLM_MODEL", "").strip(),
        local_llm_chat_path=os.getenv("LOCAL_LLM_CHAT_PATH", "/chat/completions").strip()
        or "/chat/completions",
        fast_review_background_embedding=os.getenv(
            "FAST_REVIEW_BACKGROUND_EMBEDDING", "true"
        ).strip().lower() in {"1", "true", "yes", "on"},
    )

    if not 100 <= settings.ocr_dpi <= 400:
        raise RuntimeError("OCR_DPI 必须在 100-400 之间。")
    if not 1 <= settings.ocr_max_pages <= 500:
        raise RuntimeError("OCR_MAX_PAGES 必须在 1-500 之间。")

    if settings.is_production:
        missing = []
        if len(settings.app_secret) < 32:
            missing.append("APP_SECRET（至少 32 个字符）")
        if not settings.bootstrap_admin_password:
            missing.append("BOOTSTRAP_ADMIN_PASSWORD")
        if settings.ai_mode == "cloud" and not settings.cloud_configured:
            missing.append("ALIYUN_API_KEY / ALIYUN_BASE_URL / ALIYUN_MODEL")
        if settings.ai_mode == "local_llm" and not settings.local_llm_model:
            missing.append("LOCAL_LLM_MODEL")
        if settings.vector_backend not in {"faiss", "pgvector", "sqlite"}:
            missing.append("VECTOR_BACKEND=faiss、pgvector 或 sqlite")
        if missing:
            raise RuntimeError("生产配置不完整：" + "；".join(missing))

    return settings

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migration_lock = threading.Lock()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        with self._migration_lock, self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin','securities','legal','leader','user')),
                    active INTEGER NOT NULL DEFAULT 1,
                    deleted_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    ip TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT REFERENCES users(id),
                    task_id TEXT,
                    filename TEXT NOT NULL,
                    safe_filename TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    page_count INTEGER NOT NULL DEFAULT 0,
                    paragraph_count INTEGER NOT NULL DEFAULT 0,
                    character_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(file_hash);
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT REFERENCES users(id),
                    title TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    company TEXT,
                    source TEXT NOT NULL,
                    source_url TEXT,
                    announcement_id TEXT,
                    publication_date TEXT,
                    effective_date TEXT,
                    expiry_date TEXT,
                    version TEXT,
                    file_path TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    page_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    source_type TEXT,
                    source_name TEXT,
                    retrieved_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(file_hash, document_type)
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_type ON knowledge_documents(document_type, status);
                CREATE TABLE IF NOT EXISTS knowledge_categories (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_categories_active
                    ON knowledge_categories(active, sort_order, created_at);
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
                    knowledge_document_id TEXT REFERENCES knowledge_documents(id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    page INTEGER,
                    section TEXT,
                    paragraph INTEGER,
                    chunk_index INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding_status TEXT NOT NULL DEFAULT 'pending',
                    embedding_model TEXT,
                    vector_json TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK(document_id IS NOT NULL OR knowledge_document_id IS NOT NULL)
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_knowledge ON chunks(knowledge_document_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_content_hash ON chunks(content_hash, embedding_model);
                CREATE TABLE IF NOT EXISTS embedding_cache (
                    content_hash TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    vector_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(content_hash, embedding_model)
                );
                CREATE TABLE IF NOT EXISTS analysis_tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    rule_pack TEXT,
                    status TEXT NOT NULL,
                    owner_user_id TEXT REFERENCES users(id),
                    document_id TEXT REFERENCES documents(id),
                    ai_mode TEXT NOT NULL,
                    risk_count INTEGER NOT NULL DEFAULT 0,
                    high_count INTEGER NOT NULL DEFAULT 0,
                    due_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL REFERENCES users(id),
                    filename TEXT NOT NULL,
                    task_name TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    rule_pack TEXT,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    completed_items INTEGER NOT NULL DEFAULT 0,
                    total_items INTEGER NOT NULL DEFAULT 0,
                    task_id TEXT REFERENCES analysis_tasks(id) ON DELETE SET NULL,
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_jobs_owner
                    ON analysis_jobs(owner_user_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS risks (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
                    document_id TEXT REFERENCES documents(id),
                    level TEXT NOT NULL,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    evidence TEXT,
                    source_text TEXT,
                    page INTEGER,
                    section TEXT,
                    paragraph_index INTEGER,
                    location_json TEXT NOT NULL DEFAULT '{}',
                    regulation_basis_json TEXT NOT NULL DEFAULT '[]',
                    company_basis_json TEXT NOT NULL DEFAULT '[]',
                    internal_rule_basis_json TEXT NOT NULL DEFAULT '[]',
                    historical_cases_json TEXT NOT NULL DEFAULT '[]',
                    source_documents_json TEXT NOT NULL DEFAULT '[]',
                    calculation_json TEXT NOT NULL DEFAULT '{}',
                    recommendation TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_risks_task ON risks(task_id, status);
                CREATE TABLE IF NOT EXISTS financial_audit_results (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL UNIQUE REFERENCES analysis_tasks(id) ON DELETE CASCADE,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    owner_user_id TEXT NOT NULL REFERENCES users(id),
                    file_hash TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    checks_json TEXT NOT NULL DEFAULT '[]',
                    facts_json TEXT NOT NULL DEFAULT '[]',
                    tables_json TEXT NOT NULL DEFAULT '[]',
                    period_json TEXT NOT NULL DEFAULT '{}',
                    html_report_path TEXT,
                    docx_report_path TEXT,
                    pdf_report_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_financial_audit_owner
                    ON financial_audit_results(owner_user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_financial_audit_cache
                    ON financial_audit_results(owner_user_id, file_hash, engine_version, status);
                CREATE TABLE IF NOT EXISTS reviews (
                    id TEXT PRIMARY KEY,
                    risk_id TEXT NOT NULL REFERENCES risks(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    action TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    comment TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    task_id TEXT REFERENCES analysis_tasks(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                    content TEXT NOT NULL,
                    citations_json TEXT NOT NULL DEFAULT '[]',
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
                CREATE TABLE IF NOT EXISTS memory_summaries (
                    id TEXT PRIMARY KEY,
                    task_id TEXT REFERENCES analysis_tasks(id) ON DELETE CASCADE,
                    conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    summary TEXT NOT NULL,
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS company_profiles (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT REFERENCES users(id),
                    company TEXT NOT NULL,
                    stock_code TEXT,
                    fact_type TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_value TEXT NOT NULL,
                    source TEXT NOT NULL,
                    effective_date TEXT,
                    version TEXT,
                    last_verified_at TEXT,
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT REFERENCES users(id),
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT,
                    ip TEXT,
                    before_json TEXT NOT NULL DEFAULT '{}',
                    after_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
                CREATE TABLE IF NOT EXISTS usage_records (
                    id TEXT PRIMARY KEY,
                    user_id TEXT REFERENCES users(id),
                    task_id TEXT REFERENCES analysis_tasks(id),
                    environment TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated_cost REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meeting_generation_records (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
                    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    document_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    input_json TEXT NOT NULL DEFAULT '{}',
                    unresolved_json TEXT NOT NULL DEFAULT '[]',
                    source_documents_json TEXT NOT NULL DEFAULT '[]',
                    file_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_meeting_generation_task
                    ON meeting_generation_records(task_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS draft_documents (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    subject TEXT NOT NULL DEFAULT '',
                    input_json TEXT NOT NULL DEFAULT '{}',
                    content TEXT NOT NULL,
                    sections_json TEXT NOT NULL DEFAULT '[]',
                    source_documents_json TEXT NOT NULL DEFAULT '[]',
                    structured_facts_json TEXT NOT NULL DEFAULT '[]',
                    timeline_json TEXT NOT NULL DEFAULT '[]',
                    conflicts_json TEXT NOT NULL DEFAULT '[]',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    file_path TEXT,
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_draft_documents_owner
                    ON draft_documents(owner_user_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS structured_facts (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                    knowledge_document_id TEXT REFERENCES knowledge_documents(id) ON DELETE CASCADE,
                    document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
                    chunk_id TEXT NOT NULL,
                    company TEXT,
                    matter TEXT NOT NULL,
                    fact_type TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_value TEXT NOT NULL,
                    normalized_value TEXT,
                    value_unit TEXT,
                    publication_date TEXT,
                    event_date TEXT,
                    status TEXT,
                    is_current INTEGER NOT NULL DEFAULT 0,
                    file_name TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    page INTEGER,
                    section TEXT,
                    paragraph INTEGER,
                    original_text TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_url TEXT,
                    source_priority INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    extracted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK(knowledge_document_id IS NOT NULL OR document_id IS NOT NULL),
                    UNIQUE(chunk_id,fact_type,fact_key,fact_value,original_text)
                );
                CREATE INDEX IF NOT EXISTS idx_structured_facts_document
                    ON structured_facts(knowledge_document_id,document_id);
                CREATE INDEX IF NOT EXISTS idx_structured_facts_query
                    ON structured_facts(company,matter,fact_type,publication_date DESC,source_priority DESC);
                CREATE INDEX IF NOT EXISTS idx_structured_facts_current
                    ON structured_facts(company,matter,is_current,publication_date DESC);
                CREATE TABLE IF NOT EXISTS structured_fact_conflicts (
                    id TEXT PRIMARY KEY,
                    company TEXT,
                    matter TEXT NOT NULL,
                    fact_type TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    conflict_kind TEXT NOT NULL,
                    values_json TEXT NOT NULL,
                    fact_ids_json TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(company,matter,fact_type,fact_key,conflict_kind)
                );
                CREATE INDEX IF NOT EXISTS idx_structured_fact_conflicts_query
                    ON structured_fact_conflicts(company,matter,updated_at DESC);
                """
            )
            self._ensure_column(connection, "knowledge_documents", "owner_user_id", "TEXT REFERENCES users(id)")
            self._ensure_column(connection, "knowledge_documents", "category_id", "TEXT REFERENCES knowledge_categories(id)")
            self._ensure_column(connection, "company_profiles", "owner_user_id", "TEXT REFERENCES users(id)")
            self._ensure_column(connection, "users", "deleted_at", "TEXT")
            self._ensure_column(connection, "risks", "calculation_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(connection, "draft_documents", "structured_facts_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "draft_documents", "timeline_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "draft_documents", "conflicts_json", "TEXT NOT NULL DEFAULT '[]'")
            self._migrate_company_profile_scope(connection)
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_nocase ON users(username COLLATE NOCASE)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_active ON users(deleted_at,active,created_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_owner ON knowledge_documents(owner_user_id,document_type,status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge_documents(category_id,status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_company_profile_owner ON company_profiles(owner_user_id,fact_type,fact_key)"
            )
            connection.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_company_profile_scoped_fact
                   ON company_profiles(IFNULL(owner_user_id,''),company,fact_type,fact_key,IFNULL(version,''))"""
            )

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @staticmethod
    def _migrate_company_profile_scope(connection: sqlite3.Connection) -> None:
        table = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='company_profiles'"
        ).fetchone()
        schema = str(table[0] if table else "").replace(" ", "").lower()
        if "unique(company,fact_type,fact_key,version)" not in schema:
            return
        connection.executescript(
            """
            CREATE TABLE company_profiles_scoped (
                id TEXT PRIMARY KEY,
                owner_user_id TEXT REFERENCES users(id),
                company TEXT NOT NULL,
                stock_code TEXT,
                fact_type TEXT NOT NULL,
                fact_key TEXT NOT NULL,
                fact_value TEXT NOT NULL,
                source TEXT NOT NULL,
                effective_date TEXT,
                version TEXT,
                last_verified_at TEXT,
                confirmed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO company_profiles_scoped (
                id,owner_user_id,company,stock_code,fact_type,fact_key,fact_value,source,
                effective_date,version,last_verified_at,confirmed,created_at,updated_at
            )
            SELECT id,owner_user_id,company,stock_code,fact_type,fact_key,fact_value,source,
                   effective_date,version,last_verified_at,confirmed,created_at,updated_at
            FROM company_profiles;
            DROP TABLE company_profiles;
            ALTER TABLE company_profiles_scoped RENAME TO company_profiles;
            """
        )

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.connection() as connection:
            connection.execute(sql, tuple(params))

    def executemany(self, sql: str, params: Iterable[Iterable[Any]]) -> None:
        with self.connection() as connection:
            connection.executemany(sql, [tuple(item) for item in params])

    def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

    def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self.connection() as connection:
            return [dict(row) for row in connection.execute(sql, tuple(params)).fetchall()]

    def audit(
        self,
        user_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str | None,
        ip: str | None,
        before: Any = None,
        after: Any = None,
    ) -> None:
        self.execute(
            "INSERT INTO audit_logs (id,user_id,action,resource_type,resource_id,ip,before_json,after_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()), user_id, action, resource_type, resource_id, ip,
                json.dumps(before or {}, ensure_ascii=False),
                json.dumps(after or {}, ensure_ascii=False), utc_now(),
            ),
        )

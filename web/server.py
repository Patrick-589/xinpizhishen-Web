from __future__ import annotations

import argparse
import cgi
import json
import mimetypes
import re
import sys
import uuid
import warnings
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from backend.ai import AIServiceError
from backend.config import Settings, WEB_ROOT, load_settings
from backend.database import Database, utc_now
from backend.parsers import DocumentParseError
from backend.security import ROLE_PERMISSIONS, AuthService, hash_password
from backend.services import PlatformService


warnings.filterwarnings("ignore", message="'cgi' is deprecated", category=DeprecationWarning)
MAX_JSON_BYTES = 1_000_000
SESSION_COOKIE = "xzs_session"
BLOCKED_STATIC_PREFIXES = ("/backend/", "/runtime/", "/knowledge/", "/scripts/")
BLOCKED_STATIC_SUFFIXES = (".py", ".pyc", ".db", ".sqlite", ".env", ".ps1", ".mjs")
INLINE_DOCUMENT_SUFFIXES = {".pdf", ".txt", ".csv", ".md", ".json", ".html", ".htm"}


class ApiError(Exception):
    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


class ComplianceRequestHandler(SimpleHTTPRequestHandler):
    server_version = "SecuritiesCompliancePlatform/2.0"
    settings: Settings
    database: Database
    auth: AuthService
    platform: PlatformService

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; font-src 'self' data:; frame-src 'self' blob:; frame-ancestors 'none'",
        )
        super().end_headers()

    @property
    def client_ip(self) -> str:
        return self.client_address[0] if self.client_address else ""

    @property
    def request_path(self) -> str:
        return urlparse(self.path).path

    def send_json(
        self,
        payload: dict[str, object] | list[object],
        status: HTTPStatus = HTTPStatus.OK,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_empty(self, status: HTTPStatus = HTTPStatus.NO_CONTENT) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_download(self, filename: str, content: bytes) -> None:
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
        self.end_headers()
        self.wfile.write(content)

    def send_document(self, filename: str, content: bytes) -> None:
        suffix = Path(filename).suffix.lower()
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/json":
            content_type = f"{content_type}; charset=utf-8"
        disposition = "inline" if suffix in INLINE_DOCUMENT_SUFFIXES else "attachment"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{quote(filename)}")
        self.end_headers()
        self.wfile.write(content)

    def session_cookie(self, token: str, max_age: int | None = None) -> str:
        secure = "; Secure" if self.settings.is_production else ""
        age = self.settings.session_hours * 3600 if max_age is None else max_age
        return f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}{secure}"

    def read_json(self) -> dict[str, object]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ApiError("请求长度无效。") from error
        if length <= 0 or length > MAX_JSON_BYTES:
            raise ApiError("请求内容为空或超过限制。", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiError("JSON 请求格式无效。") from error
        if not isinstance(payload, dict):
            raise ApiError("JSON 请求必须是对象。")
        return payload

    def read_form(self) -> cgi.FieldStorage:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ApiError("上传请求长度无效。") from error
        if length <= 0:
            raise ApiError("没有收到上传文件。")
        # A review may include the primary document plus several comparison
        # workbooks/reports.  Each part is still capped independently by
        # read_upload/read_optional_uploads below.
        if length > self.settings.max_upload_bytes * 10 + 2_000_000:
            raise ApiError("上传文件总大小超过限制。", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        return cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": self.command,
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": str(length),
            },
        )

    def read_upload(self, form: cgi.FieldStorage, field: str = "document") -> tuple[str, bytes]:
        upload = form[field] if field in form else None
        if upload is None or isinstance(upload, list) or not getattr(upload, "filename", ""):
            raise ApiError("请选择待处理文档。")
        filename = Path(upload.filename).name
        content = upload.file.read(self.settings.max_upload_bytes + 1)
        if len(content) > self.settings.max_upload_bytes:
            raise ApiError("文件超过上传大小限制。", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        if not content:
            raise ApiError("上传文件为空。")
        return filename, content

    def read_optional_upload(self, form: cgi.FieldStorage, field: str) -> tuple[str, bytes] | None:
        """Backward-compatible single-file companion reader."""
        values = self.read_optional_uploads(form, field)
        return values[0] if values else None

    def read_optional_uploads(self, form: cgi.FieldStorage, field: str) -> list[tuple[str, bytes]]:
        """Read all optional comparison files from repeated multipart fields."""
        if field not in form:
            return []
        raw = form[field]
        uploads = raw if isinstance(raw, list) else [raw]
        values: list[tuple[str, bytes]] = []
        for upload in uploads:
            if upload is None or not getattr(upload, "filename", ""):
                continue
            if len(values) >= 8:
                raise ApiError("最多可添加 8 份对比文件。")
            filename = Path(upload.filename).name
            content = upload.file.read(self.settings.max_upload_bytes + 1)
            if len(content) > self.settings.max_upload_bytes:
                raise ApiError(f"对比文件超过单文件 {self.settings.max_upload_bytes // 1024 // 1024}MB 限制。", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            if not content:
                raise ApiError(f"对比文件为空：{filename}")
            values.append((filename, content))
        return values

    def session_token(self) -> str | None:
        authorization = self.headers.get("Authorization", "")
        if authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def require_user(self, permission: str = "view") -> dict[str, object]:
        user = self.auth.authenticate(self.session_token())
        if not user:
            raise ApiError("请先登录。", HTTPStatus.UNAUTHORIZED)
        if not self.auth.permitted(user, permission):
            raise ApiError("当前角色没有执行该操作的权限。", HTTPStatus.FORBIDDEN)
        return user

    def handle_error(self, error: Exception) -> None:
        if isinstance(error, ApiError):
            self.send_json({"error": str(error)}, error.status)
        elif isinstance(error, PermissionError):
            self.send_json({"error": str(error)}, HTTPStatus.FORBIDDEN)
        elif isinstance(error, (DocumentParseError, ValueError, AIServiceError)):
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        else:
            self.send_json({"error": "服务处理请求时发生异常，请稍后重试。"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            if self.settings.app_env != "production":
                sys.stderr.write(f"Unhandled API error: {type(error).__name__}: {error}\n")

    def do_OPTIONS(self) -> None:
        self.send_empty()

    def do_GET(self) -> None:
        try:
            path = self.request_path
            query = parse_qs(urlparse(self.path).query)
            if path == "/api/health":
                self.send_json(self.platform.status())
                return
            if path == "/api/auth/me":
                user = self.require_user()
                self.send_json({"user": user, "permissions": sorted(ROLE_PERMISSIONS.get(str(user["role"]), set()))})
                return
            if path == "/api/tasks":
                user = self.require_user()
                self.send_json({"tasks": self.platform.list_tasks(user)})
                return
            if path == "/api/drafts":
                user = self.require_user("analyze")
                self.send_json({"drafts": self.platform.list_drafts(user)})
                return
            draft_document_match = re.fullmatch(r"/api/drafts/([^/]+)/document", path)
            if draft_document_match:
                user = self.require_user("view")
                filename, content = self.platform.get_draft_document(
                    draft_document_match.group(1), user, self.client_ip,
                )
                self.send_document(filename, content)
                return
            draft_reference_match = re.fullmatch(r"/api/drafts/([^/]+)/reference-document", path)
            if draft_reference_match:
                user = self.require_user("view")
                filename, content = self.platform.get_draft_reference_document(
                    draft_reference_match.group(1), user, self.client_ip,
                )
                self.send_document(filename, content)
                return
            draft_match = re.fullmatch(r"/api/drafts/([^/]+)", path)
            if draft_match:
                user = self.require_user("analyze")
                self.send_json(self.platform.get_draft(draft_match.group(1), user))
                return
            analysis_job_match = re.fullmatch(r"/api/analysis-jobs/([^/]+)", path)
            if analysis_job_match:
                user = self.require_user()
                self.send_json(self.platform.get_analysis_job(analysis_job_match.group(1), user))
                return
            document_match = re.fullmatch(r"/api/tasks/([^/]+)/document", path)
            if document_match:
                user = self.require_user()
                filename, content = self.platform.get_task_document(document_match.group(1), user, self.client_ip)
                self.send_download(filename, content)
                return
            related_document_preview_match = re.fullmatch(r"/api/tasks/([^/]+)/documents/([^/]+)/preview", path)
            if related_document_preview_match:
                user = self.require_user()
                self.send_json(self.platform.get_task_related_document_preview(
                    related_document_preview_match.group(1), related_document_preview_match.group(2),
                    user, self.client_ip,
                ))
                return
            related_document_match = re.fullmatch(r"/api/tasks/([^/]+)/documents/([^/]+)", path)
            if related_document_match:
                user = self.require_user()
                filename, content = self.platform.get_task_related_document(
                    related_document_match.group(1), related_document_match.group(2), user, self.client_ip,
                )
                self.send_download(filename, content)
                return
            annotated_document_match = re.fullmatch(r"/api/tasks/([^/]+)/annotated-document", path)
            if annotated_document_match:
                user = self.require_user("view")
                filename, content = self.platform.get_annotated_task_document(
                    annotated_document_match.group(1), user, self.client_ip,
                )
                self.send_download(filename, content)
                return
            document_preview_match = re.fullmatch(r"/api/tasks/([^/]+)/document-preview", path)
            if document_preview_match:
                user = self.require_user()
                self.send_json(self.platform.get_task_document_preview(
                    document_preview_match.group(1), user, self.client_ip,
                ))
                return
            financial_audit_match = re.fullmatch(r"/api/tasks/([^/]+)/financial-audit", path)
            if financial_audit_match:
                user = self.require_user("view")
                self.send_json(self.platform.get_financial_audit(financial_audit_match.group(1), user))
                return
            financial_report_match = re.fullmatch(r"/api/tasks/([^/]+)/financial-audit/report", path)
            if financial_report_match:
                user = self.require_user("view")
                report_format = query.get("format", ["html"])[0]
                filename, content = self.platform.get_financial_audit_report(
                    financial_report_match.group(1), report_format, user, self.client_ip,
                )
                self.send_document(filename, content)
                return
            task_match = re.fullmatch(r"/api/tasks/([^/]+)", path)
            if task_match:
                user = self.require_user()
                self.send_json(self.platform.get_task_result(task_match.group(1), user=user))
                return
            if path == "/api/knowledge":
                user = self.require_user()
                document_type = query.get("document_type", [None])[0]
                category_id = query.get("category_id", [None])[0]
                self.send_json({"documents": self.platform.list_knowledge(user, document_type, category_id)})
                return
            if path == "/api/knowledge/categories":
                user = self.require_user()
                self.send_json({"categories": self.platform.list_knowledge_categories(user)})
                return
            if path == "/api/rules/compare":
                user = self.require_user("view")
                title = query.get("title", [""])[0]
                new_year = query.get("new_year", ["2026"])[0]
                old_year = query.get("old_year", ["2025"])[0]
                self.send_json(self.platform.compare_rule_versions(
                    title, new_year, old_year, user, self.client_ip,
                ))
                return
            knowledge_preview_match = re.fullmatch(r"/api/knowledge/([^/]+)/preview", path)
            if knowledge_preview_match:
                user = self.require_user("view")
                self.send_json(self.platform.get_knowledge_document_preview(
                    knowledge_preview_match.group(1), user, self.client_ip,
                ))
                return
            knowledge_document_match = re.fullmatch(r"/api/knowledge/([^/]+)/document", path)
            if knowledge_document_match:
                user = self.require_user("view")
                filename, content = self.platform.get_knowledge_document(
                    knowledge_document_match.group(1), user, self.client_ip,
                )
                self.send_document(filename, content)
                return
            if path == "/api/usage":
                user = self.require_user("audit")
                self.send_json(self.platform.usage_summary(user))
                return
            if path == "/api/audit":
                user = self.require_user("audit")
                limit = int(query.get("limit", ["100"])[0])
                self.send_json({"logs": self.platform.audit_logs(user, limit)})
                return
            if path == "/api/conversations":
                user = self.require_user()
                task_id = query.get("task_id", [None])[0]
                self.send_json({"conversations": self.platform.list_conversations(user, task_id)})
                return
            if path == "/api/chat/conversations":
                user = self.require_user("analyze")
                self.send_json({"conversations": self.platform.list_workspace_conversations(user)})
                return
            workspace_message_match = re.fullmatch(r"/api/chat/([^/]+)/messages", path)
            if workspace_message_match:
                user = self.require_user("analyze")
                self.send_json({"messages": self.platform.get_workspace_messages(workspace_message_match.group(1), user)})
                return
            message_match = re.fullmatch(r"/api/conversations/([^/]+)/messages", path)
            if message_match:
                user = self.require_user()
                self.send_json({"messages": self.platform.get_messages(message_match.group(1), user)})
                return
            if path == "/api/users":
                self.require_user("users")
                users = self.database.fetch_all(
                    """SELECT id,username,display_name,role,active,created_at,updated_at FROM users
                       WHERE deleted_at IS NULL ORDER BY created_at DESC"""
                )
                self.send_json({"users": users})
                return
            if path == "/api/company-profile":
                user = self.require_user()
                facts = self.database.fetch_all(
                    """SELECT * FROM company_profiles
                       WHERE owner_user_id IS NULL OR owner_user_id=? ORDER BY fact_type,fact_key""",
                    (user["id"],),
                )
                self.send_json({"facts": facts})
                return

            if path.startswith(BLOCKED_STATIC_PREFIXES) or path.lower().endswith(BLOCKED_STATIC_SUFFIXES):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            super().do_GET()
        except Exception as error:
            self.handle_error(error)

    def do_POST(self) -> None:
        try:
            path = self.request_path
            if path == "/api/auth/login":
                payload = self.read_json()
                result = self.auth.login(str(payload.get("username", "")), str(payload.get("password", "")), self.client_ip)
                if not result:
                    self.database.audit(None, "login_failed", "session", None, self.client_ip)
                    raise ApiError("用户名或密码错误。", HTTPStatus.UNAUTHORIZED)
                token, user = result
                self.database.audit(user["id"], "login", "session", None, self.client_ip)
                self.send_json(
                    {"user": user, "expiresIn": self.settings.session_hours * 3600},
                    extra_headers={"Set-Cookie": self.session_cookie(token)},
                )
                return
            if path == "/api/auth/register":
                payload = self.read_json()
                password = str(payload.get("password", ""))
                if password != str(payload.get("password_confirm", "")):
                    raise ApiError("两次输入的密码不一致。")
                token, user = self.auth.register(
                    str(payload.get("username", "")),
                    password,
                    str(payload.get("display_name", "")),
                    self.client_ip,
                )
                self.database.audit(user["id"], "register", "user", user["id"], self.client_ip)
                self.database.audit(user["id"], "login", "session", None, self.client_ip)
                self.send_json(
                    {"user": user, "expiresIn": self.settings.session_hours * 3600},
                    HTTPStatus.CREATED,
                    extra_headers={"Set-Cookie": self.session_cookie(token)},
                )
                return
            if path == "/api/auth/logout":
                user = self.require_user()
                self.auth.logout(self.session_token())
                self.database.audit(user["id"], "logout", "session", None, self.client_ip)
                self.send_json({"status": "ok"}, extra_headers={"Set-Cookie": self.session_cookie("", 0)})
                return
            if path == "/api/auth/change-password":
                user = self.require_user()
                payload = self.read_json()
                new_password = str(payload.get("new_password", ""))
                if new_password != str(payload.get("new_password_confirm", "")):
                    raise ApiError("两次输入的新密码不一致。")
                token, refreshed_user = self.auth.change_password(
                    str(user["id"]),
                    str(payload.get("current_password", "")),
                    new_password,
                    self.client_ip,
                )
                self.database.audit(user["id"], "password_change", "user", str(user["id"]), self.client_ip)
                self.send_json(
                    {"status": "ok", "user": refreshed_user, "expiresIn": self.settings.session_hours * 3600},
                    extra_headers={"Set-Cookie": self.session_cookie(token)},
                )
                return
            if path == "/api/auth/delete-account":
                user = self.require_user()
                payload = self.read_json()
                if str(payload.get("confirmation", "")).strip() != "注销账号":
                    raise ApiError("请输入“注销账号”完成确认。")
                if not self.auth.verify_current_password(
                    str(user["id"]), str(payload.get("current_password", ""))
                ):
                    raise ApiError("当前密码错误。")
                result = self.platform.delete_account(
                    str(user["id"]), user, self.client_ip, self_service=True,
                )
                self.send_json(
                    result,
                    extra_headers={"Set-Cookie": self.session_cookie("", 0)},
                )
                return
            if path in {"/api/analyze", "/api/tasks"}:
                user = self.require_user("upload")
                form = self.read_form()
                filename, content = self.read_upload(form)
                comparison_documents = self.read_optional_uploads(form, "comparison_document")
                result = self.platform.create_analysis_job(
                    filename,
                    content,
                    form.getfirst("taskName", Path(filename).stem),
                    form.getfirst("taskType", "auto"),
                    form.getfirst("rulePack", "auto"),
                    user,
                    self.client_ip,
                    comparison_documents=comparison_documents,
                )
                self.send_json(result, HTTPStatus.ACCEPTED)
                return
            if path == "/api/tasks/batch-delete":
                user = self.require_user("view")
                payload = self.read_json()
                task_ids = payload.get("task_ids", payload.get("taskIds", []))
                if not isinstance(task_ids, list):
                    raise ApiError("task_ids 必须是数组。")
                self.send_json(self.platform.delete_tasks(task_ids, user, self.client_ip))
                return
            if path == "/api/drafts":
                user = self.require_user("analyze")
                payload = self.read_json()
                self.send_json(self.platform.create_draft(payload, user, self.client_ip), HTTPStatus.CREATED)
                return
            if path == "/api/drafts/from-reference":
                user = self.require_user("analyze")
                form = self.read_form()
                filename, content = self.read_upload(form, "reference_document")
                payload = {
                    key: form.getfirst(key, "")
                    for key in ("title", "document_type", "subject", "facts", "requirements")
                }
                self.send_json(
                    self.platform.create_draft_from_reference(filename, content, payload, user, self.client_ip),
                    HTTPStatus.CREATED,
                )
                return
            draft_update_match = re.fullmatch(r"/api/drafts/([^/]+)", path)
            if draft_update_match:
                user = self.require_user("analyze")
                payload = self.read_json()
                self.send_json(self.platform.update_draft(draft_update_match.group(1), payload, user, self.client_ip))
                return
            if path == "/api/knowledge/import":
                user = self.require_user("knowledge")
                form = self.read_form()
                filename, content = self.read_upload(form)
                metadata = {
                    key: form.getfirst(key, "")
                    for key in (
                        "title", "document_type", "company", "source", "source_url", "announcement_id",
                        "date", "effective_date", "expiry_date", "version", "source_type", "source_name",
                        "relative_path", "category_id",
                    )
                }
                self.send_json(self.platform.import_knowledge(filename, content, metadata, user, self.client_ip), HTTPStatus.CREATED)
                return
            if path == "/api/knowledge/categories":
                user = self.require_user("knowledge")
                payload = self.read_json()
                self.send_json(self.platform.create_knowledge_category(
                    str(payload.get("name", "")), str(payload.get("description", "")), user, self.client_ip,
                ), HTTPStatus.CREATED)
                return
            rebuild_match = re.fullmatch(r"/api/knowledge/([^/]+)/rebuild", path)
            if rebuild_match:
                user = self.require_user("knowledge")
                self.send_json(self.platform.rebuild_knowledge(rebuild_match.group(1), user, self.client_ip))
                return
            report_match = re.fullmatch(r"/api/tasks/([^/]+)/report", path)
            if report_match:
                user = self.require_user("view")
                self.send_json(self.platform.generate_report(report_match.group(1), user, self.client_ip))
                return
            chat_match = re.fullmatch(r"/api/tasks/([^/]+)/chat", path)
            if chat_match:
                user = self.require_user("analyze")
                payload = self.read_json()
                self.send_json(self.platform.chat(
                    chat_match.group(1), str(payload.get("question", "")),
                    str(payload.get("conversation_id", "")) or None, user, self.client_ip,
                ))
                return
            if path == "/api/chat":
                user = self.require_user("analyze")
                payload = self.read_json()
                self.send_json(self.platform.workspace_chat(
                    str(payload.get("question", "")),
                    str(payload.get("conversation_id", "")) or None,
                    user,
                    self.client_ip,
                ))
                return
            review_match = re.fullmatch(r"/api/risks/([^/]+)/review", path)
            if review_match:
                user = self.require_user("review")
                payload = self.read_json()
                self.send_json(self.platform.review_risk(
                    review_match.group(1), str(payload.get("action", "")), str(payload.get("comment", "")), user, self.client_ip,
                ))
                return
            if path == "/api/users":
                actor = self.require_user("users")
                payload = self.read_json()
                username = str(payload.get("username", "")).strip()
                password = str(payload.get("password", ""))
                role = str(payload.get("role", "user"))
                if not username or len(password) < 8 or role not in ROLE_PERMISSIONS:
                    raise ApiError("用户名、密码或角色无效；密码至少 8 位。")
                user_id = str(uuid.uuid4())
                now = utc_now()
                self.database.execute(
                    "INSERT INTO users (id,username,password_hash,display_name,role,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                    (user_id, username, hash_password(password), str(payload.get("display_name", username)), role, now, now),
                )
                self.database.audit(actor["id"], "user_create", "user", user_id, self.client_ip, after={"username": username, "role": role})
                self.send_json({"id": user_id, "username": username, "role": role}, HTTPStatus.CREATED)
                return
            if path == "/api/company-profile":
                user = self.require_user("knowledge")
                payload = self.read_json()
                required = ["company", "fact_type", "fact_key", "fact_value", "source"]
                if any(not str(payload.get(key, "")).strip() for key in required):
                    raise ApiError("公司画像事实缺少必填字段。")
                fact_id = str(uuid.uuid4())
                now = utc_now()
                self.database.execute(
                    """INSERT INTO company_profiles (id,owner_user_id,company,stock_code,fact_type,fact_key,fact_value,source,effective_date,version,last_verified_at,confirmed,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        fact_id, None, payload["company"], payload.get("stock_code"), payload["fact_type"], payload["fact_key"],
                        payload["fact_value"], payload["source"], payload.get("effective_date"), payload.get("version"),
                        now, int(bool(payload.get("confirmed"))), now, now,
                    ),
                )
                self.database.audit(user["id"], "company_fact_create", "company_profile", fact_id, self.client_ip, after={key: payload.get(key) for key in required})
                self.send_json({"id": fact_id}, HTTPStatus.CREATED)
                return
            raise ApiError("接口不存在。", HTTPStatus.NOT_FOUND)
        except Exception as error:
            self.handle_error(error)

    def do_DELETE(self) -> None:
        try:
            draft_match = re.fullmatch(r"/api/drafts/([^/]+)", self.request_path)
            if draft_match:
                user = self.require_user("analyze")
                self.send_json(self.platform.delete_draft(draft_match.group(1), user, self.client_ip))
                return
            user_match = re.fullmatch(r"/api/users/([^/]+)", self.request_path)
            if user_match:
                actor = self.require_user("users")
                self.send_json(self.platform.delete_account(user_match.group(1), actor, self.client_ip))
                return
            task_match = re.fullmatch(r"/api/tasks/([^/]+)", self.request_path)
            if task_match:
                user = self.require_user("view")
                self.send_json(self.platform.delete_task(task_match.group(1), user, self.client_ip))
                return
            category_match = re.fullmatch(r"/api/knowledge/categories/([^/]+)", self.request_path)
            if category_match:
                user = self.require_user("knowledge")
                self.send_json(self.platform.delete_knowledge_category(category_match.group(1), user, self.client_ip))
                return
            knowledge_match = re.fullmatch(r"/api/knowledge/([^/]+)", self.request_path)
            if knowledge_match:
                user = self.require_user("knowledge")
                self.platform.delete_knowledge(knowledge_match.group(1), user, self.client_ip)
                self.send_json({"status": "inactive"})
                return
            raise ApiError("接口不存在。", HTTPStatus.NOT_FOUND)
        except Exception as error:
            self.handle_error(error)

    def log_message(self, format_string: str, *args: object) -> None:
        command = getattr(self, "command", "REQUEST")
        path = urlparse(getattr(self, "path", "")).path or "-"
        sys.stdout.write(f"{command} {path}\n")
        sys.stdout.flush()


def create_runtime() -> tuple[Settings, Database, AuthService, PlatformService, dict[str, str] | None]:
    settings = load_settings()
    database = Database(settings.database_path)
    database.migrate()
    auth = AuthService(database, settings)
    bootstrap = auth.bootstrap()
    platform = PlatformService(settings, database)
    platform.initialize()
    return settings, database, auth, platform, bootstrap


def main() -> None:
    parser = argparse.ArgumentParser(description="上市公司证券合规风险管理与 AI 智能审阅平台")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--init-only", action="store_true")
    args = parser.parse_args()

    settings, database, auth, platform, bootstrap = create_runtime()
    platform.bind_address = args.bind
    ComplianceRequestHandler.settings = settings
    ComplianceRequestHandler.database = database
    ComplianceRequestHandler.auth = auth
    ComplianceRequestHandler.platform = platform
    if bootstrap and settings.app_env != "production":
        print(f"首次启动开发账号：{bootstrap['username']} / {bootstrap['password']}（请登录后修改或通过环境变量覆盖）")
    if args.init_only:
        print(f"数据库初始化完成：{settings.database_path}")
        return
    server = ThreadingHTTPServer((args.bind, args.port), ComplianceRequestHandler)
    print(f"证券合规平台：http://{args.bind}:{args.port}/index.html")
    print(f"AI_MODE={settings.ai_mode}，Embedding={platform.embedding_provider.model_name()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from .config import Settings
from .database import Database, utc_now


ROLE_PERMISSIONS = {
    "admin": {"view", "upload", "analyze", "review", "knowledge", "audit", "users"},
    "securities": {"view", "upload", "analyze", "review", "audit"},
    "legal": {"view", "upload", "analyze", "review"},
    "leader": {"view", "review", "audit"},
    "user": {"view", "upload", "analyze", "review", "audit"},
}


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return f"pbkdf2_sha256$240000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, expected_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


class AuthService:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings

    def bootstrap(self) -> dict[str, str] | None:
        existing = self.database.fetch_one("SELECT id FROM users LIMIT 1")
        if existing:
            return None
        password = self.settings.bootstrap_admin_password
        generated = False
        if not password:
            if self.settings.is_production:
                raise RuntimeError("生产环境必须配置 BOOTSTRAP_ADMIN_PASSWORD。")
            password = "Admin123!"
            generated = True
        user_id = str(uuid.uuid4())
        now = utc_now()
        self.database.execute(
            "INSERT INTO users (id,username,password_hash,display_name,role,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (
                user_id,
                self.settings.bootstrap_admin_username,
                hash_password(password),
                "系统管理员",
                "admin",
                now,
                now,
            ),
        )
        return {"username": self.settings.bootstrap_admin_username, "password": password, "generated": str(generated)}

    def login(self, username: str, password: str, ip: str | None) -> tuple[str, dict[str, Any]] | None:
        user = self.database.fetch_one(
            "SELECT id,username,password_hash,display_name,role,active FROM users WHERE username=? COLLATE NOCASE",
            (username.strip(),),
        )
        if not user or not user["active"] or not verify_password(password, user["password_hash"]):
            return None
        return self._create_session(user, ip)

    def register(
        self,
        username: str,
        password: str,
        display_name: str,
        ip: str | None,
    ) -> tuple[str, dict[str, Any]]:
        if not self.settings.allow_registration:
            raise ValueError("当前系统未开放自助注册。")
        username = username.strip()
        display_name = display_name.strip() or username
        if not re.fullmatch(r"[\w.-]{3,32}", username, flags=re.UNICODE):
            raise ValueError("用户名须为 3-32 位，可使用中文、字母、数字、点、横线或下划线。")
        if len(display_name) > 40:
            raise ValueError("姓名或昵称不能超过 40 个字符。")
        if len(password) < 8 or len(password) > 128:
            raise ValueError("密码须为 8-128 位。")
        if self.database.fetch_one("SELECT id FROM users WHERE lower(username)=lower(?)", (username,)):
            raise ValueError("该用户名已被注册。")
        user_id = str(uuid.uuid4())
        now = utc_now()
        try:
            self.database.execute(
                "INSERT INTO users (id,username,password_hash,display_name,role,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (user_id, username, hash_password(password), display_name, "user", now, now),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("该用户名已被注册。") from error
        return self._create_session(
            {"id": user_id, "username": username, "display_name": display_name, "role": "user"},
            ip,
        )

    def _create_session(self, user: dict[str, Any], ip: str | None) -> tuple[str, dict[str, Any]]:
        token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(UTC)
        expires = now + timedelta(hours=self.settings.session_hours)
        self.database.execute(
            "INSERT INTO sessions (token_hash,user_id,ip,created_at,expires_at) VALUES (?,?,?,?,?)",
            (token_hash, user["id"], ip, now.replace(microsecond=0).isoformat(), expires.replace(microsecond=0).isoformat()),
        )
        public_user = {key: user[key] for key in ("id", "username", "display_name", "role")}
        return token, public_user

    def authenticate(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        user = self.database.fetch_one(
            """
            SELECT u.id,u.username,u.display_name,u.role,u.active,s.expires_at
            FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?
            """,
            (token_hash,),
        )
        if not user or not user["active"]:
            return None
        try:
            expires_at = datetime.fromisoformat(user["expires_at"])
        except ValueError:
            return None
        if expires_at < datetime.now(UTC):
            self.database.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
            return None
        return {key: user[key] for key in ("id", "username", "display_name", "role")}

    def logout(self, token: str | None) -> None:
        if not token:
            return
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self.database.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))

    def change_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
        ip: str | None,
    ) -> tuple[str, dict[str, Any]]:
        user = self.database.fetch_one(
            "SELECT id,username,password_hash,display_name,role,active FROM users WHERE id=?",
            (user_id,),
        )
        if not user or not user["active"]:
            raise ValueError("当前账号不可用。")
        if not verify_password(current_password, user["password_hash"]):
            raise ValueError("当前密码错误。")
        if len(new_password) < 8 or len(new_password) > 128:
            raise ValueError("新密码须为 8-128 位。")
        if verify_password(new_password, user["password_hash"]):
            raise ValueError("新密码不能与当前密码相同。")
        now = utc_now()
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE users SET password_hash=?,updated_at=? WHERE id=?",
                (hash_password(new_password), now, user_id),
            )
            connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        return self._create_session(user, ip)

    def verify_current_password(self, user_id: str, password: str) -> bool:
        user = self.database.fetch_one(
            "SELECT password_hash,active,deleted_at FROM users WHERE id=?",
            (user_id,),
        )
        return bool(
            user
            and user["active"]
            and not user.get("deleted_at")
            and verify_password(password, user["password_hash"])
        )

    @staticmethod
    def permitted(user: dict[str, Any], permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(str(user.get("role")), set())

from fastapi import HTTPException, status, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict, Any
import time
import os
import sqlite3
import json
import hmac
import hashlib
import base64
import secrets
from threading import Lock
from models.config import UserConfig, settings
from models.schemas import UserRole


active_sessions: Dict[str, Dict[str, Any]] = {}
security = HTTPBearer(auto_error=False)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_DB_PATH = os.path.normpath(os.path.join(BASE_DIR, "..", "tokens.db"))
_token_db_conn = sqlite3.connect(TOKEN_DB_PATH, check_same_thread=False)
_token_db_lock = Lock()

with _token_db_conn:
    _token_db_conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jwt_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jti TEXT UNIQUE,
            username TEXT,
            role TEXT,
            token TEXT,
            created_at INTEGER,
            expires_at INTEGER,
            revoked INTEGER DEFAULT 0
        )
        """
    )


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _jwt_secret() -> str:
    try:
        return settings.secret_key
    except Exception:
        return "change-this-secret"


def _encode_jwt(payload: Dict[str, Any]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    header_b64 = _b64url_encode(header_bytes)
    payload_b64 = _b64url_encode(payload_bytes)
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    key = _jwt_secret().encode("utf-8")
    signature = hmac.new(key, signing_input, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def _decode_jwt(token: str) -> Optional[Dict[str, Any]]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, signature_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        key = _jwt_secret().encode("utf-8")
        expected_sig = hmac.new(key, signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(signature_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        payload_bytes = _b64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
        exp_ts = int(payload.get("exp", 0))
        if exp_ts and time.time() > exp_ts:
            return None
        return payload
    except Exception:
        return None


def _store_jwt_token(jti: str, username: str, role: str, token: str, expires_at: int) -> None:
    created_at = int(time.time())
    try:
        with _token_db_lock:
            with _token_db_conn:
                _token_db_conn.execute(
                    "INSERT OR REPLACE INTO jwt_tokens (jti, username, role, token, created_at, expires_at, revoked) VALUES (?, ?, ?, ?, ?, ?, 0)",
                    (jti, username, role, token, created_at, expires_at),
                )
    except Exception as e:
        print(f"Error storing JWT token: {e}")


def _token_exists(jti: str) -> bool:
    try:
        with _token_db_lock:
            cur = _token_db_conn.cursor()
            cur.execute(
                "SELECT 1 FROM jwt_tokens WHERE jti = ? AND revoked = 0",
                (jti,),
            )
            row = cur.fetchone()
            return row is not None
    except Exception as e:
        print(f"Error checking JWT token: {e}")
        return False


def revoke_user_tokens(username: str) -> int:
    try:
        with _token_db_lock:
            cur = _token_db_conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM jwt_tokens WHERE username = ? AND revoked = 0",
                (username,),
            )
            count_row = cur.fetchone()
            cur.execute(
                "DELETE FROM jwt_tokens WHERE username = ?",
                (username,),
            )
            _token_db_conn.commit()
            if count_row and len(count_row) > 0:
                return int(count_row[0])
            return 0
    except Exception as e:
        print(f"Error revoking JWT tokens for {username}: {e}")
        return 0


def create_user_jwt(username: str, role: str, expires_in: int = 3600) -> str:
    now = int(time.time())
    exp_ts = now + expires_in
    jti = secrets.token_hex(16)
    payload = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": exp_ts,
        "jti": jti,
    }
    token = _encode_jwt(payload)
    _store_jwt_token(jti, username, role, token, exp_ts)
    return token


def validate_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    payload = _decode_jwt(token)
    if not payload:
        return None
    jti = str(payload.get("jti") or "")
    if not jti:
        return None
    if not _token_exists(jti):
        return None
    return payload


class SessionManager:
    @staticmethod
    def create_session(username: str, role: str) -> str:
        session_id = f"{username}_{int(time.time())}"
        active_sessions[session_id] = {
            "username": username,
            "role": role,
            "created_at": time.time(),
            "last_activity": time.time(),
        }
        return session_id

    @staticmethod
    def get_session(session_id: str) -> Optional[Dict[str, Any]]:
        if session_id in active_sessions:
            session = active_sessions[session_id]
            session["last_activity"] = time.time()
            return session
        return None

    @staticmethod
    def delete_session(session_id: str) -> bool:
        if session_id in active_sessions:
            del active_sessions[session_id]
            return True
        return False

    @staticmethod
    def get_user_sessions(username: str) -> list:
        return [
            session_id
            for session_id, data in active_sessions.items()
            if data["username"] == username
        ]

    @staticmethod
    def get_all_sessions() -> Dict[str, Dict[str, Any]]:
        return active_sessions.copy()

    @staticmethod
    def cleanup_expired_sessions(timeout: int = 3600) -> int:
        current_time = time.time()
        expired_sessions = [
            session_id
            for session_id, data in active_sessions.items()
            if current_time - data["last_activity"] > timeout
        ]
        for session_id in expired_sessions:
            del active_sessions[session_id]
        return len(expired_sessions)


def authenticate_user(username: str, password: str) -> Optional[Dict[str, str]]:
    if UserConfig.validate_credentials(username, password):
        role = UserConfig.get_user_role(username)
        return {"username": username, "role": role}
    return None


def get_current_user_from_session(request: Request) -> Optional[Dict[str, Any]]:
    session_id = request.cookies.get("session_id")
    if not session_id:
        return None
    session = SessionManager.get_session(session_id)
    if not session:
        return None
    username = session.get("username")
    role = session.get("role")
    if role == UserRole.MAMA:
        jwt_token = request.cookies.get("mama_jwt") or request.cookies.get("jwt_token")
        if not jwt_token:
            SessionManager.delete_session(session_id)
            return None
        payload = validate_jwt_token(jwt_token)
        if not payload:
            SessionManager.delete_session(session_id)
            return None
        if str(payload.get("sub")) != str(username):
            SessionManager.delete_session(session_id)
            return None
        payload_role = str(payload.get("role"))
        if payload_role != UserRole.MAMA.value:
            SessionManager.delete_session(session_id)
            return None
    return session


def require_auth(request: Request) -> Dict[str, Any]:
    user = get_current_user_from_session(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


def require_admin(request: Request) -> Dict[str, Any]:
    user = require_auth(request)
    if user["role"] != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


def get_optional_user(request: Request) -> Optional[Dict[str, Any]]:
    try:
        return get_current_user_from_session(request)
    except Exception:
        return None


def kick_user_sessions(username: str) -> int:
    sessions_to_remove = SessionManager.get_user_sessions(username)
    for session_id in sessions_to_remove:
        SessionManager.delete_session(session_id)
    return len(sessions_to_remove)


def is_mama_user(user: Dict[str, Any]) -> bool:
    return UserConfig.is_mama(user.get("username", ""))


def get_mama_sessions() -> list:
    return SessionManager.get_user_sessions(UserConfig.MAMA_USERNAME)


session_manager = SessionManager()

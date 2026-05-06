from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request, WebSocket, status
from pydantic import BaseModel

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_STATE_DIR = os.path.join(ROOT_DIR, ".state")
STATE_DIR = os.environ.get("CYBERRANGER_STATE_DIR", DEFAULT_STATE_DIR)
USERS_FILE = os.path.join(STATE_DIR, "users.json")
SECRET_FILE = os.path.join(STATE_DIR, "auth_secret.txt")

DEFAULT_ADMIN_USERNAME = os.environ.get("CYBERRANGER_ADMIN_USERNAME", "admin").strip().lower() or "admin"
DEFAULT_ADMIN_PASSWORD = os.environ.get("CYBERRANGER_ADMIN_PASSWORD", "admin123!")
TOKEN_TTL_SECONDS = int(os.environ.get("CYBERRANGER_TOKEN_TTL_SECONDS", "43200"))
ALLOW_SELF_REGISTRATION = os.environ.get("CYBERRANGER_ALLOW_SELF_REGISTRATION", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}

_PASSWORD_ITERATIONS = 390000
_USERS_LOCK = threading.Lock()


class AuthenticatedUser(BaseModel):
    id: str
    username: str
    full_name: Optional[str] = None
    role: str = "user"
    is_active: bool = True
    created_at: float
    last_login_at: Optional[float] = None


def _ensure_data_dir() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)


def _load_users_unlocked() -> Dict[str, Dict[str, Any]]:
    try:
        with open(USERS_FILE, "r") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_users_unlocked(users: Dict[str, Dict[str, Any]]) -> None:
    _ensure_data_dir()
    with open(USERS_FILE, "w") as handle:
        json.dump(users, handle, indent=2)


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${_PASSWORD_ITERATIONS}${_urlsafe_b64encode(salt)}${_urlsafe_b64encode(digest)}"


def hash_password(password: str) -> str:
    return _hash_password(password, secrets.token_bytes(16))


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, _digest_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = _urlsafe_b64decode(salt_b64)
        expected = _hash_password(password, salt)
        return hmac.compare_digest(expected, password_hash)
    except Exception:
        return False


def _get_secret_key() -> str:
    _ensure_data_dir()
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE, "r") as handle:
            secret = handle.read().strip()
            if secret:
                return secret

    secret = secrets.token_urlsafe(48)
    with open(SECRET_FILE, "w") as handle:
        handle.write(secret)
    return secret


def _normalize_username(username: str) -> str:
    value = (username or "").strip().lower()
    if not value:
        raise ValueError("Username is required")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
    if any(char not in allowed for char in value):
        raise ValueError("Username may only contain letters, numbers, '.', '_' and '-' characters")
    return value


def _validate_password(password: str) -> None:
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters long")


def _user_from_record(record: Dict[str, Any]) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=record["id"],
        username=record["username"],
        full_name=record.get("full_name"),
        role=record.get("role") or "user",
        is_active=bool(record.get("is_active", True)),
        created_at=float(record.get("created_at") or time.time()),
        last_login_at=record.get("last_login_at"),
    )


def ensure_bootstrap_admin() -> None:
    with _USERS_LOCK:
        users = _load_users_unlocked()
        has_admin = any((user.get("role") or "user") == "admin" for user in users.values())
        if has_admin:
            return

        now = time.time()
        admin_id = str(uuid.uuid4())
        users[admin_id] = {
            "id": admin_id,
            "username": DEFAULT_ADMIN_USERNAME,
            "full_name": "Administrator",
            "role": "admin",
            "is_active": True,
            "created_at": now,
            "last_login_at": None,
            "password_hash": hash_password(DEFAULT_ADMIN_PASSWORD),
        }
        _save_users_unlocked(users)


def get_user_by_id(user_id: str) -> Optional[AuthenticatedUser]:
    ensure_bootstrap_admin()
    with _USERS_LOCK:
        users = _load_users_unlocked()
        record = users.get(user_id)
        if not record:
            return None
        return _user_from_record(record)


def list_users() -> list[AuthenticatedUser]:
    ensure_bootstrap_admin()
    with _USERS_LOCK:
        users = _load_users_unlocked()
        return sorted((_user_from_record(record) for record in users.values()), key=lambda item: item.username)


def create_user(username: str, password: str, full_name: Optional[str] = None, role: str = "user") -> AuthenticatedUser:
    ensure_bootstrap_admin()
    normalized_username = _normalize_username(username)
    _validate_password(password)
    normalized_role = (role or "user").strip().lower()
    if normalized_role not in {"admin", "user"}:
        raise ValueError("Role must be either 'admin' or 'user'")

    with _USERS_LOCK:
        users = _load_users_unlocked()
        if any(user.get("username") == normalized_username for user in users.values()):
            raise ValueError("Username already exists")

        now = time.time()
        user_id = str(uuid.uuid4())
        record = {
            "id": user_id,
            "username": normalized_username,
            "full_name": (full_name or "").strip() or None,
            "role": normalized_role,
            "is_active": True,
            "created_at": now,
            "last_login_at": None,
            "password_hash": hash_password(password),
        }
        users[user_id] = record
        _save_users_unlocked(users)
        return _user_from_record(record)


def update_user(
    user_id: str,
    *,
    full_name: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    password: Optional[str] = None,
) -> AuthenticatedUser:
    ensure_bootstrap_admin()
    with _USERS_LOCK:
        users = _load_users_unlocked()
        record = users.get(user_id)
        if not record:
            raise ValueError("User not found")

        if full_name is not None:
            record["full_name"] = full_name.strip() or None
        if role is not None:
            normalized_role = role.strip().lower()
            if normalized_role not in {"admin", "user"}:
                raise ValueError("Role must be either 'admin' or 'user'")
            record["role"] = normalized_role
        if is_active is not None:
            record["is_active"] = bool(is_active)
        if password is not None:
            _validate_password(password)
            record["password_hash"] = hash_password(password)

        users[user_id] = record
        _save_users_unlocked(users)
        return _user_from_record(record)


def authenticate_user(username: str, password: str) -> Optional[AuthenticatedUser]:
    ensure_bootstrap_admin()
    normalized_username = _normalize_username(username)
    with _USERS_LOCK:
        users = _load_users_unlocked()
        for user_id, record in users.items():
            if record.get("username") != normalized_username:
                continue
            if not verify_password(password, record.get("password_hash") or ""):
                return None
            if not record.get("is_active", True):
                return None
            record["last_login_at"] = time.time()
            users[user_id] = record
            _save_users_unlocked(users)
            return _user_from_record(record)
    return None


def create_access_token(user: AuthenticatedUser) -> str:
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(_get_secret_key().encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    return f"{_urlsafe_b64encode(payload_bytes)}.{_urlsafe_b64encode(signature)}"


def _decode_access_token(token: str) -> Dict[str, Any]:
    try:
        payload_b64, signature_b64 = token.split(".", 1)
        payload_bytes = _urlsafe_b64decode(payload_b64)
        expected_signature = hmac.new(_get_secret_key().encode("utf-8"), payload_bytes, hashlib.sha256).digest()
        provided_signature = _urlsafe_b64decode(signature_b64)
        if not hmac.compare_digest(expected_signature, provided_signature):
            raise ValueError("Invalid token signature")
        payload = json.loads(payload_bytes.decode("utf-8"))
        if int(payload.get("exp") or 0) < int(time.time()):
            raise ValueError("Token expired")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token") from exc


def _extract_bearer_token(raw_header: Optional[str]) -> Optional[str]:
    if not raw_header:
        return None
    scheme, _, token = raw_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def get_current_user_from_token(token: str) -> AuthenticatedUser:
    payload = _decode_access_token(token)
    user = get_user_by_id(str(payload.get("sub") or ""))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


async def require_authenticated_user(request: Request) -> AuthenticatedUser:
    token = _extract_bearer_token(request.headers.get("authorization"))
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return get_current_user_from_token(token)


async def require_admin_user(current_user: AuthenticatedUser = Depends(require_authenticated_user)) -> AuthenticatedUser:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def get_current_user_from_websocket(websocket: WebSocket) -> AuthenticatedUser:
    token = websocket.query_params.get("token")
    if not token:
        token = _extract_bearer_token(websocket.headers.get("authorization"))
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return get_current_user_from_token(token)

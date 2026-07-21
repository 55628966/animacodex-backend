# -*- coding: utf-8 -*-
"""JWT authentication module for Model A — 29号 A_组.

CRITICAL RED LINES:
- NEVER store raw email — only sha256(email)
- NEVER include chart_id/birth data in JWT payload
- JWT expiration: access=1h, refresh=7d
- bcrypt cost factor: 12
- Email hash in JWT: sha256(email)[:16] (partial, for correlation only)
"""
import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import storage


class AuthError(Exception):
    """Auth-specific error that maps to a JSON error response."""
    def __init__(self, code: str, message: str, status: int = 401):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _auth_err_response(code: str, message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})

_JWT_SECRET = os.environ.get("ANIMA_JWT_SECRET") or secrets.token_hex(32)
_JWT_ALGORITHM = "HS256"
_ACCESS_TTL = timedelta(hours=1)
_REFRESH_TTL = timedelta(days=7)
_BCRYPT_ROUNDS = 12

router = APIRouter()


# ── Password utilities ──────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Return bcrypt hash of the plaintext password."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, pw_hash: str) -> bool:
    """Check a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), pw_hash.encode("utf-8"))


# ── Email hashing ───────────────────────────────────────────────────

def _hash_email(email: str) -> str:
    """sha256(email) — full hash for database lookup, never reversible."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def _short_email_hash(email: str) -> str:
    """First 16 hex chars of sha256(email) — for JWT correlation only."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:16]


# ── JWT utilities ───────────────────────────────────────────────────

def create_jwt(user_id: str, email: str) -> dict:
    """Return {access_token, refresh_token} for the given user.

    JWT payload never contains raw email, chart_id, or birth data.
    """
    now = datetime.now(timezone.utc)
    email_hash = _short_email_hash(email)
    access_payload = {
        "sub": user_id,
        "email_hash": email_hash,
        "iat": now,
        "exp": now + _ACCESS_TTL,
        "type": "access",
    }
    refresh_payload = {
        "sub": user_id,
        "email_hash": email_hash,
        "iat": now,
        "exp": now + _REFRESH_TTL,
        "type": "refresh",
    }
    return {
        "access_token": jwt.encode(access_payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM),
        "refresh_token": jwt.encode(refresh_payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM),
    }


def verify_jwt(token: str, expected_type: str = "access") -> dict:
    """Decode and validate a JWT. Raises on expired, wrong type, or tampered tokens."""
    payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"Expected token type '{expected_type}', got '{payload.get('type')}'")
    return payload


async def get_current_user(request: Request) -> str:
    """FastAPI dependency: extract user_id from Authorization: Bearer <token> header.

    Returns the user_id (sub claim) on success; raises 401-style AuthError on failure.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise AuthError("UNAUTHORIZED", "Missing or invalid Authorization header", 401)
    token = auth_header[7:]
    try:
        payload = verify_jwt(token, expected_type="access")
    except jwt.ExpiredSignatureError:
        raise AuthError("UNAUTHORIZED", "Access token has expired", 401)
    except jwt.InvalidTokenError:
        raise AuthError("UNAUTHORIZED", "Invalid or tampered access token", 401)
    return payload["sub"]


# ── Auth endpoints ──────────────────────────────────────────────────

@router.post("/auth/register")
async def auth_register(request: Request):
    """Register a new user. Body: {email, password} or {phone, country_code, password}. Returns tokens."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "请求体不是合法 JSON"}})
    
    email = body.get("email") if isinstance(body, dict) else None
    phone = body.get("phone") if isinstance(body, dict) else None
    country_code = body.get("country_code", "") if isinstance(body, dict) else ""
    password = body.get("password") if isinstance(body, dict) else None

    if not isinstance(password, str) or len(password) < 8:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "password 至少要 8 个字符"}})

    # Determine identifier: phone takes priority, email fallback
    identifier = None
    identifier_type = None
    if isinstance(phone, str) and phone.strip():
        phone_clean = phone.strip().replace(" ", "").replace("-", "")
        if not phone_clean.isdigit() or len(phone_clean) < 6:
            return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "phone 格式无效"}})
        cc = country_code.strip() if isinstance(country_code, str) else ""
        identifier = cc + ":" + phone_clean
        identifier_type = "phone"
    elif isinstance(email, str) and email.strip() and "@" in email:
        identifier = email.strip().lower()
        identifier_type = "email"
    else:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "需要提供 email 或 phone + country_code"}})

    identifier_hash = _hash_email(identifier)
    existing = storage.get_user_by_email_hash(identifier_hash)
    if existing is not None:
        msg = "该邮箱已注册" if identifier_type == "email" else "该手机号已注册"
        return JSONResponse(status_code=409, content={"error": {"code": "EXISTS", "message": msg}})

    user_id = str(uuid.uuid4())
    pw_hash = hash_password(password)
    storage.create_user(user_id, identifier_hash, pw_hash)

    tokens = create_jwt(user_id, identifier)
    refresh_hash = _hash_email(tokens["refresh_token"])
    expires_at = (datetime.now(timezone.utc) + _REFRESH_TTL).isoformat()
    storage.create_session(user_id, refresh_hash, expires_at)

    return JSONResponse(content={
        "user_id": user_id,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
    })


@router.post("/auth/login")
async def auth_login(request: Request):
    """Login with email+password or phone+password. Returns tokens."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "请求体不是合法 JSON"}})
    email = body.get("email") if isinstance(body, dict) else None
    phone = body.get("phone") if isinstance(body, dict) else None
    country_code = body.get("country_code", "") if isinstance(body, dict) else ""
    password = body.get("password") if isinstance(body, dict) else None

    if not isinstance(password, str):
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "password 不能为空"}})

    identifier = None
    if isinstance(phone, str) and phone.strip():
        phone_clean = phone.strip().replace(" ", "").replace("-", "")
        cc = country_code.strip() if isinstance(country_code, str) else ""
        identifier = cc + ":" + phone_clean
    elif isinstance(email, str) and email.strip():
        identifier = email.strip().lower()
    else:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "需要提供 email 或 phone"}})

    identifier_hash = _hash_email(identifier)
    user = storage.get_user_by_email_hash(identifier_hash)
    if user is None or not verify_password(password, user["password_hash"]):
        return JSONResponse(status_code=401, content={"error": {"code": "UNAUTHORIZED", "message": "账号或密码错误"}})

    tokens = create_jwt(user["id"], identifier)
    refresh_hash = _hash_email(tokens["refresh_token"])
    expires_at = (datetime.now(timezone.utc) + _REFRESH_TTL).isoformat()
    storage.create_session(user["id"], refresh_hash, expires_at)

    return JSONResponse(content={
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
    })


@router.post("/auth/magic-link")
async def auth_magic_link(request: Request):
    """Request a magic link. Mock: always returns success."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "请求体不是合法 JSON"}})
    email = body.get("email") if isinstance(body, dict) else None
    if not isinstance(email, str) or not email.strip() or "@" not in email:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "email 必须是非空合法邮箱"}})
    return JSONResponse(content={"message": "Magic link sent (mock)"})


@router.get("/auth/verify")
async def auth_verify(token: str = ""):
    """Mock email verification — always returns success."""
    return JSONResponse(content={"verified": True, "user_id": f"mock-{token[:8] or 'xxx'}"})


@router.post("/auth/refresh")
async def auth_refresh(request: Request):
    """Exchange a refresh token for a new access token."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "请求体不是合法 JSON"}})
    refresh_token = body.get("refresh_token") if isinstance(body, dict) else None
    if not isinstance(refresh_token, str) or not refresh_token:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "refresh_token 不能为空"}})

    try:
        payload = verify_jwt(refresh_token, expected_type="refresh")
    except jwt.ExpiredSignatureError:
        return JSONResponse(status_code=401, content={"error": {"code": "UNAUTHORIZED", "message": "Refresh token has expired"}})
    except jwt.InvalidTokenError:
        return JSONResponse(status_code=401, content={"error": {"code": "UNAUTHORIZED", "message": "Invalid refresh token"}})

    # Check session exists and not revoked
    sessions = storage.get_sessions_for_user(payload["sub"])
    token_hash = _hash_email(refresh_token)
    valid_session = None
    for s in sessions:
        if s["refresh_token_hash"] == token_hash and not s["revoked"]:
            dt = datetime.fromisoformat(s["expires_at"])
            if dt > datetime.now(timezone.utc):
                valid_session = s
                break
    if valid_session is None:
        return JSONResponse(status_code=401, content={"error": {"code": "UNAUTHORIZED", "message": "Session not found or revoked"}})

    # Issue new access token (we need email for hash, but we only have email_hash)
    # For refresh, we create a new access token using the existing sub + email_hash from the payload
    now = datetime.now(timezone.utc)
    access_payload = {
        "sub": payload["sub"],
        "email_hash": payload.get("email_hash", ""),
        "iat": now,
        "exp": now + _ACCESS_TTL,
        "type": "access",
    }
    new_access = jwt.encode(access_payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)

    return JSONResponse(content={"access_token": new_access})


@router.post("/auth/forgot-password")
async def auth_forgot_password(request: Request):
    """Request a password reset. Accepts {email} → generates reset token → returns confirmation.
    
    The reset token is stored server-side; this mock returns success regardless
    of whether the email exists (to avoid user enumeration).
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "请求体不是合法 JSON"}})
    email = body.get("email") if isinstance(body, dict) else None
    if not isinstance(email, str) or not email.strip() or "@" not in email:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "email 必须是非空合法邮箱"}})
    identifier_hash = _hash_email(email)
    user = storage.get_user_by_email_hash(identifier_hash)
    if user is not None:
        # Generate and store the reset token silently
        storage.create_reset_token(user["id"])
    # Always return the same message to prevent user enumeration
    return JSONResponse(content={"message": "重置链接已发送"})


@router.post("/auth/reset-password")
async def auth_reset_password(request: Request):
    """Reset password with a token. Accepts {token, new_password}."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "请求体不是合法 JSON"}})
    token = body.get("token") if isinstance(body, dict) else None
    new_password = body.get("new_password") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "token 不能为空"}})
    if not isinstance(new_password, str) or len(new_password) < 8:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "new_password 至少要 8 个字符"}})
    user_id = storage.consume_reset_token(token)
    if user_id is None:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_TOKEN", "message": "重置 token 无效或已过期"}})
    pw_hash = hash_password(new_password)
    storage.update_user_password(user_id, pw_hash)
    return JSONResponse(content={"message": "密码已重置"})


@router.delete("/auth/session")
async def auth_delete_session(request: Request):
    """Invalidate the current session's refresh token."""
    try:
        user_id = await get_current_user(request)
    except AuthError as e:
        return _auth_err_response(e.code, e.message, e.status)
    # Revoke all sessions for the user (simple approach — revoke on logout)
    storage.revoke_all_sessions(user_id)
    return JSONResponse(content={"message": "Session invalidated"}, status_code=200)

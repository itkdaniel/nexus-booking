"""
HMAC-SHA256 JWT authentication middleware.

Accepts Bearer tokens forwarded by the main portfolio gateway.
Admin role required for write/delete operations.

Config injection: call configure_auth(settings) at startup (via create_app) so
verify_token() uses the injected jwt_secret rather than the global get_settings()
fallback. This keeps auth fully consistent with the factory pattern.

Tests can mock `app.auth.get_settings` as before; the module-level reference
is preserved so existing mock.patch() call sites continue to work.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings  # exported for mock.patch("app.auth.get_settings")

_bearer = HTTPBearer(auto_error=False)

# Module-level settings override — set by configure_auth(settings) at startup.
# When not None, takes priority over the global get_settings() singleton.
_settings = None


def configure_auth(settings) -> None:
    """Wire auth to the injected Settings object. Called once at startup."""
    global _settings
    _settings = settings


def _get_settings():
    """Return injected settings or fall back to the module-level get_settings()."""
    if _settings is not None:
        return _settings
    return get_settings()


def _b64url_encode(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    return urlsafe_b64decode(s + "=" * (padding % 4))


def _sign(header_b64: str, payload_b64: str, secret: str) -> str:
    msg = f"{header_b64}.{payload_b64}".encode()
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).digest()
    return _b64url_encode(sig)


def generate_token(payload: dict, secret: str | None = None) -> str:
    """Generate an HMAC-SHA256 JWT (for tests and dev use)."""
    s = secret or _get_settings().jwt_secret
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps({**payload, "iat": int(time.time()), "exp": int(time.time()) + 86400}).encode())
    sig = _sign(header, body, s)
    return f"{header}.{body}.{sig}"


def verify_token(token: str) -> Optional[dict]:
    """Verify token signature + expiry. Returns payload dict or None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig = parts
        expected = _sign(header_b64, payload_b64, _get_settings().jwt_secret)
        if not hmac.compare_digest(expected, sig):
            return None
        payload = json.loads(_b64url_decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


async def get_optional_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[dict]:
    """Returns the JWT payload if a valid token is present, else None."""
    if not creds:
        return None
    return verify_token(creds.credentials)


async def require_auth(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """FastAPI dependency — raises 401 if no valid token."""
    user = await get_optional_user(creds)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Unauthorized", "code": "UNAUTHORIZED", "details": {}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(user: dict = Depends(require_auth)) -> dict:
    """FastAPI dependency — raises 403 if user is not admin."""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "Forbidden — admin role required", "code": "FORBIDDEN", "details": {}},
        )
    return user

"""
Unit tests for HMAC-SHA256 JWT auth helpers.
"""
from __future__ import annotations

import time

import pytest

from app.auth import generate_token, verify_token, configure_auth


@pytest.mark.unit
class TestGenerateToken:
    def test_generates_three_part_jwt(self):
        token = generate_token({"sub": "u1", "role": "user"}, secret="test")
        assert len(token.split(".")) == 3

    def test_different_secrets_produce_different_tokens(self):
        payload = {"sub": "u1", "role": "admin"}
        t1 = generate_token(payload, secret="secret-a")
        t2 = generate_token(payload, secret="secret-b")
        assert t1 != t2

    def test_token_contains_payload(self):
        token = generate_token({"sub": "u42", "role": "admin"}, secret="s")
        import json
        from base64 import urlsafe_b64decode
        parts = token.split(".")
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        decoded = json.loads(urlsafe_b64decode(padded))
        assert decoded["sub"] == "u42"
        assert decoded["role"] == "admin"


@pytest.mark.unit
class TestVerifyToken:
    def test_valid_token_returns_payload(self):
        from app.config import Settings
        cfg = Settings(jwt_secret="test-key", database_url="sqlite+aiosqlite:///:memory:")
        configure_auth(cfg)
        token = generate_token({"sub": "u1", "role": "user"}, secret="test-key")
        payload = verify_token(token)
        assert payload is not None
        assert payload["sub"] == "u1"

    def test_invalid_signature_returns_none(self):
        from app.config import Settings
        cfg = Settings(jwt_secret="wrong-secret", database_url="sqlite+aiosqlite:///:memory:")
        configure_auth(cfg)
        token = generate_token({"sub": "u1", "role": "user"}, secret="secret-a")
        result = verify_token(token)
        assert result is None

    def test_malformed_token_returns_none(self):
        from app.config import Settings
        cfg = Settings(jwt_secret="test", database_url="sqlite+aiosqlite:///:memory:")
        configure_auth(cfg)
        assert verify_token("not.a.token.at.all") is None
        assert verify_token("") is None
        assert verify_token("x.y") is None


@pytest.mark.unit
class TestAdminRequirement:
    """Test that require_admin rejects non-admin users."""

    @pytest.mark.asyncio
    async def test_admin_token_passes(self, admin_token, test_settings):
        configure_auth(test_settings)
        from app.auth import verify_token
        payload = verify_token(admin_token)
        assert payload is not None
        assert payload["role"] == "admin"

    @pytest.mark.asyncio
    async def test_user_token_has_user_role(self, user_token, test_settings):
        configure_auth(test_settings)
        from app.auth import verify_token
        payload = verify_token(user_token)
        assert payload is not None
        assert payload["role"] == "user"

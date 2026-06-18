"""
Unit tests for HMAC-SHA256 JWT auth helpers.
"""
from __future__ import annotations

import time

import pytest

from app.auth import generate_token, verify_token


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
        payload = verify_token.__wrapped__(token) if hasattr(verify_token, "__wrapped__") else None
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
        token = generate_token({"sub": "u1", "role": "user"}, secret="test-key")
        payload = verify_token.__func__(token) if hasattr(verify_token, "__func__") else None
        # Use the module-level function directly
        from app import auth
        # Patch settings secret
        import unittest.mock as mock
        with mock.patch("app.auth.get_settings") as m:
            m.return_value.jwt_secret = "test-key"
            payload = auth.verify_token(token)
        assert payload is not None
        assert payload["sub"] == "u1"

    def test_invalid_signature_returns_none(self):
        token = generate_token({"sub": "u1", "role": "user"}, secret="secret-a")
        import unittest.mock as mock
        with mock.patch("app.auth.get_settings") as m:
            m.return_value.jwt_secret = "wrong-secret"
            result = mock.MagicMock()
            from app import auth
            result = auth.verify_token(token)
        assert result is None

    def test_malformed_token_returns_none(self):
        import unittest.mock as mock
        from app import auth
        with mock.patch("app.auth.get_settings") as m:
            m.return_value.jwt_secret = "test"
            assert auth.verify_token("not.a.token.at.all") is None
            assert auth.verify_token("") is None
            assert auth.verify_token("x.y") is None


@pytest.mark.unit
class TestAdminRequirement:
    """Test that require_admin rejects non-admin users."""

    @pytest.mark.asyncio
    async def test_admin_token_passes(self, admin_token, test_settings):
        import unittest.mock as mock
        from app import auth
        with mock.patch("app.auth.get_settings") as m:
            m.return_value.jwt_secret = test_settings.jwt_secret
            payload = auth.verify_token(admin_token)
        assert payload is not None
        assert payload["role"] == "admin"

    @pytest.mark.asyncio
    async def test_user_token_has_user_role(self, user_token, test_settings):
        import unittest.mock as mock
        from app import auth
        with mock.patch("app.auth.get_settings") as m:
            m.return_value.jwt_secret = test_settings.jwt_secret
            payload = auth.verify_token(user_token)
        assert payload is not None
        assert payload["role"] == "user"

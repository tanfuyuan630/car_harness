"""鉴权特性测试：密码哈希与 JWT 校验。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from jose import jwt

from app.core.auth import create_access_token, get_current_user
from app.core.config import settings
from app.services.user_service import hash_password, verify_password


def test_password_hash_is_salted():
    """相同明文两次哈希结果不同，且都能校验通过。"""
    first = hash_password("Secret123")
    second = hash_password("Secret123")
    assert first != second
    assert verify_password("Secret123", first) is True
    assert verify_password("Secret123", second) is True


def test_verify_password_rejects_wrong_or_invalid():
    """错误密码与非法哈希都返回 False。"""
    hashed = hash_password("Secret123")
    assert verify_password("wrong", hashed) is False
    assert verify_password("Secret123", "not-a-bcrypt-hash") is False


def test_create_access_token_contains_subject():
    """Token 的 sub 为 user_id。"""
    token = create_access_token("u1")
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert payload["sub"] == "u1"
    assert "exp" in payload


def test_get_current_user_requires_token():
    """缺少 Token 直接返回 401。"""
    with pytest.raises(HTTPException) as exc:
        get_current_user(None, None)
    assert exc.value.status_code == 401
    assert exc.value.detail == "未登录"


def test_get_current_user_rejects_invalid_token():
    """非法 Token 返回 401，不访问数据库。"""
    with pytest.raises(HTTPException) as exc:
        get_current_user("invalid-token", None)
    assert exc.value.status_code == 401

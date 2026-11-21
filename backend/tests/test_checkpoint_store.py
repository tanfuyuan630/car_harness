"""Checkpointer 配置测试：连接串、连接参数、memory 模式。"""
from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
from app.services import checkpoint_store


@pytest.fixture(autouse=True)
def reset_state():
    """每个用例前后清空 Checkpointer 单例，避免相互影响。"""
    checkpoint_store._saver = None
    checkpoint_store._context_manager = None
    checkpoint_store._redis_client = None
    yield
    checkpoint_store._saver = None
    checkpoint_store._context_manager = None
    checkpoint_store._redis_client = None


def test_default_checkpointer_is_redis():
    """默认使用 Redis，memory 仅作为测试选项。"""
    assert type(settings).model_fields["CHECKPOINTER_TYPE"].default == "redis"


def test_redis_url_encodes_password(monkeypatch):
    """密码中的特殊字符做 URL 编码，连接串格式正确。"""
    monkeypatch.setattr(settings, "REDIS_HOST", "192.168.137.128")
    monkeypatch.setattr(settings, "REDIS_PORT", 6379)
    monkeypatch.setattr(settings, "REDIS_PASSWORD", "p@ss/word")
    monkeypatch.setattr(settings, "REDIS_DB", 0)
    assert settings.redis_url == "redis://:p%40ss%2Fword@192.168.137.128:6379/0"


def test_redis_url_without_password(monkeypatch):
    """无密码时不带认证段。"""
    monkeypatch.setattr(settings, "REDIS_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "REDIS_PASSWORD", "")
    assert settings.redis_url == "redis://127.0.0.1:6379/0"


def test_connection_args_contain_timeout_and_retry(monkeypatch):
    """连接参数包含 socket 超时与指数退避重试。"""
    monkeypatch.setattr(settings, "REDIS_SOCKET_TIMEOUT_SECONDS", 7)
    monkeypatch.setattr(settings, "REDIS_RETRY_ATTEMPTS", 4)
    args = checkpoint_store.build_connection_args()
    assert args["socket_timeout"] == 7
    assert args["socket_connect_timeout"] == 7
    assert args["retry_on_timeout"] is True
    assert args["retry"]._retries == 4


def test_memory_mode_returns_memory_saver(monkeypatch):
    """memory 模式返回内存 Checkpointer，不连接 Redis。"""
    from langgraph.checkpoint.memory import MemorySaver

    monkeypatch.setattr(settings, "CHECKPOINTER_TYPE", "memory")
    saver = asyncio.run(checkpoint_store.setup_checkpointer())
    assert isinstance(saver, MemorySaver)
    assert checkpoint_store.get_checkpointer() is saver
    assert checkpoint_store.get_redis_client() is None


def test_get_checkpointer_requires_setup():
    """未初始化时直接报错，避免静默丢状态。"""
    with pytest.raises(RuntimeError, match="尚未初始化"):
        checkpoint_store.get_checkpointer()

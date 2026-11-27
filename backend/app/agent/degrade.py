"""依赖降级状态与日志：统一四类依赖的降级记录、请求级档位与进程级组件状态。

降级只写服务端日志，不改变任何接口响应结构、前端展示或 IM 回复文案。
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from enum import Enum
from typing import TYPE_CHECKING, Any

from app.core.config import settings

if TYPE_CHECKING:
    from app.agent.tiering import ComplexityLevel

logger = logging.getLogger(__name__)


class DegradeComponent(str, Enum):
    """可降级的依赖组件。"""

    LLM = "llm"
    RAG = "rag"
    CHECKPOINT = "checkpoint"
    SUBAGENT = "subagent"


def degrade_enabled() -> bool:
    """降级总开关是否开启。"""
    return settings.DEGRADE_ENABLED


def force_degraded() -> bool:
    """是否处于手动强制降级状态；总开关关闭时强制无效。"""
    return settings.DEGRADE_ENABLED and settings.DEGRADE_FORCE


# 请求级：降档后的复杂度档位；None 表示本请求未降档
_degraded_level: ContextVar["ComplexityLevel | None"] = ContextVar(
    "degrade_llm_level", default=None
)
# 请求级：已记录过降级的“组件:原因”集合，避免同一请求重复刷日志
_logged: ContextVar[set[str] | None] = ContextVar("degrade_logged", default=None)
# 进程级：已降级的组件（检查点启动降级、RAG 冷却等）
_components: set[str] = set()


def get_degraded_level() -> "ComplexityLevel | None":
    """返回本请求已降档到的档位，未降档时返回 None。"""
    return _degraded_level.get()


def set_degraded_level(level: "ComplexityLevel") -> None:
    """记录本请求降档后的档位，后续模型调用直接复用。"""
    _degraded_level.set(level)


def reset_request_degrade() -> None:
    """每轮请求开始时清空请求级降档状态。"""
    _degraded_level.set(None)
    _logged.set(None)


def mark_component_degraded(component: DegradeComponent) -> None:
    """标记进程级组件已降级。"""
    _components.add(component.value)


def is_component_degraded(component: DegradeComponent) -> bool:
    """判断进程级组件是否已降级。"""
    return component.value in _components


def log_degrade(
    component: DegradeComponent,
    reason: str,
    *,
    once: bool = False,
    **fields: Any,
) -> None:
    """输出统一降级日志。

    once 为真时，同一请求内同一“组件:原因”只记录一次。
    附加字段按 key=value 追加，禁止传入用户消息原文与模型输出。
    """
    if once:
        logged = _logged.get()
        if logged is None:
            logged = set()
            _logged.set(logged)
        key = f"{component.value}:{reason}"
        if key in logged:
            return
        logged.add(key)

    extra = " ".join(f"{name}={value}" for name, value in fields.items())
    if extra:
        logger.warning("[Degrade] component=%s reason=%s %s", component.value, reason, extra)
    else:
        logger.warning("[Degrade] component=%s reason=%s", component.value, reason)

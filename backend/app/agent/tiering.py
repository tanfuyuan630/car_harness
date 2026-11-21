"""多层模型路由：复杂度分类、档位选择与主 Agent 档位上下文管理。

开关由 LLM_TIER_ENABLED 控制：
- 关闭时调用方不分类，模型统一使用 OPENAI_MODEL；
- 开启时按 simple/moderate/complex 映射 low/medium/high 三档模型。
"""
from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from contextvars import ContextVar
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agent.error_policy import ErrorKind, RecoverableToolError, classify_exception
from app.core.config import settings

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "complexity_classifier.md"
# 子 Agent 分类结果缓存上限：同一委派任务的多轮模型调用只分类一次
_SUBAGENT_CACHE_MAX = 256
_PREVIOUS_TEXT_LIMIT = 500
_CURRENT_TEXT_LIMIT = 2000


class ComplexityLevel(str, Enum):
    """问题复杂度三档。"""

    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class ComplexityDecision(BaseModel):
    """分类器结构化输出。"""

    level: ComplexityLevel
    reason: str = Field(default="", max_length=60)


_TIER_BY_LEVEL = {
    ComplexityLevel.SIMPLE: "low",
    ComplexityLevel.MODERATE: "medium",
    ComplexityLevel.COMPLEX: "high",
}
_LEVEL_BY_TIER = {tier: level for level, tier in _TIER_BY_LEVEL.items()}

# 主 Agent 档位随请求上下文隔离；子 Agent 不复用该值，按委派任务单独分类
_main_level: ContextVar[ComplexityLevel | None] = ContextVar("llm_main_tier", default=None)
# 当前请求线程 ID：模型回调元数据缺失时用于日志定位
_main_thread: ContextVar[str | None] = ContextVar("llm_main_thread", default=None)

# 子 Agent 任务描述哈希 -> 档位，进程内 LRU
_subagent_cache: OrderedDict[str, ComplexityLevel] = OrderedDict()


def tier_enabled() -> bool:
    """分档开关是否开启。"""
    return settings.LLM_TIER_ENABLED


def tier_name(level: ComplexityLevel) -> str:
    """复杂度对应的档位名：low/medium/high。"""
    return _TIER_BY_LEVEL[level]


def model_for_level(level: ComplexityLevel) -> str:
    """档位对应的模型名，全部来自配置。"""
    if level is ComplexityLevel.SIMPLE:
        return settings.LLM_TIER_LOW_MODEL
    if level is ComplexityLevel.MODERATE:
        return settings.LLM_TIER_MEDIUM_MODEL
    return settings.LLM_TIER_HIGH_MODEL


def set_main_tier(level: ComplexityLevel, thread_id: str | None = None) -> None:
    """设置当前请求的主 Agent 档位，并记录线程 ID 供日志使用。"""
    _main_level.set(level)
    if thread_id:
        _main_thread.set(thread_id)


def get_main_tier() -> ComplexityLevel | None:
    """读取当前请求的主 Agent 档位，未设置时返回 None。"""
    return _main_level.get()


def get_main_thread() -> str | None:
    """读取当前请求的线程 ID，未设置时返回 None。"""
    return _main_thread.get()


def reset_main_tier() -> None:
    """请求结束后清理主 Agent 档位与线程上下文。"""
    _main_level.set(None)
    _main_thread.set(None)


def log_decision(
    source: str,
    decision: ComplexityDecision,
    thread_id: str,
    subagent_name: str = "-",
) -> None:
    """记录一次档位判定；不记录消息原文与模型输出。"""
    logger.info(
        "[LLMTier] thread=%s source=%s subagent=%s complexity=%s tier=%s model=%s reason=%s",
        thread_id or "-",
        source,
        subagent_name or "-",
        decision.level.value,
        tier_name(decision.level),
        model_for_level(decision.level),
        decision.reason or "-",
    )


async def prepare_main_tier(text: str, previous_text: str, thread_id: str) -> ComplexityLevel:
    """入口分类：判定当前问题复杂度并写入主 Agent 档位上下文。"""
    decision = await classify_complexity(text, previous_text)
    set_main_tier(decision.level, thread_id)
    log_decision("main", decision, thread_id)
    return decision.level


def set_thread_tier(tier_value: str | None, thread_id: str, scenario: str) -> ComplexityLevel:
    """恢复/重试时复用线程最近档位，不重新分类。"""
    level = _LEVEL_BY_TIER.get((tier_value or "").strip().lower())
    if level is None:
        logger.warning(
            "[LLMTier] thread=%s scenario=%s 线程元数据缺少有效档位(%r)，按 medium 执行",
            thread_id,
            scenario,
            tier_value,
        )
        level = ComplexityLevel.MODERATE
    set_main_tier(level, thread_id)
    logger.info(
        "[LLMTier] thread=%s source=%s complexity=%s tier=%s model=%s reason=-",
        thread_id or "-",
        scenario,
        level.value,
        tier_name(level),
        model_for_level(level),
    )
    return level


@lru_cache(maxsize=1)
def _classifier_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit]


async def classify_complexity(text: str, previous_text: str = "") -> ComplexityDecision:
    """调用轻量分类模型判定复杂度；解析失败按可恢复错误上抛，不做默认档兜底。"""
    from app.agent.llm import get_llm

    llm = get_llm(settings.LLM_CLASSIFIER_MODEL, settings.LLM_CLASSIFIER_MAX_TOKENS)
    structured = llm.with_structured_output(ComplexityDecision)

    parts: list[str] = []
    if previous_text and previous_text.strip():
        parts.append(f"上一条助手回复（节选）：\n{_truncate(previous_text, _PREVIOUS_TEXT_LIMIT)}")
    parts.append(f"用户最新消息：\n{_truncate(text, _CURRENT_TEXT_LIMIT)}")
    messages = [
        SystemMessage(content=_classifier_prompt()),
        HumanMessage(content="\n\n".join(parts)),
    ]

    try:
        result = await structured.ainvoke(messages)
        return result if isinstance(result, ComplexityDecision) else ComplexityDecision.model_validate(result)
    except Exception as exc:
        # 临时错误保持原类型，交由上层按现有错误分级处理
        if classify_exception(exc) == ErrorKind.TRANSIENT:
            raise
        raise RecoverableToolError(f"复杂度分类失败: {str(exc)[:200]}") from exc


def _content_text(content: Any) -> str:
    """把消息内容统一成纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content
        )
    return str(content or "")


def _first_human_text(messages: list[BaseMessage]) -> str:
    """取第一条 HumanMessage：子 Agent 的委派任务描述。"""
    for message in messages:
        if isinstance(message, HumanMessage):
            return _content_text(message.content)
    return ""


def _last_human_text(messages: list[BaseMessage]) -> str:
    """取最后一条 HumanMessage：主 Agent 的当前用户消息。"""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return _content_text(message.content)
    return ""


def _cache_get(key: str) -> ComplexityLevel | None:
    level = _subagent_cache.get(key)
    if level is not None:
        _subagent_cache.move_to_end(key)
    return level


def _cache_put(key: str, level: ComplexityLevel) -> None:
    _subagent_cache[key] = level
    _subagent_cache.move_to_end(key)
    while len(_subagent_cache) > _SUBAGENT_CACHE_MAX:
        _subagent_cache.popitem(last=False)


def _task_key(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


async def resolve_subagent_level(
    messages: list[BaseMessage], thread_id: str, subagent_name: str = "-"
) -> ComplexityLevel:
    """子 Agent 按委派任务描述选档；同一任务后续轮次复用缓存结果。"""
    text = _first_human_text(messages) or _last_human_text(messages)
    key = _task_key(text)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    decision = await classify_complexity(text)
    log_decision("subagent", decision, thread_id, subagent_name)
    _cache_put(key, decision.level)
    return decision.level


async def resolve_main_level(messages: list[BaseMessage], thread_id: str) -> ComplexityLevel:
    """主 Agent 档位：入口已设置时直接复用，否则按当前消息惰性分类一次。"""
    level = get_main_tier()
    if level is not None:
        return level

    decision = await classify_complexity(_last_human_text(messages))
    set_main_tier(decision.level, thread_id)
    log_decision("main", decision, thread_id)
    return decision.level

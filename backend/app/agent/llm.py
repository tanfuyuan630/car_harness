"""LLM 客户端工厂：按配置返回模型实例，支持 OpenAI 兼容端点。

临时错误（限流、超时、连接失败、5xx）在模型调用层做有限重试；
流式响应一旦已输出 token，不再整段重试，交由上层错误恢复流程处理。

多层模型路由：TieredChatOpenAI 在每次模型调用前解析目标档位，
主 Agent 使用请求入口分类结果，子 Agent 按其委派任务描述分类；
解析结果指向模型池中的实例，不修改共享模型对象。
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Literal

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app.agent.error_policy import (
    ErrorKind,
    TransientExhausted,
    classify_exception,
    max_llm_attempts,
    transient_backoff,
)
from app.agent.tiering import (
    get_main_thread,
    model_for_level,
    resolve_main_level,
    resolve_subagent_level,
)
from app.core.config import settings


class RetryingChatOpenAI(ChatOpenAI):
    """在模型调用层对临时错误做重试的 ChatOpenAI。"""

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception(lambda exc: classify_exception(exc) == ErrorKind.TRANSIENT),
            stop=stop_after_attempt(max_llm_attempts()),
            wait=wait_exponential_jitter(initial=0.5, max=8),
            reraise=True,
        ):
            with attempt:
                return await super()._agenerate(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )
        raise TransientExhausted("模型调用重试耗尽")

    async def _astream(
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        attempts = 0
        while True:
            started = False
            try:
                async for chunk in super()._astream(*args, **kwargs):
                    started = True
                    yield chunk
                return
            except Exception as exc:
                # 已输出部分内容后不重试，避免重复 token
                if (
                    started
                    or classify_exception(exc) != ErrorKind.TRANSIENT
                    or attempts + 1 >= max_llm_attempts()
                ):
                    raise
                attempts += 1
                await asyncio.sleep(transient_backoff(attempts))


class TieredChatOpenAI(RetryingChatOpenAI):
    """按复杂度档位动态选择模型的 ChatOpenAI。

    主 Agent 复用请求入口写入的档位；子 Agent 按首条委派任务分类，
    同一任务后续调用复用缓存。开关关闭时固定使用 OPENAI_MODEL。
    """

    tier_role: Literal["main", "subagent"] = "main"

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        target = await self._resolve_target(messages, run_manager)
        if target is self:
            return await super()._agenerate(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )
        return await target._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        target = await self._resolve_target(messages, run_manager)
        if target is self:
            async for chunk in super()._astream(
                messages, stop=stop, run_manager=run_manager, **kwargs
            ):
                yield chunk
            return
        async for chunk in target._astream(
            messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            yield chunk

    async def _resolve_target(
        self,
        messages: list[BaseMessage],
        run_manager: AsyncCallbackManagerForLLMRun | None,
    ) -> RetryingChatOpenAI:
        """解析本次调用应使用的模型实例；关闭分档时返回自身。"""
        if not settings.LLM_TIER_ENABLED:
            return self

        metadata = getattr(run_manager, "metadata", None) or {}
        # 流式子图的回调元数据可能缺少 thread_id，回退到请求上下文中的线程
        thread_id = str(metadata.get("thread_id") or get_main_thread() or "-")
        if self.tier_role == "subagent":
            level = await resolve_subagent_level(
                messages, thread_id, _subagent_name(metadata)
            )
        else:
            level = await resolve_main_level(messages, thread_id)

        model = model_for_level(level)
        if model == self.model_name:
            return self
        return get_llm(model)


def _subagent_name(metadata: dict[str, Any]) -> str:
    """从回调元数据推断子 Agent 名称，取不到时返回占位符。"""
    name = metadata.get("lc_agent_name")
    if isinstance(name, str) and name:
        return name
    namespace = str(metadata.get("checkpoint_ns", "") or "")
    return namespace.split(":")[0] if namespace else "-"


def _llm_kwargs(model: str | None, max_tokens: int | None = None) -> dict:
    """构造模型参数，只传非 None 的可选项。"""
    kwargs: dict = {
        "model": model or settings.OPENAI_MODEL,
        "api_key": settings.OPENAI_API_KEY,
        "base_url": settings.OPENAI_API_BASE,
        "timeout": settings.OPENAI_TIMEOUT_SECONDS,
        # 重试由 RetryingChatOpenAI 控制，关闭 SDK 自带重试避免叠加
        "max_retries": 0,
    }
    if settings.LLM_TEMPERATURE is not None:
        kwargs["temperature"] = settings.LLM_TEMPERATURE
    if settings.LLM_MAX_TOKENS is not None:
        kwargs["max_tokens"] = settings.LLM_MAX_TOKENS
    if settings.LLM_TOP_P is not None:
        kwargs["top_p"] = settings.LLM_TOP_P
    # 分类器等场景需要更小的输出上限，覆盖全局配置
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return kwargs


def create_llm(model: str | None = None, max_tokens: int | None = None) -> RetryingChatOpenAI:
    """根据配置创建带临时错误重试的 OpenAI 兼容 ChatModel 实例。"""
    return RetryingChatOpenAI(**_llm_kwargs(model, max_tokens))


_llm_pool: dict[tuple[str, int | None], RetryingChatOpenAI] = {}


def get_llm(model: str | None = None, max_tokens: int | None = None) -> RetryingChatOpenAI:
    """按模型名缓存模型实例，避免重复构造。"""
    name = model or settings.OPENAI_MODEL
    key = (name, max_tokens)
    instance = _llm_pool.get(key)
    if instance is None:
        instance = create_llm(name, max_tokens)
        _llm_pool[key] = instance
    return instance


def create_tiered_llm(role: Literal["main", "subagent"]) -> TieredChatOpenAI:
    """创建分档模型实例，role 决定按入口档位还是委派任务选档。"""
    return TieredChatOpenAI(**_llm_kwargs(settings.OPENAI_MODEL), tier_role=role)

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

from app.agent.degrade import (
    DegradeComponent,
    degrade_enabled,
    force_degraded,
    get_degraded_level,
    log_degrade,
    set_degraded_level,
)
from app.agent.error_policy import (
    ErrorKind,
    TransientExhausted,
    classify_exception,
    max_llm_attempts,
    transient_backoff,
)
from app.agent.tiering import (
    ComplexityLevel,
    get_main_thread,
    model_for_level,
    resolve_main_level,
    resolve_subagent_level,
    tier_name,
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

    降级开启时，当前档位模型调用失败且尚未输出 token，逐级降档重试。
    """

    tier_role: Literal["main", "subagent"] = "main"

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        level = await self._resolve_level(messages, run_manager)
        if level is None:
            return await RetryingChatOpenAI._agenerate(
                self, messages, stop=stop, run_manager=run_manager, **kwargs
            )

        candidates = self._candidates(level)
        last_index = len(candidates) - 1
        for index, candidate in enumerate(candidates):
            target = self._model_of(candidate)
            try:
                result = await RetryingChatOpenAI._agenerate(
                    target, messages, stop=stop, run_manager=run_manager, **kwargs
                )
            except Exception:
                # 还有更低档时才继续降档，最后一档失败直接上抛原始异常
                if index >= last_index:
                    raise
                continue
            if index > 0:
                self._record_degrade(level, candidate, run_manager)
            return result
        raise TransientExhausted("模型降档链已耗尽")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        level = await self._resolve_level(messages, run_manager)
        if level is None:
            async for chunk in RetryingChatOpenAI._astream(
                self, messages, stop=stop, run_manager=run_manager, **kwargs
            ):
                yield chunk
            return

        candidates = self._candidates(level)
        last_index = len(candidates) - 1
        for index, candidate in enumerate(candidates):
            target = self._model_of(candidate)
            started = False
            try:
                async for chunk in RetryingChatOpenAI._astream(
                    target, messages, stop=stop, run_manager=run_manager, **kwargs
                ):
                    started = True
                    yield chunk
            except Exception:
                # 已输出 token 时不降档重试，避免重复内容
                if started or index >= last_index:
                    raise
                continue
            if index > 0:
                self._record_degrade(level, candidate, run_manager)
            return

    async def _resolve_level(
        self,
        messages: list[BaseMessage],
        run_manager: AsyncCallbackManagerForLLMRun | None,
    ) -> ComplexityLevel | None:
        """解析本次调用使用的档位；关闭分档时返回 None 表示使用默认模型。"""
        if not settings.LLM_TIER_ENABLED:
            return None

        metadata = getattr(run_manager, "metadata", None) or {}
        thread_id = str(metadata.get("thread_id") or get_main_thread() or "-")

        if force_degraded():
            log_degrade(
                DegradeComponent.LLM,
                "forced",
                once=True,
                thread=thread_id,
                role=self.tier_role,
                tier="low",
            )
            return ComplexityLevel.SIMPLE

        degraded = get_degraded_level()
        if degraded is not None:
            return degraded

        if self.tier_role == "subagent":
            return await resolve_subagent_level(
                messages, thread_id, _subagent_name(metadata)
            )
        return await resolve_main_level(messages, thread_id)

    def _candidates(self, level: ComplexityLevel) -> tuple[ComplexityLevel, ...]:
        """本次调用的档位尝试顺序：首个为选定档位，其后为逐级降档。"""
        if not degrade_enabled():
            return (level,)
        return (level, *_FALLBACK_LEVELS[level])

    def _model_of(self, level: ComplexityLevel) -> RetryingChatOpenAI:
        """档位对应的模型实例；与默认模型同名时复用自身。"""
        model = model_for_level(level)
        if model == self.model_name:
            return self
        return get_llm(model)

    def _record_degrade(
        self,
        from_level: ComplexityLevel,
        to_level: ComplexityLevel,
        run_manager: AsyncCallbackManagerForLLMRun | None,
    ) -> None:
        """记录一次降档并写入请求级状态，本请求后续调用直接复用新档位。"""
        set_degraded_level(to_level)
        metadata = getattr(run_manager, "metadata", None) or {}
        thread_id = str(metadata.get("thread_id") or get_main_thread() or "-")
        log_degrade(
            DegradeComponent.LLM,
            "model_failed",
            once=True,
            thread=thread_id,
            role=self.tier_role,
            from_tier=tier_name(from_level),
            to_tier=tier_name(to_level),
            model=model_for_level(to_level),
        )


# 档位降级链：高档可降到中档与低档，中档只能降到低档，低档无更低档
_FALLBACK_LEVELS: dict[ComplexityLevel, tuple[ComplexityLevel, ...]] = {
    ComplexityLevel.COMPLEX: (ComplexityLevel.MODERATE, ComplexityLevel.SIMPLE),
    ComplexityLevel.MODERATE: (ComplexityLevel.SIMPLE,),
    ComplexityLevel.SIMPLE: (),
}


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

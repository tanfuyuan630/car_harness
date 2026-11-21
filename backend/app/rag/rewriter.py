"""查询改写组件：调用 OpenAI 兼容端点的大模型生成同义检索查询。

模块级单例，首次调用时创建并缓存，避免每次检索重复初始化客户端。
"""
from __future__ import annotations

from typing import Any

from llama_index.core.base.llms.types import LLMMetadata
from llama_index.llms.openai import OpenAI

from app.core.config import settings

# 兼容端点模型的上下文窗口，仅用于描述模型元数据
_COMPAT_CONTEXT_WINDOW = 131072

# 模块级单例缓存
_rewrite_llm: OpenAI | None = None


class _CompatOpenAI(OpenAI):
    """适配 OpenAI 兼容端点与自定义模型名（如 kimi-k3）。

    - llama-index 构建调用追踪负载时会按模型名查询内置 OpenAI 模型表，
      自定义模型名会报错，因此覆写元数据；
    - 部分模型不支持 temperature，因此请求体中不携带该参数。
    """

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=_COMPAT_CONTEXT_WINDOW,
            num_output=self.max_tokens or -1,
            is_chat_model=True,
            is_function_calling_model=False,
            model_name=self.model,
        )

    def _get_model_kwargs(self, **kwargs: Any) -> dict[str, Any]:
        """请求体中去掉 temperature：部分模型（如 kimi-k3）不支持该参数。"""
        model_kwargs = super()._get_model_kwargs(**kwargs)
        model_kwargs.pop("temperature", None)
        return model_kwargs


def get_rewrite_llm() -> OpenAI:
    """获取查询改写用 LLM 实例，首次调用时按配置创建并缓存。"""
    global _rewrite_llm
    if _rewrite_llm is None:
        # 构造函数不传 temperature/max_tokens；temperature 在请求体中由子类移除
        _rewrite_llm = _CompatOpenAI(
            model=settings.OPENAI_MODEL,
            api_base=settings.OPENAI_API_BASE,
            api_key=settings.OPENAI_API_KEY,
        )
    return _rewrite_llm

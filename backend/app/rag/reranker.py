"""Rerank 组件：调用 DashScope 文本重排模型对召回结果重排序。

模块级单例，首次调用时创建并缓存，避免每次检索重复初始化客户端。
"""
from __future__ import annotations

from llama_index.postprocessor.dashscope_rerank import DashScopeRerank

from app.core.config import settings

# 模块级单例缓存
_reranker: DashScopeRerank | None = None


def get_reranker() -> DashScopeRerank:
    """获取 Reranker 实例，首次调用时按配置创建并缓存。"""
    global _reranker
    if _reranker is None:
        _reranker = DashScopeRerank(
            model=settings.RAG_RERANK_MODEL,
            top_n=settings.RAG_RERANK_TOP_N,
            api_key=settings.OPENAI_API_KEY,
        )
    return _reranker

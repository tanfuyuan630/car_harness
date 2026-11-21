"""Embedding 组件：通过 OpenAI 兼容端点调用文本向量模型。

模块级单例，首次调用时创建并缓存，避免每次检索重复初始化客户端。
"""
from __future__ import annotations

from llama_index.embeddings.openai_like import OpenAILikeEmbedding

from app.core.config import settings

# 模块级单例缓存
_embedding: OpenAILikeEmbedding | None = None


def get_embedding() -> OpenAILikeEmbedding:
    """获取 Embedding 实例，首次调用时按配置创建并缓存。"""
    global _embedding
    if _embedding is None:
        _embedding = OpenAILikeEmbedding(
            model_name=settings.RAG_EMBEDDING_MODEL,
            api_base=settings.OPENAI_API_BASE,
            api_key=settings.OPENAI_API_KEY,
            embed_batch_size=10,
        )
    return _embedding

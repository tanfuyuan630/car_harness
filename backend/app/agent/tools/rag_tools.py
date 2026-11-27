"""领域知识库工具：为每个业务领域构造固定检索范围的检索工具。"""
from __future__ import annotations

import json

from langchain_core.tools import StructuredTool

from app.agent.degrade import DegradeComponent, degrade_enabled, force_degraded, log_degrade
from app.rag.domains import DOMAIN_BY_KEY
from app.rag.service import rag_service


def build_domain_knowledge_tool(domain: str) -> StructuredTool:
    """构造只检索指定领域的知识库工具。

    领域由闭包固定，不作为工具参数暴露给模型，避免子 Agent 越域检索。
    检索异常且降级开启时返回空结果，保证子 Agent 继续回答。
    """
    spec = DOMAIN_BY_KEY[domain]

    def _search(query: str, top_k: int = 4) -> str:
        """检索本领域知识库文档，返回片段、来源文件名与相关性分数。"""
        if force_degraded():
            return json.dumps({"results": [], "degraded": True}, ensure_ascii=False)
        try:
            results = rag_service.retrieve(query, top_k=top_k, domain=domain)
        except Exception as exc:
            if not degrade_enabled():
                raise
            log_degrade(
                DegradeComponent.RAG,
                "tool_failed",
                domain=domain,
                error=str(exc)[:150],
                once=True,
            )
            return json.dumps({"results": [], "degraded": True}, ensure_ascii=False)
        return json.dumps(results, ensure_ascii=False, indent=2)

    return StructuredTool.from_function(
        func=_search,
        name="search_knowledge_base",
        description=(
            f"检索「{spec.title}」领域的知识库文档。"
            "传入检索问题或关键词，返回相关片段、来源文件名与相关性分数。"
        ),
    )

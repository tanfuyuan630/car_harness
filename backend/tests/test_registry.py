"""Agent 注册中心特性测试：工具开关与子 Agent 声明。"""
from __future__ import annotations

from app.agent.registry import AgentRegistry
from app.core.config import settings


def test_acp_tool_follows_switch(monkeypatch):
    """ACP 工具随 ACP_ENABLED 开关注册或移除。"""
    monkeypatch.setattr(settings, "ACP_ENABLED", True)
    enabled_names = {tool.name for tool in AgentRegistry().tools}
    assert "generate_file_via_acp" in enabled_names
    assert {"list_files_tool", "read_file_tool", "write_file_tool"} <= enabled_names

    monkeypatch.setattr(settings, "ACP_ENABLED", False)
    disabled_names = {tool.name for tool in AgentRegistry().tools}
    assert "generate_file_via_acp" not in disabled_names


def test_subagents_skip_domains_when_rag_disabled(monkeypatch):
    """RAG 关闭时只保留车型专家，且提示词非空。"""
    monkeypatch.setattr(settings, "RAG_ENABLED", False)
    monkeypatch.setattr(settings, "ENABLED_SUBAGENTS", "")
    subagents = AgentRegistry().subagents
    assert [item["name"] for item in subagents] == ["car_model_expert"]
    assert subagents[0]["system_prompt"].strip()


def test_enabled_subagents_filter(monkeypatch):
    """ENABLED_SUBAGENTS 可限定注册的子 Agent。"""
    monkeypatch.setattr(settings, "RAG_ENABLED", False)
    monkeypatch.setattr(settings, "ENABLED_SUBAGENTS", "not_exists")
    assert AgentRegistry().subagents == []

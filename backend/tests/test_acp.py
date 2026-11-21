"""ACP 客户端与文件生成工具特性测试：协议交互、越界拦截、超时与注册开关。"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.agent.tools import acp_file_tools
from app.agent.tools.acp_file_tools import generate_file_via_acp
from app.core.config import settings
from app.services.acp_client import ACPClient, ACPError


def test_client_full_interaction(mock_acp, workspace):
    """完成握手、权限自动授权、工作区内写文件，并拦截越界写入。"""
    target = workspace / "报告.md"
    result = asyncio.run(
        ACPClient().run_prompt(f"生成文件\n目标文件绝对路径：{target}\n内容要求：测试")
    )

    assert result["stop_reason"] == "end_turn"
    assert result["agent_text"] == "文件已生成"
    assert result["tool_call_count"] == 1
    assert target.read_text(encoding="utf-8").startswith("# 测试文件")

    state = json.loads(
        (mock_acp["out_dir"] / "state.json").read_text(encoding="utf-8")
    )
    assert state["permission_option"] == "allow-1"
    assert state["traversal_blocked"] is True
    assert not (workspace.parent / "forbidden.md").exists()
    assert (mock_acp["out_dir"] / "cwd.txt").read_text(encoding="utf-8") == str(
        workspace.resolve()
    )


def test_resolve_workspace_path_rejects_outside(workspace):
    """相对路径越界与绝对路径越界都返回 None。"""
    client = ACPClient()
    assert client._resolve_workspace_path("../outside.md") is None
    assert client._resolve_workspace_path(str(workspace.parent / "outside.md")) is None
    assert client._resolve_workspace_path("sub/report.md") == (workspace / "sub/report.md").resolve()


def test_client_timeout(slow_acp):
    """服务端长时间无响应时抛出超时错误。"""
    with pytest.raises(ACPError, match="超时"):
        asyncio.run(ACPClient().run_prompt("任意任务"))


def test_client_missing_command(monkeypatch):
    """命令不存在时返回明确的安装提示。"""
    monkeypatch.setattr(settings, "ACP_COMMAND", "definitely-not-exists-cli")
    with pytest.raises(ACPError, match="未找到命令"):
        asyncio.run(ACPClient().run_prompt("任意任务"))


def test_tool_rejects_invalid_filename(workspace):
    """绝对路径、包含 .. 或空文件名直接拒绝。"""
    for name in ["", "../x.md", str(workspace / "x.md"), "a/../../x.md"]:
        result = asyncio.run(
            generate_file_via_acp.ainvoke({"filename": name, "instruction": "内容"})
        )
        assert result.startswith("错误：filename")


def test_tool_success(mock_acp, workspace):
    """工具返回文件路径与大小，文件内容由 ACP 写入。"""
    result = asyncio.run(
        generate_file_via_acp.ainvoke({"filename": "方案.md", "instruction": "写一份方案"})
    )
    payload = json.loads(result)
    target = workspace / "方案.md"

    assert payload["status"] == "ok"
    assert payload["path"] == "方案.md"
    assert payload["size"] == target.stat().st_size
    assert target.read_text(encoding="utf-8") == "# 测试文件\nACP 写入成功\n"


def test_tool_reports_missing_output(monkeypatch, workspace):
    """ACP 正常结束但没有产物时返回错误。"""

    class FakeClient:
        async def run_prompt(self, prompt: str) -> dict:
            return {"stop_reason": "end_turn", "agent_text": "", "tool_call_count": 0}

    monkeypatch.setattr(acp_file_tools, "ACPClient", FakeClient)
    result = asyncio.run(
        generate_file_via_acp.ainvoke({"filename": "空.md", "instruction": "内容"})
    )
    assert result == "错误：ACP 执行结束但未生成文件 空.md"

"""pytest 公共配置与夹具：隔离数据目录、工作区与 mock ACP 服务端。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 保证以 backend 为工作目录导入应用，且 .env 与相对路径解析一致
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app.core.config import settings  # noqa: E402

# mock ACP 服务端：验证握手、权限请求、文件写入与越界拦截
MOCK_ACP_SOURCE = '''
import json
import sys
from pathlib import Path

STATE = {"prompt_id": None, "target": None, "permission_option": None, "traversal_blocked": None}
OUT_DIR = Path(sys.argv[1]).resolve()


def send(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\\n")
    sys.stdout.flush()


def notify(update):
    send({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "sess_mock", "update": update}})


def parse_target(text):
    for line in text.splitlines():
        if line.startswith("目标文件绝对路径："):
            return line.split("：", 1)[1].strip()
    return None


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method = msg.get("method")
    msg_id = msg.get("id")

    if method == "initialize":
        send({"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": 1,
            "agentCapabilities": {},
            "agentInfo": {"name": "mock-agent", "version": "0.0.1"},
            "authMethods": [],
        }})
    elif method == "session/new":
        (OUT_DIR / "cwd.txt").write_text(msg["params"]["cwd"], encoding="utf-8")
        send({"jsonrpc": "2.0", "id": msg_id, "result": {"sessionId": "sess_mock"}})
    elif method == "session/prompt":
        STATE["prompt_id"] = msg_id
        STATE["target"] = parse_target(msg["params"]["prompt"][0]["text"])
        send({"jsonrpc": "2.0", "id": 900, "method": "session/request_permission", "params": {
            "sessionId": "sess_mock",
            "toolCall": {"toolCallId": "call_1"},
            "options": [
                {"optionId": "reject-1", "name": "Reject", "kind": "reject_once"},
                {"optionId": "allow-1", "name": "Allow once", "kind": "allow_once"},
            ],
        }})
    elif msg_id == 900:
        STATE["permission_option"] = msg.get("result", {}).get("outcome", {}).get("optionId")
        send({"jsonrpc": "2.0", "id": 901, "method": "fs/write_text_file", "params": {
            "sessionId": "sess_mock", "path": STATE["target"],
            "content": "# 测试文件\\nACP 写入成功\\n",
        }})
    elif msg_id == 901:
        send({"jsonrpc": "2.0", "id": 902, "method": "fs/write_text_file", "params": {
            "sessionId": "sess_mock", "path": str(OUT_DIR.parent / "forbidden.md"),
            "content": "越界内容",
        }})
    elif msg_id == 902:
        STATE["traversal_blocked"] = "error" in msg
        notify({"sessionUpdate": "tool_call", "toolCallId": "call_1", "title": "写文件", "status": "in_progress"})
        notify({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "文件已生成"}})
        notify({"sessionUpdate": "tool_call_update", "toolCallId": "call_1", "status": "completed"})
        (OUT_DIR / "state.json").write_text(json.dumps(STATE, ensure_ascii=False), encoding="utf-8")
        send({"jsonrpc": "2.0", "id": STATE["prompt_id"], "result": {"stopReason": "end_turn"}})
'''

# 慢速 ACP 服务端：用于验证超时终止
SLOW_ACP_SOURCE = '''
import json
import sys
import time

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method = msg.get("method")
    if method == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": 1, "agentCapabilities": {}, "authMethods": []}}), flush=True)
    elif method == "session/new":
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"sessionId": "sess_slow"}}), flush=True)
    elif method == "session/prompt":
        time.sleep(60)
'''


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    """把 DATA_DIR 指向临时目录，避免读写项目真实数据。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "DATA_DIR", str(data_dir))
    return data_dir


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """把 WORKSPACE_DIR 指向临时目录。"""
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setattr(settings, "WORKSPACE_DIR", str(ws))
    return ws


@pytest.fixture
def mock_acp(tmp_path, monkeypatch):
    """启动 mock ACP 服务端的配置，返回脚本与输出目录。"""
    script = tmp_path / "mock_acp_agent.py"
    script.write_text(MOCK_ACP_SOURCE, encoding="utf-8")
    out_dir = tmp_path / "mock_out"
    out_dir.mkdir()
    monkeypatch.setattr(settings, "ACP_COMMAND", sys.executable)
    monkeypatch.setattr(settings, "ACP_ARGS", f"{script} {out_dir}")
    monkeypatch.setattr(settings, "ACP_TIMEOUT_SECONDS", 20)
    return {"script": script, "out_dir": out_dir}


@pytest.fixture
def slow_acp(tmp_path, monkeypatch):
    """启动慢速 ACP 服务端的配置，用于超时测试。"""
    script = tmp_path / "slow_acp_agent.py"
    script.write_text(SLOW_ACP_SOURCE, encoding="utf-8")
    monkeypatch.setattr(settings, "ACP_COMMAND", sys.executable)
    monkeypatch.setattr(settings, "ACP_ARGS", str(script))
    monkeypatch.setattr(settings, "ACP_TIMEOUT_SECONDS", 2)
    return script

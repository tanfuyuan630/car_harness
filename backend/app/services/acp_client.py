"""ACP（Agent Client Protocol）客户端：以子进程方式连接本地 TRAE CLI。

协议要点：
- stdio 传输，消息为换行分隔的 JSON-RPC 2.0，UTF-8 编码；
- 客户端先 initialize，再 session/new，最后通过 session/prompt 下发任务；
- Agent 反向调用 fs/read_text_file、fs/write_text_file 时由本客户端处理，
  所有文件读写限定在 workspace 目录内；
- 权限请求按自动授权策略选择 allow_once（缺失时选 allow_always）。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

CLIENT_INFO = {
    "name": "car-harness",
    "title": "汽车销售助手 Agent Harness",
    "version": "1.0.0",
}

# ACP 错误码：需要认证
AUTH_REQUIRED_CODE = -32000

# stdout 单行报文上限：ACP 服务端的 session/new 可能返回较大的模型与模式配置，
# asyncio 默认 64KB 会触发 LimitOverrunError，导致读取任务中断
STREAM_LIMIT = 8 * 1024 * 1024


class ACPError(RuntimeError):
    """ACP 调用失败，消息可直接展示给用户。"""


class ACPClient:
    """单次任务使用的 ACP 客户端，调用结束后关闭子进程。"""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 0
        self._session_id: str | None = None
        self._stop_reason = ""
        self._agent_text: list[str] = []
        self._tool_calls: dict[str, dict[str, Any]] = {}

    # ---------------- 对外入口 ----------------

    async def run_prompt(self, prompt: str) -> dict[str, Any]:
        """执行一次完整对话轮次，返回停止原因与 Agent 文本摘要。"""
        try:
            await asyncio.wait_for(
                self._run_prompt(prompt),
                timeout=settings.ACP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as e:
            raise ACPError(
                f"ACP 生成超时（超过 {settings.ACP_TIMEOUT_SECONDS} 秒）"
            ) from e
        finally:
            await self.close()

        return {
            "stop_reason": self._stop_reason,
            "agent_text": "".join(self._agent_text).strip(),
            "tool_call_count": len(self._tool_calls),
        }

    async def _run_prompt(self, prompt: str) -> None:
        await self._start()
        await self._initialize()
        self._session_id = await self._create_session()
        result = await self._request(
            "session/prompt",
            {
                "sessionId": self._session_id,
                "prompt": [{"type": "text", "text": prompt}],
            },
        )
        self._stop_reason = result.get("stopReason", "")

    # ---------------- 进程管理 ----------------

    def _launch_command(self) -> list[str]:
        """解析启动命令；Windows 下的 .cmd/.bat 包装脚本需通过 cmd /c 启动。"""
        command = settings.ACP_COMMAND
        resolved = shutil.which(command) or command
        args = [a for a in settings.ACP_ARGS.split() if a]
        if resolved.lower().endswith((".cmd", ".bat")):
            return ["cmd", "/c", resolved, *args]
        return [resolved, *args]

    async def _start(self) -> None:
        cmd = self._launch_command()
        logger.info("[ACP] 启动服务端：%s", " ".join(cmd))
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=STREAM_LIMIT,
            )
        except FileNotFoundError as e:
            raise ACPError(
                f"未找到命令 {settings.ACP_COMMAND}，请先安装 TRAE CLI 并确保其在 PATH 中"
            ) from e
        except OSError as e:
            raise ACPError(f"启动 ACP 服务端失败：{e}") from e
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def close(self) -> None:
        """关闭 stdin 并终止子进程，同时取消读取任务。"""
        proc, self._proc = self._proc, None
        if proc is not None:
            with contextlib.suppress(Exception):
                if proc.stdin and not proc.stdin.is_closing():
                    proc.stdin.close()
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                    await proc.wait()
            logger.info("[ACP] 服务端已退出，返回码：%s", proc.returncode)
        for task in (self._reader_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
        self._reader_task = None
        self._stderr_task = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ACPError("ACP 进程已关闭"))
        self._pending.clear()

    async def _read_stderr(self) -> None:
        """将服务端 stderr 写入后端日志，便于排查登录与权限问题。"""
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            logger.info("[ACP stderr] %s", line.decode("utf-8", errors="replace").rstrip())

    async def _read_stdout(self) -> None:
        """读取换行分隔的 JSON-RPC 消息并分发。"""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            raw = line.strip()
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("[ACP] 忽略非 JSON 输出：%s", raw[:200])
                continue
            await self._dispatch(message)
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ACPError("ACP 进程已退出"))
        self._pending.clear()

    # ---------------- 消息收发 ----------------

    async def _send(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise ACPError("ACP 进程未启动")
        data = json.dumps(payload, ensure_ascii=False) + "\n"
        try:
            proc.stdin.write(data.encode("utf-8"))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            raise ACPError("ACP 进程连接已断开") from e

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = fut
        await self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        return await fut

    async def _dispatch(self, message: dict[str, Any]) -> None:
        """区分响应、Agent 反向请求与通知三类消息。"""
        if "id" in message and ("result" in message or "error" in message):
            fut = self._pending.pop(message["id"], None)
            if fut is None or fut.done():
                return
            error = message.get("error")
            if error:
                if error.get("code") == AUTH_REQUIRED_CODE:
                    fut.set_exception(
                        ACPError("TRAE CLI 需要登录，请先在终端完成 traecli 登录后重试")
                    )
                else:
                    fut.set_exception(
                        ACPError(f"ACP 调用失败：{error.get('message', '未知错误')}")
                    )
            else:
                fut.set_result(message.get("result") or {})
            return

        method = message.get("method", "")
        params = message.get("params") or {}
        if "id" in message:
            result, error = await self._handle_agent_request(method, params)
            if error is not None:
                await self._send({"jsonrpc": "2.0", "id": message["id"], "error": error})
            else:
                await self._send(
                    {"jsonrpc": "2.0", "id": message["id"], "result": result}
                )
        elif method == "session/update":
            self._handle_update(params.get("update") or {})

    # ---------------- Agent 反向请求 ----------------

    async def _handle_agent_request(
        self, method: str, params: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if method == "fs/write_text_file":
            target = self._resolve_workspace_path(params.get("path", ""))
            if target is None:
                return None, {"code": -32602, "message": "禁止写入工作区外的文件"}
            content = params.get("content", "")
            await asyncio.to_thread(self._write_text, target, content)
            return {}, None

        if method == "fs/read_text_file":
            target = self._resolve_workspace_path(params.get("path", ""))
            if target is None:
                return None, {"code": -32602, "message": "禁止访问工作区外的文件"}
            if not target.is_file():
                return None, {"code": -32001, "message": "文件不存在"}
            content = await asyncio.to_thread(self._read_text, target)
            line = params.get("line")
            limit = params.get("limit")
            if line or limit:
                lines = content.splitlines(keepends=True)
                start = max((line or 1) - 1, 0)
                end = start + limit if limit else None
                content = "".join(lines[start:end])
            return {"content": content}, None

        if method == "session/request_permission":
            options = params.get("options") or []
            chosen = next(
                (o for o in options if o.get("kind") == "allow_once"), None
            ) or next((o for o in options if o.get("kind") == "allow_always"), None)
            if chosen is None:
                return {"outcome": {"outcome": "cancelled"}}, None
            return {
                "outcome": {"outcome": "selected", "optionId": chosen.get("optionId")}
            }, None

        return None, {"code": -32601, "message": f"不支持的方法：{method}"}

    @staticmethod
    def _workspace() -> Path:
        return settings.workspace_dir_path.resolve()

    def _resolve_workspace_path(self, raw_path: str) -> Path | None:
        """把协议传入的绝对路径解析并限制在 workspace 内，越界返回 None。"""
        if not raw_path:
            return None
        path = Path(raw_path)
        if not path.is_absolute():
            path = self._workspace() / path
        target = path.resolve()
        if not target.is_relative_to(self._workspace()):
            return None
        return target

    @staticmethod
    def _write_text(target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    @staticmethod
    def _read_text(target: Path) -> str:
        return target.read_text(encoding="utf-8")

    # ---------------- 会话流程 ----------------

    async def _initialize(self) -> dict[str, Any]:
        result = await self._request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True},
                },
                "clientInfo": CLIENT_INFO,
            },
        )
        logger.info("[ACP] 初始化完成：%s", result.get("agentInfo") or {})
        return result

    async def _create_session(self) -> str:
        result = await self._request(
            "session/new",
            {"cwd": str(self._workspace()), "mcpServers": []},
        )
        session_id = result.get("sessionId")
        if not session_id:
            raise ACPError("ACP 未返回 sessionId")
        return session_id

    # ---------------- 通知处理 ----------------

    def _handle_update(self, update: dict[str, Any]) -> None:
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = update.get("content") or {}
            if content.get("type") == "text":
                self._agent_text.append(content.get("text", ""))
        elif kind in ("tool_call", "tool_call_update"):
            tool_call_id = update.get("toolCallId")
            if tool_call_id:
                self._tool_calls.setdefault(tool_call_id, {}).update(update)

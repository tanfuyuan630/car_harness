"""FastAPI 应用入口：聊天、会话、人机协同、汽车数据接口。"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sse_starlette.sse import EventSourceResponse

from app.agent.error_policy import (
    ErrorKind,
    classify_exception,
    is_redis_unavailable,
    reset_recovery_budget,
)
from app.agent.harness import get_agent
from app.agent.tiering import (
    ComplexityLevel,
    prepare_main_tier,
    reset_main_tier,
    set_main_tier,
    set_thread_tier,
    tier_name,
)
from app.api.auth import router as auth_router
from app.core.auth import get_current_user
from app.core.config import settings
from app.core.db import init_db
from app.models.schemas import ChatRequest, HistoryResponse, MessageItem, ResumeRequest, ThreadCreateResponse
from app.models.user import User
from app.services.car_data import car_data_service
from app.services import conversation_store
from app.services import memory_manager
from app.services import checkpoint_maintenance, thread_registry
from app.services.checkpoint_store import close_checkpointer, setup_checkpointer
from app.services.interrupts import build_resume_value, interrupt_kind, pending_actions

logger = logging.getLogger(__name__)

app = FastAPI(title="汽车销售助手 Agent Harness", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


@app.on_event("startup")
async def on_startup() -> None:
    """启动时先初始化 Redis Checkpointer，再初始化数据库与 IM 渠道。"""
    await setup_checkpointer()
    init_db()
    _start_im_channels()
    checkpoint_maintenance.start_maintenance()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """关闭时停止维护任务并释放 Redis 连接。"""
    await checkpoint_maintenance.stop_maintenance()
    await close_checkpointer()


def _start_im_channels() -> None:
    """按配置启动 IM 渠道；未启用或缺凭据时直接跳过，不影响 Web 服务。"""
    if not settings.FEISHU_ENABLED:
        return
    if not settings.FEISHU_APP_ID or not settings.FEISHU_APP_SECRET:
        return

    # 延迟导入：未启用飞书时不加载 lark_oapi 与渠道模块
    from app.channels.feishu import FeishuChannel
    from app.channels.handler import handle_im_message
    from app.channels.router import ChannelRouter

    router = ChannelRouter()
    router.register(
        handle_im_message,
        FeishuChannel(
            dispatch=router.dispatch,
            app_id=settings.FEISHU_APP_ID,
            app_secret=settings.FEISHU_APP_SECRET,
        ),
    )
    router.start_all()


# ---------------- Agent 追踪配置 ----------------

# 全局业务标识，用于在 LangSmith 中区分本项目与其他项目的调用链路
AGENT_TAG = "car-sales-agent"


def _trace_config(
    thread_id: str, user_id: str, scenario: str, tier: str | None = None
) -> dict[str, Any]:
    """构造带 LangSmith 追踪标签的 Agent 运行配置。

    tags 与 metadata 会传播到整条 trace（含子智能体与工具调用），
    便于在 LangSmith 中按业务场景、用户维度过滤与统计。
    分档开启时额外记录本次使用的模型档位。
    """
    tags = [AGENT_TAG, scenario, f"user:{user_id}"]
    metadata: dict[str, Any] = {
        "thread_id": thread_id,
        "user_id": user_id,
        "scenario": scenario,
    }
    if tier is not None:
        metadata["llm_tier"] = tier
        tags.append(f"tier:{tier}")
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": scenario,
        "tags": tags,
        "metadata": metadata,
    }


async def _prepare_main_tier(
    user_id: str, thread_id: str, message: str
) -> tuple[ComplexityLevel | None, str]:
    """分档开启时分类并写入主 Agent 档位；关闭时返回 (None, "off")。"""
    if not settings.LLM_TIER_ENABLED:
        return None, "off"
    previous = conversation_store.last_assistant_text(user_id, thread_id)
    level = await prepare_main_tier(message, previous, thread_id)
    return level, tier_name(level)


# ---------------- 会话管理 ----------------

@app.post("/api/threads", response_model=ThreadCreateResponse)
async def create_thread(current_user: User = Depends(get_current_user)):
    """创建新会话线程。"""
    thread_id = str(uuid.uuid4())
    # 分档开启时写入默认档位，后续恢复与重试可复用
    await thread_registry.track_thread(
        current_user.user_id, thread_id, tier="medium" if settings.LLM_TIER_ENABLED else None
    )
    return ThreadCreateResponse(thread_id=thread_id)


@app.get("/api/threads/{thread_id}/history", response_model=HistoryResponse)
def get_history(thread_id: str, current_user: User = Depends(get_current_user)):
    """获取会话历史消息（从持久化的 Markdown 记录读取）。"""
    turns = conversation_store.load_conversation(current_user.user_id, thread_id)
    messages: list[MessageItem] = []
    for t in turns:
        messages.append(MessageItem(role="user", content=t["user"]))
        messages.append(MessageItem(role="assistant", content=t["assistant"]))
    return HistoryResponse(thread_id=thread_id, messages=messages)


@app.get("/api/threads/{thread_id}/interrupts")
async def get_interrupts(thread_id: str, _: User = Depends(get_current_user)):
    """获取当前待审批或待补充信息的中断。"""
    agent = get_agent()
    config = {"configurable": {"thread_id": thread_id}}
    state = await agent.aget_state(config)
    interrupts = []
    for task in state.tasks:
        for interrupt in getattr(task, "interrupts", []) or []:
            interrupts.append({
                "value": interrupt.value,
                "kind": interrupt_kind(interrupt.value),
            })
    return {"thread_id": thread_id, "interrupts": interrupts}


@app.post("/api/threads/{thread_id}/resume")
async def resume_thread(thread_id: str, req: ResumeRequest, current_user: User = Depends(get_current_user)):
    """提交审批或补充信息，恢复 Agent 执行。"""
    agent = get_agent()
    # 恢复时复用线程最近档位，避免补充信息过短导致档位漂移
    tier: str | None = None
    if settings.LLM_TIER_ENABLED:
        meta = await thread_registry.get_thread_meta(thread_id)
        tier = tier_name(set_thread_tier(meta.get("tier"), thread_id, "hitl-resume"))
    config = _trace_config(thread_id, current_user.user_id, "hitl-resume", tier)
    from langgraph.types import Command
    try:
        state = await agent.aget_state(config)
        actions = pending_actions(state)
        if not actions:
            raise HTTPException(status_code=409, detail="该线程没有待处理的中断")
        resume_value = build_resume_value(actions, req.decision, req.edited_content)
        reset_recovery_budget()
        try:
            result = await agent.ainvoke(Command(resume=resume_value), config=config)
        except Exception as exc:
            return await _error_response(exc, thread_id, "resume")
        assistant_text = _last_ai_text(result)
        # 中断前流式阶段已保存用户消息和不完整的助手消息，此处仅更新最后一条助手消息为最终回答
        conversation_store.update_last_assistant(current_user.user_id, thread_id, assistant_text)
        await thread_registry.track_thread(current_user.user_id, thread_id, tier=tier)
        # 检查恢复后是否再次触发中断
        state = await agent.aget_state(config)
        has_interrupt = any(getattr(t, "interrupts", None) for t in state.tasks)
        return {"thread_id": thread_id, "content": assistant_text, "interrupted": has_interrupt}
    finally:
        reset_main_tier()


# ---------------- 聊天 ----------------

def _last_ai_text(result: dict) -> str:
    """提取结果中最后一条消息的文本内容。"""
    msgs = result.get("messages", [])
    last = msgs[-1] if msgs else None
    content = last.content if last else ""
    if isinstance(content, list):
        content = " ".join(
            str(c.get("text", "")) if isinstance(c, dict) else str(c) for c in content
        )
    return str(content)


def _save_user_only(user_id: str, thread_id: str, message: str) -> None:
    """失败轮次只落盘用户消息，助手内容留空，等待人工重试后回填。"""
    conversation_store.save_turn(user_id, thread_id, message, "")


async def _error_response(exc: Exception, thread_id: str, scenario: str) -> JSONResponse:
    """按错误分类返回统一响应，并记录致命错误的线程与检查点。"""
    kind = classify_exception(exc)
    checkpoint_id = ""
    if kind == ErrorKind.FATAL:
        try:
            state = await get_agent().aget_state({"configurable": {"thread_id": thread_id}})
            checkpoint_id = (state.config or {}).get("configurable", {}).get("checkpoint_id", "")
        except Exception:
            checkpoint_id = ""
        logger.exception(
            "[AgentFatal] scenario=%s thread=%s checkpoint=%s", scenario, thread_id, checkpoint_id
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"服务端错误: {str(exc)[:200]}",
                "fatal": True,
                "retryable": False,
                "kind": kind.value,
            },
        )
    if is_redis_unavailable(exc):
        logger.warning("[RedisUnavailable] thread=%s scenario=%s: %s", thread_id, scenario, exc)
        return JSONResponse(
            status_code=503,
            content={
                "detail": "会话存储暂不可用，请稍后重试",
                "retryable": True,
                "kind": kind.value,
            },
        )
    return JSONResponse(
        status_code=502,
        content={
            "detail": f"模型临时错误: {str(exc)[:200]}",
            "retryable": True,
            "kind": kind.value,
        },
    )


def _build_messages(user_id: str, thread_id: str, new_message: str) -> list[dict]:
    """根据摘要 + 滑动窗口构建 Agent 输入消息列表。"""
    ctx = memory_manager.build_context(user_id, thread_id)
    messages: list[dict] = []
    if ctx["summary"]:
        messages.append({"role": "system", "content": f"【历史摘要】\n{ctx['summary']}"})
    for turn in ctx["recent"]:
        if turn["user"]:
            messages.append({"role": "user", "content": turn["user"]})
        if turn["assistant"]:
            messages.append({"role": "assistant", "content": turn["assistant"]})
    messages.append({"role": "user", "content": new_message})
    return messages


@app.post("/api/chat")
async def chat(req: ChatRequest, current_user: User = Depends(get_current_user)):
    """非流式聊天接口。"""
    agent = get_agent()
    messages = _build_messages(current_user.user_id, req.thread_id, req.message)
    # 分档开启时先分类再调 Agent；分类失败按可重试错误返回，不静默换档
    try:
        level, tier = await _prepare_main_tier(current_user.user_id, req.thread_id, req.message)
    except Exception as exc:
        return await _error_response(exc, req.thread_id, "chat")
    config = _trace_config(
        req.thread_id, current_user.user_id, "chat", tier if level is not None else None
    )
    reset_recovery_budget()
    await thread_registry.track_thread(
        current_user.user_id, req.thread_id, tier=tier if level is not None else None
    )
    try:
        result = await agent.ainvoke({"messages": messages}, config=config)
    except Exception as exc:
        _save_user_only(current_user.user_id, req.thread_id, req.message)
        return await _error_response(exc, req.thread_id, "chat")
    finally:
        reset_main_tier()
    assistant_text = _last_ai_text(result)
    # 持久化对话并更新记忆
    await memory_manager.update_memory(current_user.user_id, req.thread_id, req.message, assistant_text)
    state = await agent.aget_state(config)
    has_interrupt = any(getattr(t, "interrupts", None) for t in state.tasks)
    return {
        "thread_id": req.thread_id,
        "content": assistant_text,
        "interrupted": has_interrupt,
        "tier": tier,
    }


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, current_user: User = Depends(get_current_user)):
    """流式聊天接口（SSE）。"""
    agent = get_agent()
    messages = _build_messages(current_user.user_id, req.thread_id, req.message)
    # 分档开启时先分类再流式调用；分类失败直接返回可重试错误
    try:
        level, tier = await _prepare_main_tier(current_user.user_id, req.thread_id, req.message)
    except Exception as exc:
        return await _error_response(exc, req.thread_id, "chat-stream")
    config = _trace_config(
        req.thread_id, current_user.user_id, "chat-stream", tier if level is not None else None
    )
    reset_recovery_budget()
    await thread_registry.track_thread(
        current_user.user_id, req.thread_id, tier=tier if level is not None else None
    )
    full_content = ""

    async def event_generator():
        nonlocal full_content
        # 生成器可能运行在独立任务中，进入时重新写入档位上下文
        if level is not None:
            set_main_tier(level, req.thread_id)
        failed = False
        try:
            async for event in agent.astream_events(
                {"messages": messages},
                config=config,
                version="v2",
            ):
                etype = event.get("event")
                data = event.get("data", {})
                meta = event.get("metadata") or {}
                # 只处理顶层主图的事件，过滤子智能体（子图）内部的模型流，
                # 避免子智能体的中间输出混入最终回复。
                # 子图事件的 checkpoint_ns 格式为 "subagent_name:..."（含冒号且不是 model: 开头），
                # 主图模型事件的 checkpoint_ns 为 "model:..." 或空。
                ns = meta.get("checkpoint_ns", "") or ""
                if ns and not ns.startswith("model:"):
                    continue
                if etype == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        text = chunk.content
                        if isinstance(text, list):
                            text = "".join(t.get("text", "") if isinstance(t, dict) else str(t) for t in text)
                        if text:
                            full_content += str(text)
                            yield {"event": "token", "data": json.dumps({"content": str(text)}, ensure_ascii=False)}
                elif etype == "on_tool_start":
                    name = data.get("name", "")
                    yield {"event": "tool_start", "data": json.dumps({"name": name}, ensure_ascii=False)}
                elif etype == "on_tool_end":
                    name = data.get("name", "")
                    output = data.get("output", "")
                    out_str = str(output)[:500] if output else ""
                    yield {"event": "tool_end", "data": json.dumps({"name": name, "output": out_str}, ensure_ascii=False)}
        except Exception as exc:
            failed = True
            kind = classify_exception(exc)
            checkpoint_id = ""
            try:
                state = await agent.aget_state(config)
                checkpoint_id = (state.config or {}).get("configurable", {}).get("checkpoint_id", "")
            except Exception:
                checkpoint_id = ""
            logger.exception(
                "[AgentStreamError] kind=%s thread=%s checkpoint=%s",
                kind.value, req.thread_id, checkpoint_id,
            )
            _save_user_only(current_user.user_id, req.thread_id, req.message)
            full_content = ""
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "error": str(exc)[:200],
                        "kind": kind.value,
                        "retryable": kind != ErrorKind.FATAL,
                    },
                    ensure_ascii=False,
                ),
            }
        finally:
            reset_main_tier()
            # 成功才写入完整对话；失败只保留用户轮次，等待重试回填
            if not failed:
                try:
                    await memory_manager.update_memory(
                        current_user.user_id, req.thread_id, req.message, full_content,
                    )
                except Exception:
                    logger.exception("[MemoryUpdate] 更新对话记忆失败：%s", req.thread_id)
            yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_generator())


@app.post("/api/threads/{thread_id}/retry")
async def retry_thread(thread_id: str, current_user: User = Depends(get_current_user)):
    """从最后一个成功检查点继续未完成的任务，不重复用户消息。"""
    agent = get_agent()
    # 重试复用线程最近档位，不重新分类
    tier: str | None = None
    if settings.LLM_TIER_ENABLED:
        meta = await thread_registry.get_thread_meta(thread_id)
        tier = tier_name(set_thread_tier(meta.get("tier"), thread_id, "chat-retry"))
    config = _trace_config(thread_id, current_user.user_id, "chat-retry", tier)
    try:
        state = await agent.aget_state(config)

        if any(getattr(t, "interrupts", None) for t in state.tasks):
            raise HTTPException(status_code=409, detail="该线程有待处理的中断，请先完成审批或补充信息")
        if not state.next:
            raise HTTPException(status_code=409, detail="该线程没有可重试的任务")

        reset_recovery_budget()
        try:
            result = await agent.ainvoke(None, config=config)
        except Exception as exc:
            return await _error_response(exc, thread_id, "retry")

        assistant_text = _last_ai_text(result)
        conversation_store.update_last_assistant(current_user.user_id, thread_id, assistant_text)
        await thread_registry.track_thread(current_user.user_id, thread_id, tier=tier)
        state = await agent.aget_state(config)
        has_interrupt = any(getattr(t, "interrupts", None) for t in state.tasks)
        return {"thread_id": thread_id, "content": assistant_text, "interrupted": has_interrupt}
    finally:
        reset_main_tier()


# ---------------- 历史会话 ----------------

@app.get("/api/conversations")
def list_conversations(current_user: User = Depends(get_current_user)):
    """列出当前登录用户的所有会话。"""
    return {"conversations": conversation_store.list_conversations(current_user.user_id)}


@app.get("/api/conversations/{thread_id}")
def get_conversation(thread_id: str, current_user: User = Depends(get_current_user)):
    """读取指定会话的完整对话记录。"""
    turns = conversation_store.load_conversation(current_user.user_id, thread_id)
    return {"thread_id": thread_id, "turns": turns}


# ---------------- 工作区文件 ----------------

def _workspace_root() -> Path:
    """返回工作区绝对路径，所有文件操作以此为边界。"""
    return settings.workspace_dir_path.resolve()


@app.get("/api/workspace/files")
def list_workspace_files(_: User = Depends(get_current_user)):
    """列出工作区内的全部文件，按修改时间倒序。"""
    root = _workspace_root()
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        stat = path.stat()
        files.append(
            {
                "name": path.relative_to(root).as_posix(),
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    files.sort(key=lambda item: item["modified_at"], reverse=True)
    return {"files": files}


@app.get("/api/workspace/files/{file_path:path}")
def download_workspace_file(file_path: str, _: User = Depends(get_current_user)):
    """下载工作区内的文件，路径越界返回 400。"""
    root = _workspace_root()
    target = (root / file_path).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(status_code=400, detail="非法文件路径")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(target, filename=target.name)


# ---------------- 汽车数据 ----------------

@app.get("/api/brands")
def get_brands(_: User = Depends(get_current_user)):
    return {"brands": car_data_service.list_brands()}


@app.get("/api/brands/{brand}/series")
def get_series(brand: str, _: User = Depends(get_current_user)):
    return {"series": car_data_service.list_series(brand=brand)}


@app.get("/api/cars")
def search_cars(
    brand: str | None = None,
    series: str | None = None,
    level: str | None = None,
    energy_type: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    keyword: str | None = None,
    limit: int = 20,
    _: User = Depends(get_current_user),
):
    return {
        "cars": car_data_service.search_cars(
            brand=brand, series=series, level=level, energy_type=energy_type,
            price_min=price_min, price_max=price_max, keyword=keyword, limit=limit,
        )
    }


@app.get("/api/cars/{model_id}")
def get_car(model_id: str, _: User = Depends(get_current_user)):
    detail = car_data_service.get_car_detail(model_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="车型不存在")
    return detail


@app.get("/api/health")
def health():
    return {"status": "ok"}

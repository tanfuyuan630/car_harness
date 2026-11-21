"""Redis 检查点集成测试。

依赖 Redis 8（内置 RedisJSON/RediSearch）；RediSearch 只支持 DB 0，测试使用带前缀的线程 ID。
条件不满足时自动跳过。
"""
from __future__ import annotations

from typing import TypedDict
from urllib.parse import quote_plus

import pytest
import redis
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.core.config import settings

THREAD_IDS = ("it_plain", "it_restart", "it_interrupt", "it_delete")


def _redis_url() -> str:
    auth = f":{quote_plus(settings.REDIS_PASSWORD)}@" if settings.REDIS_PASSWORD else ""
    return f"redis://{auth}{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"


def _redis_ready() -> bool:
    """探测连接、RedisJSON 与 RediSearch 是否可用。"""
    client = None
    try:
        client = redis.Redis.from_url(_redis_url(), socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        client.execute_command("JSON.SET", "lg:probe:json", "$", '{"a":1}')
        client.delete("lg:probe:json")
        client.execute_command("FT._LIST")
        return True
    except Exception:
        return False
    finally:
        if client is not None:
            client.close()


REDIS_READY = _redis_ready()
pytestmark = pytest.mark.skipif(
    not REDIS_READY,
    reason="需要 Redis 8 + RedisJSON/RediSearch，且 DB 15 可连接",
)


class State(TypedDict, total=False):
    answer: str


def _plain_graph():
    graph = StateGraph(State)
    graph.add_node("echo", lambda state: {"answer": "ok"})
    graph.add_edge(START, "echo")
    graph.add_edge("echo", END)
    return graph


def _interrupt_graph():
    def ask(state):
        value = interrupt(
            {"action_requests": [{"name": "ask_user_for_input", "args": {"question": "预算"}}]}
        )
        return {"answer": value}

    graph = StateGraph(State)
    graph.add_node("ask", ask)
    graph.add_edge(START, "ask")
    graph.add_edge("ask", END)
    return graph


def _new_saver():
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver

    return AsyncRedisSaver.from_conn_string(
        _redis_url(),
        ttl={"default_ttl": 60, "refresh_on_read": True},
    )


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _cleanup() -> None:
    """只清理测试线程相关键，保留索引与其他业务数据。"""
    client = redis.Redis.from_url(_redis_url(), socket_connect_timeout=2, socket_timeout=2)
    try:
        for thread_id in THREAD_IDS:
            keys = list(client.scan_iter(match=f"*{thread_id}*", count=500))
            if keys:
                client.delete(*keys)
    finally:
        client.close()


@pytest.fixture(autouse=True)
def clean_db():
    _cleanup()
    yield
    _cleanup()


def test_checkpoint_written_and_read():
    """检查点写入后可读取，且存在 TTL。"""
    import asyncio

    async def flow():
        cm = _new_saver()
        saver = await cm.__aenter__()
        try:
            graph = _plain_graph().compile(checkpointer=saver)
            config = _config("it_plain")
            await graph.ainvoke({"answer": ""}, config)
            snapshot = await graph.aget_state(config)
            assert snapshot.values["answer"] == "ok"
            assert snapshot.config["configurable"]["checkpoint_id"]

            client = redis.Redis.from_url(_redis_url(), socket_timeout=2)
            try:
                keys = list(client.scan_iter(match="*it_plain*", count=500))
                assert keys
                assert any(client.ttl(key) > 0 for key in keys)
            finally:
                client.close()
        finally:
            await cm.__aexit__(None, None, None)

    asyncio.run(flow())


def test_second_saver_reads_same_thread():
    """新 Saver 实例可读取同一线程，模拟进程重启。"""
    import asyncio

    async def flow():
        cm1 = _new_saver()
        saver1 = await cm1.__aenter__()
        try:
            graph = _plain_graph().compile(checkpointer=saver1)
            await graph.ainvoke({"answer": ""}, _config("it_restart"))
        finally:
            await cm1.__aexit__(None, None, None)

        cm2 = _new_saver()
        saver2 = await cm2.__aenter__()
        try:
            graph2 = _plain_graph().compile(checkpointer=saver2)
            snapshot = await graph2.aget_state(_config("it_restart"))
            assert snapshot.values["answer"] == "ok"
        finally:
            await cm2.__aexit__(None, None, None)

    asyncio.run(flow())


def test_interrupt_survives_restart_and_resume():
    """中断后重启，仍能查询待处理中断并恢复执行。"""
    import asyncio

    async def flow():
        config = _config("it_interrupt")
        cm1 = _new_saver()
        saver1 = await cm1.__aenter__()
        try:
            graph = _interrupt_graph().compile(checkpointer=saver1)
            await graph.ainvoke({"answer": ""}, config)
            snapshot = await graph.aget_state(config)
            assert snapshot.tasks[0].interrupts
        finally:
            await cm1.__aexit__(None, None, None)

        cm2 = _new_saver()
        saver2 = await cm2.__aenter__()
        try:
            graph2 = _interrupt_graph().compile(checkpointer=saver2)
            snapshot = await graph2.aget_state(config)
            assert snapshot.tasks[0].interrupts
            result = await graph2.ainvoke(Command(resume="20 万"), config)
            assert result["answer"] == "20 万"
            final = await graph2.aget_state(config)
            assert not any(task.interrupts for task in final.tasks)
        finally:
            await cm2.__aexit__(None, None, None)

    asyncio.run(flow())


def test_adelete_thread_removes_state():
    """删除线程后不再返回检查点。"""
    import asyncio

    async def flow():
        cm = _new_saver()
        saver = await cm.__aenter__()
        try:
            graph = _plain_graph().compile(checkpointer=saver)
            config = _config("it_delete")
            await graph.ainvoke({"answer": ""}, config)
            await saver.adelete_thread("it_delete")
            snapshot = await graph.aget_state(config)
            assert not snapshot.values
            assert not snapshot.config["configurable"].get("checkpoint_id")
        finally:
            await cm.__aexit__(None, None, None)

    asyncio.run(flow())

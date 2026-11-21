"""飞书渠道: 长连接接收 im.message.receive_v1 事件, 通过 OpenAPI 回复原消息。"""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from typing import TYPE_CHECKING, Any

from app.channels.base import Channel, IncomingMessage, MessageHandler

if TYPE_CHECKING:
    from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

logger = logging.getLogger(__name__)

# 群聊 @ 提及占位符, 形如 @_user_1
AT_PLACEHOLDER_RE = re.compile(r"@_user_\d+")

# 流式更新的最小间隔（秒），避免触发飞书消息更新频率限制
_STREAM_UPDATE_INTERVAL = 1.2

# 流式回复的占位文本
_PLACEHOLDER = "思考中..."


class _StreamUpdater:
    """流式内容更新器：记录最新文本，按间隔节流调用消息更新，模拟逐字输出。"""

    def __init__(self, channel: "FeishuChannel", message_id: str) -> None:
        self._channel = channel
        self._message_id = message_id
        self._last_update = 0.0

    def __call__(self, text: str) -> None:
        now = time.monotonic()
        if now - self._last_update >= _STREAM_UPDATE_INTERVAL:
            self._channel.patch(self._message_id, text)
            self._last_update = now


class FeishuChannel(Channel):
    """飞书渠道: 长连接收事件, 队列串行处理, OpenAPI 回复。"""

    name = "feishu"

    def __init__(self, dispatch: MessageHandler, app_id: str, app_secret: str) -> None:
        super().__init__(dispatch)
        self.app_id = app_id
        self.app_secret = app_secret
        # 入站消息队列: 事件回调只入队, 由工作线程串行处理, 避免阻塞长连接心跳
        self._queue: queue.Queue = queue.Queue()
        # OpenAPI 客户端在 start() 中创建, 确保 lark 的模块级事件循环属于渠道线程
        self._client: Any = None

    def start(self) -> None:
        # 在渠道线程内首次导入 lark_oapi: 其 ws 模块导入时会创建模块级事件循环,
        # 该循环必须与运行长连接的线程一致; 若在 FastAPI 启动的运行中循环里导入会无法启动。
        import lark_oapi as lark

        self._client = lark.Client.builder() \
            .app_id(self.app_id) \
            .app_secret(self.app_secret) \
            .build()

        # 先启动消息消费线程, 再建立长连接
        threading.Thread(target=self._worker, name="feishu-worker", daemon=True).start()

        # 事件分发器: 长连接模式下加密密钥与校验 token 留空
        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(self._on_event) \
            .build()

        # 长连接客户端: 通过 WebSocket 接收事件, start() 会阻塞当前线程
        ws_client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )
        logger.info("[feishu] 长连接启动")
        ws_client.start()

    def _on_event(self, data: P2ImMessageReceiveV1) -> None:
        # 只处理文本消息, 非文本直接忽略
        msg = data.event.message
        if msg.message_type != "text":
            logger.info("[feishu] 忽略非文本消息: type=%s, message_id=%s", msg.message_type, msg.message_id)
            return

        content = json.loads(msg.content)
        # 剥离群聊 @ 提及占位符, 去掉后为空则忽略
        text = AT_PLACEHOLDER_RE.sub("", content.get("text", "")).strip()
        if not text:
            logger.info("[feishu] 忽略空文本消息: message_id=%s", msg.message_id)
            return

        message = IncomingMessage(
            channel=self.name,
            chat_id=msg.chat_id,
            sender_id=data.event.sender.sender_id.open_id,
            message_id=msg.message_id,
            text=text,
        )
        logger.info("[feishu] 收到消息: message_id=%s, 内容=%r", msg.message_id, text)
        self._queue.put(message)

    def _worker(self) -> None:
        # 串行消费队列: 先回复占位消息，再随 Agent 流式输出更新该消息，最后写入完整回复
        while True:
            message = self._queue.get()
            reply_id = None
            try:
                reply_id = self.reply(message, _PLACEHOLDER)
                answer = self.dispatch(message, _StreamUpdater(self, reply_id))
                self.patch(reply_id, answer)
            except Exception:
                logger.exception("[feishu] 消息处理失败: message_id=%s", message.message_id)
                if reply_id:
                    self.patch(reply_id, "处理失败，请稍后重试")
            finally:
                self._queue.task_done()

    def reply(self, message: IncomingMessage, text: str) -> str:
        # 以机器人身份用纯文本消息回复原消息，返回新消息 ID 供后续流式更新
        from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody

        request = ReplyMessageRequest.builder() \
            .message_id(message.message_id) \
            .request_body(
                ReplyMessageRequestBody.builder()
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .msg_type("text")
                .build()
            ) \
            .build()
        response = self._client.im.v1.message.reply(request)
        if not response.success():
            logger.error("[feishu] 回复失败: code=%s, msg=%s", response.code, response.msg)
            raise RuntimeError(f"飞书回复失败: {response.code} {response.msg}")
        return response.data.message_id

    def patch(self, message_id: str, text: str) -> None:
        # 更新机器人已发送的消息内容，用于模拟流式输出；需应用具备更新消息权限
        from lark_oapi.api.im.v1 import UpdateMessageRequest, UpdateMessageRequestBody

        request = UpdateMessageRequest.builder() \
            .message_id(message_id) \
            .request_body(
                UpdateMessageRequestBody.builder()
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .msg_type("text")
                .build()
            ) \
            .build()
        response = self._client.im.v1.message.update(request)
        if not response.success():
            logger.error("[feishu] 更新消息失败: code=%s, msg=%s", response.code, response.msg)

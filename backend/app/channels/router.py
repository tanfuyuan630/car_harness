"""渠道入口路由: 维护渠道名到消息处理器的映射, 负责统一分发与渠道启动。"""
from __future__ import annotations

import logging
import threading

from app.channels.base import Channel, DeltaCallback, IncomingMessage, MessageHandler

logger = logging.getLogger(__name__)


class ChannelRouter:
    """多渠道统一入口: 按渠道名路由到对应的消息处理器。"""

    def __init__(self) -> None:
        # 渠道名 -> 消息处理器
        self._handlers: dict[str, MessageHandler] = {}
        # 渠道名 -> 渠道实例
        self._channels: dict[str, Channel] = {}

    def register(self, handler: MessageHandler, channel: Channel) -> None:
        """注册渠道及其消息处理器; 渠道名必须非空且不能重复。"""
        name = channel.name
        if not name:
            raise ValueError("渠道名称不能为空")
        if name in self._handlers:
            raise ValueError(f"渠道已注册: {name}")
        self._handlers[name] = handler
        self._channels[name] = channel

    def dispatch(self, message: IncomingMessage, on_delta: DeltaCallback) -> str:
        """按消息所属渠道查找处理器并透传内容更新回调, 未注册渠道直接报错。"""
        handler = self._handlers.get(message.channel)
        if handler is None:
            raise ValueError(f"渠道未注册: {message.channel}")
        return handler(message, on_delta)

    def start_all(self) -> None:
        """为每个渠道启动守护线程运行 start(), 单个渠道异常只记录日志。"""
        for name, channel in self._channels.items():
            thread = threading.Thread(
                target=self._run_channel,
                args=(name, channel),
                name=f"channel-{name}",
                daemon=True,
            )
            thread.start()

    @staticmethod
    def _run_channel(name: str, channel: Channel) -> None:
        # 渠道启动与运行异常均不向上抛出, 避免影响其他渠道与 HTTP 服务
        try:
            logger.info("渠道启动: %s", name)
            channel.start()
        except Exception:
            logger.exception("渠道运行异常: %s", name)

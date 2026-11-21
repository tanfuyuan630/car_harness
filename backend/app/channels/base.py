"""渠道抽象: 统一不同 IM 的消息格式与收发接口, 新增 IM 只需实现 Channel 基类。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable


@dataclass
class IncomingMessage:
    """统一消息对象: 由各渠道适配器从原始事件解析生成。"""

    channel: str      # 渠道名, 如 feishu
    chat_id: str      # 会话 ID, 作为多轮记忆的隔离维度
    sender_id: str    # 渠道侧发送者 ID
    message_id: str   # 渠道侧消息 ID, 用于回复定位
    text: str         # 文本内容


# 内容更新回调: 接收当前累积的完整回复文本，由渠道决定如何展示（如飞书更新消息）
DeltaCallback = Callable[[str], None]

# 消息处理器: 接收统一消息与内容更新回调，返回最终回复文本
MessageHandler = Callable[[IncomingMessage, DeltaCallback], str]


class Channel(ABC):
    """IM 渠道基类: 负责监听渠道消息并回复统一处理结果。"""

    name: str = ""

    def __init__(self, dispatch: MessageHandler) -> None:
        # 统一入口分发函数, 由渠道在收到消息后调用
        self.dispatch = dispatch

    @abstractmethod
    def start(self) -> None:
        """启动渠道监听, 阻塞当前线程。"""
        ...

    @abstractmethod
    def reply(self, message: IncomingMessage, text: str) -> str:
        """回复指定消息，返回新消息 ID（用于后续流式更新）。"""
        ...

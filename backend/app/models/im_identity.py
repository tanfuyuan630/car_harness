"""IM 身份映射 ORM 模型: 映射 t_im_identities 表。"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint

from app.core.db import Base


class ImIdentity(Base):
    """IM 身份与系统用户的映射, 作为两者解耦的唯一依据。"""

    __tablename__ = "t_im_identities"
    __table_args__ = (
        UniqueConstraint("channel", "sender_id", name="uk_channel_sender"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    channel = Column(String(50), nullable=False, comment="渠道名, 如 feishu")
    sender_id = Column(String(200), nullable=False, comment="渠道侧发送者 ID")
    user_id = Column(String(200), nullable=False, comment="映射的系统用户 user_id")
    create_date = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    update_date = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="修改时间",
    )

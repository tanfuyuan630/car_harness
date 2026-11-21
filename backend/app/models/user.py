"""用户 ORM 模型：映射 t_users 表。"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, SmallInteger, String

from app.core.db import Base


class User(Base):
    __tablename__ = "t_users"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    user_name = Column(String(200), nullable=False, comment="用户名称")
    user_id = Column(String(200), nullable=False, unique=True, comment="用户id")
    user_pwd = Column(String(200), nullable=False, comment="密码（bcrypt 哈希）")
    age = Column(Integer, nullable=True, comment="年龄")
    create_date = Column(
        DateTime, nullable=False, default=datetime.now,
        onupdate=datetime.now, comment="创建时间",
    )
    create_by = Column(String(200), nullable=True, comment="创建人")
    update_date = Column(DateTime, nullable=False, default=datetime.now, comment="修改时间")
    update_by = Column(String(200), nullable=True, comment="修改人")
    state = Column(SmallInteger, nullable=False, default=1, comment="状态:0失效,1有效")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_name": self.user_name,
            "user_id": self.user_id,
            "age": self.age,
            "state": self.state,
        }

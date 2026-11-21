"""用户服务：用户查询、创建、密码校验。"""
import secrets
from datetime import datetime

import bcrypt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.im_identity import ImIdentity
from app.models.user import User


def hash_password(password: str) -> str:
    """对明文密码做 bcrypt 加盐哈希，返回字符串。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与存储的哈希是否匹配（bcrypt 自动从哈希中提取盐）。"""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def get_by_user_id(db: Session, user_id: str) -> User | None:
    return db.query(User).filter(User.user_id == user_id).first()


def create_user(
    db: Session, *, user_id: str, user_name: str, password: str, age: int | None = None,
) -> User:
    """创建用户；若 user_id 重复抛出 IntegrityError（调用方捕获转 409）。"""
    now = datetime.now()
    user = User(
        user_id=user_id,
        user_name=user_name,
        user_pwd=hash_password(password),
        age=age,
        create_date=now,
        create_by=user_id,
        update_date=now,
        update_by=user_id,
        state=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_or_create_im_user(db: Session, channel: str, sender_id: str) -> User:
    """按渠道发送者获取系统用户；首次出现时创建用户与 IM 身份映射。

    映射表是 IM 身份与 Web 账号解耦的唯一依据，命中后直接复用对应用户。
    """
    identity = (
        db.query(ImIdentity)
        .filter(ImIdentity.channel == channel, ImIdentity.sender_id == sender_id)
        .first()
    )
    if identity is not None:
        return get_by_user_id(db, identity.user_id)

    user_id = f"{channel}_{sender_id}"
    now = datetime.now()
    user = User(
        user_id=user_id,
        user_name=f"{channel}用户_{sender_id[-8:]}",
        user_pwd=hash_password(secrets.token_urlsafe(32)),
        create_date=now,
        create_by=user_id,
        update_date=now,
        update_by=user_id,
        state=1,
    )
    # 用户与映射在同一事务内创建，一次提交保证一致性
    db.add(user)
    db.add(ImIdentity(
        channel=channel,
        sender_id=sender_id,
        user_id=user_id,
        create_date=now,
        update_date=now,
    ))
    db.commit()
    db.refresh(user)
    return user

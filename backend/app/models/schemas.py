"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    thread_id: str
    message: str


class ThreadCreateResponse(BaseModel):
    thread_id: str


class MessageItem(BaseModel):
    role: str
    content: str
    tool_calls: Optional[list[dict[str, Any]]] = None


class HistoryResponse(BaseModel):
    thread_id: str
    messages: list[MessageItem]


class ResumeRequest(BaseModel):
    decision: str  # approve | reject | edit
    edited_content: Optional[str] = None


# ---------------- 认证相关 ----------------

class RegisterRequest(BaseModel):
    user_id: str
    user_name: str
    user_pwd: str
    age: Optional[int] = None


class LoginRequest(BaseModel):
    user_id: str
    user_pwd: str


class UserResponse(BaseModel):
    id: int
    user_id: str
    user_name: str
    age: Optional[int] = None
    state: int


class AuthResponse(BaseModel):
    token: str
    user: UserResponse

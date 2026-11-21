"""认证接口：注册、登录、登出、获取当前用户。"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import create_access_token, get_current_user
from app.core.db import get_db
from app.models.schemas import AuthResponse, LoginRequest, RegisterRequest, UserResponse
from app.models.user import User
from app.services.user_service import create_user, get_by_user_id, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """用户注册：user_id 全局唯一，密码 bcrypt 哈希存储。"""
    try:
        user = create_user(
            db,
            user_id=req.user_id,
            user_name=req.user_name,
            password=req.user_pwd,
            age=req.age,
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户ID已存在")
    return UserResponse(**user.to_dict())


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """用户登录：校验密码，返回 JWT Token。"""
    user = get_by_user_id(db, req.user_id)
    if user is None or not verify_password(req.user_pwd, user.user_pwd):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户ID或密码错误")
    if user.state != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已失效")
    token = create_access_token(user.user_id)
    return AuthResponse(token=token, user=UserResponse(**user.to_dict()))


@router.post("/logout")
def logout(_: User = Depends(get_current_user)):
    """登出：前端清除 Token 即可，服务端无状态。"""
    return {"detail": "已登出"}


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return UserResponse(**current_user.to_dict())

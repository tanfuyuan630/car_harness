# SPC-002 用户登录与注册功能模块 - 实施计划

## Task 1: MySQL 配置与数据库连接
- **Status**: completed
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 安装依赖：`sqlalchemy`、`pymysql`、`passlib[bcrypt]`、`python-jose`
  - 创建 `backend/app/core/db.py`：数据库连接配置与 Session 工厂
  - 配置写入 `.env`：`MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USER`、`MYSQL_PASSWORD`、`MYSQL_DATABASE`
  - 更新 `app/core/config.py` 增加 MySQL 与 JWT 配置项
  - 连接：127.0.0.1:3306@root/123456
- **Acceptance Criteria Addressed**: AC-3
- **Test Requirements**:
  - `rule` TR-1.1: MySQL 连接成功，Session 可正常创建
  - `rule` TR-1.2: `t_users` 表存在且结构与 spec 一致

## Task 2: 用户数据模型与访问层
- **Status**: completed
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 创建 `backend/app/models/user.py`：SQLAlchemy ORM 模型 `User`，映射 `t_users` 表，含 `user_id` 唯一约束
  - 创建 `backend/app/services/user_service.py`：
    - `get_by_user_id(user_id)` 查询用户
    - `create_user(user_id, user_name, password, age)` 创建用户，密码 bcrypt 哈希
    - `verify_password(plain, hashed)` 密码校验
  - 密码哈希：bcrypt 加盐，不存明文
- **Acceptance Criteria Addressed**: AC-4
- **Test Requirements**:
  - `rule` TR-2.1: `User` 模型字段与 `t_users` 表一一对应
  - `rule` TR-2.2: 通过 `user_id` 可查询到用户，密码比对正确返回布尔值
  - `rule` TR-2.3: 创建用户后 `user_pwd` 字段为哈希值，非明文
  - `rule` TR-2.4: 重复 `user_id` 创建抛出 IntegrityError（业务层转 409）

## Task 3: 注册/登录/登出接口
- **Status**: completed
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - 创建 `backend/app/api/auth.py`：
    - `POST /api/auth/register`：注册，字段级校验，user_id 冲突返回 409，成功返回用户信息（不含密码）
    - `POST /api/auth/login`：校验 user_id + 密码，返回 JWT Token
    - `POST /api/auth/logout`：登出
    - `GET /api/auth/me`：获取当前登录用户信息
  - 创建 `backend/app/core/auth.py`：Token 生成、校验依赖 `get_current_user`
  - Pydantic Schema：`RegisterRequest`、`LoginRequest`、`UserResponse`
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-5, AC-6
- **Test Requirements**:
  - `rule` TR-3.1: 新用户注册成功，返回用户信息（不含密码）
  - `rule` TR-3.2: 重复 `user_id` 注册返回 409
  - `rule` TR-3.3: 正确账号登录返回 Token 与用户信息
  - `rule` TR-3.4: 错误密码返回 401
  - `rule` TR-3.5: 携带有效 Token 访问 `/api/auth/me` 返回用户信息
  - `rule` TR-3.6: 无 Token 或无效 Token 访问受保护接口返回 401

## Task 4: 受保护接口接入鉴权
- **Status**: completed
- **Priority**: high
- **Depends On**: Task 3
- **Description**:
  - 为 `/api/chat`、`/api/chat/stream`、`/api/threads/*` 等受保护接口添加 `Depends(get_current_user)`
  - 保留 `/api/health`、注册接口、登录接口为公开接口
- **Acceptance Criteria Addressed**: AC-6
- **Test Requirements**:
  - `rule` TR-4.1: 未登录访问 `/api/chat` 返回 401
  - `rule` TR-4.2: 登录后访问 `/api/chat` 正常

## Task 5: 前端登录/注册页面与鉴权流程
- **Status**: completed
- **Priority**: high
- **Depends On**: Task 3
- **Description**:
  - 创建 `src/views/LoginView.vue`：用户ID/密码输入、登录按钮、错误提示、注册入口链接
  - 创建 `src/views/RegisterView.vue`：用户ID/用户名/密码/年龄表单、前端校验、冲突提示、注册成功跳登录页
  - 路由守卫：未登录跳转到 `/login`，登录用户访问 `/login` 跳转首页
  - Token 存储到 `localStorage`，API 请求统一携带 Authorization 头
  - 导航栏增加登出按钮
- **Acceptance Criteria Addressed**: AC-5, AC-7
- **Test Requirements**:
  - `rule` TR-5.1: 未登录访问任意页面 → 跳转 `/login`
  - `rule` TR-5.2: 登录成功 → 跳转主页面
  - `rule` TR-5.3: 登出 → 清除 Token 并回到登录页
  - `rule` TR-5.4: 请求头携带 `Authorization: Bearer <token>`
  - `rule` TR-5.5: 注册成功后提示并跳转登录页
  - `rule` TR-5.6: 注册重复 user_id 显示冲突提示

## Task 6: 端到端验证
- **Status**: completed
- **Priority**: high
- **Depends On**: Task 4, Task 5
- **Description**:
  - 准备 MySQL `t_users` 表
  - 完整流程：未登录拦截 → 注册新用户 → 登录 → 使用对话 → 登出
- **Acceptance Criteria Addressed**: AC-1~AC-7
- **Test Requirements**:
  - `rule` TR-6.1: 端到端注册-登录-使用-登出流程正常
  - `rule` TR-6.2: 数据库中 `user_pwd` 为哈希值

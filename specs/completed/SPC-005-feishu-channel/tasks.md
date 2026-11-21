# Tasks

- [x] Task 1: 渠道抽象与入口路由
  - [x] SubTask 1.1: 新增 `backend/app/channels/__init__.py` 与 `base.py`，定义 `IncomingMessage`（channel / chat_id / sender_id / message_id / text）、`MessageHandler` 类型与 `Channel` 抽象（name / start / reply），参考 `agent_assistant/channels/base.py`
  - [x] SubTask 1.2: 新增 `backend/app/channels/router.py`，实现 `ChannelRouter`：按渠道名注册处理器与渠道、`dispatch(message)` 查表分发、未注册渠道报错、`start_all()` 在后台守护线程启动全部渠道并隔离异常

- [x] Task 2: 飞书长连接渠道
  - [x] SubTask 2.1: 新增 `backend/app/channels/feishu.py`，实现 `FeishuChannel`：用 `lark_oapi` 长连接订阅 `im.message.receive_v1`，解析文本、剥离 @ 提及占位符，空文本与非文本忽略
  - [x] SubTask 2.2: 渠道内用 `queue.Queue` + 单个后台工作线程串行处理消息，调用路由入口取得回复，避免阻塞长连接心跳
  - [x] SubTask 2.3: 通过 `im.v1.message.reply` 以纯文本消息回复原消息，失败仅记录日志

- [x] Task 3: IM 身份映射与用户创建
  - [x] SubTask 3.1: 新增 `backend/app/models/im_identity.py`，定义 `ImIdentity`（channel / sender_id / user_id / 创建与更新时间），`(channel, sender_id)` 唯一
  - [x] SubTask 3.2: `backend/app/core/db.py` 的 `init_db` 导入 `ImIdentity`，随 `create_all` 自动建表
  - [x] SubTask 3.3: 在 `backend/app/services/user_service.py` 增加 `get_or_create_im_user(db, channel, sender_id) -> User`：先查映射表，未命中则创建系统用户（`user_id={channel}_{sender_id}`、随机密码 bcrypt 哈希、`state=1`）并写入映射
  - [x] SubTask 3.4: 创建流程使用独立 `SessionLocal` 会话，异常时回滚并记录日志；不生成 JWT、不校验 Web 登录态

- [x] Task 4: IM 消息处理管线
  - [x] SubTask 4.1: 新增 `backend/app/channels/handler.py`，实现 `handle_im_message(message) -> str`：通过映射取得系统用户、生成 `thread_id={channel}_{chat_id}_{sender_id}`、`memory_manager.build_context` 组装上下文
  - [x] SubTask 4.2: 通过 `asyncio.run` 在进程内调用 `get_agent().ainvoke`（不请求 HTTP 接口），追踪配置带 `car-sales-agent`、渠道场景标签与 user/thread 元数据；提取最后一条 AI 消息文本
  - [x] SubTask 4.3: 识别 `final_recommendation_tool` 中断，提取 `recommendation` 并追加"该推荐需人工确认，请登录 Web 端完成确认"
  - [x] SubTask 4.4: 调用 `memory_manager.update_memory` 持久化本轮对话与摘要

- [x] Task 5: 配置与依赖
  - [x] SubTask 5.1: `backend/app/core/config.py` 增加 `FEISHU_ENABLED`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET`
  - [x] SubTask 5.2: `backend/.env.example` 增加飞书配置项与说明
  - [x] SubTask 5.3: `backend/requirements.txt` 增加 `lark-oapi`

- [x] Task 6: 启动集成
  - [x] SubTask 6.1: `backend/app/main.py` 启动事件中构建 `ChannelRouter`，注册 IM 消息处理器；`FEISHU_ENABLED` 且凭据完整时创建并注册 `FeishuChannel`，调用 `start_all()`
  - [x] SubTask 6.2: 未启用或缺凭据时不创建渠道、不导入 `lark_oapi`；渠道异常不影响 HTTP 服务

- [x] Task 7: 联调验证
  - [x] SubTask 7.1: 启动后端，未启用时 `/api/health` 正常；占位凭据启用时渠道线程发起长连接、鉴权失败仅记录日志且 HTTP 服务正常。真实长连接需用用户自己的应用凭据实测
  - [x] SubTask 7.2: 用进程内模拟 IM 消息验证处理管线：返回 Agent 回答，`t_users`、`t_im_identities` 与 `data/conversations/` 记录均生成（验证后已清理测试数据）
  - [x] SubTask 7.3: 同一会话连续两轮模拟消息，第二轮正确引用上一轮推荐，对话记录累计 2 轮；群聊 @ 占位符剥离逻辑已实现并验证。真实飞书私聊/群聊收发需用户启用后实测

# Task Dependencies
- Task 2 depends on Task 1
- Task 4 depends on Task 1, Task 3
- Task 6 depends on Task 1, Task 2, Task 4, Task 5
- Task 7 depends on Task 1, Task 2, Task 3, Task 4, Task 5, Task 6

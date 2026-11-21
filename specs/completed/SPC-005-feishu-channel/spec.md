# SPC-005 多渠道 IM 接入与飞书渠道 Spec

## Why
当前汽车销售助手只通过 Web 页面使用，销售顾问与用户日常沟通主要在飞书。需要让用户直接在 IM 里向机器人提问，复用现有的 Agent Harness、对话持久化与摘要记忆能力。渠道层需按"多渠道接入 + 统一入口路由"设计，本期落地飞书（参考 `D:\aiworkspace\agent_assistant` 的长连接 + `lark_oapi` 方案），后续新增 IM 只增加适配器，不改核心处理管线。

## What Changes
- 新增 `backend/app/channels/` 模块：
  - `base.py`：统一入站消息对象 `IncomingMessage` 与 `Channel` 抽象（参考 `agent_assistant/channels/base.py`）
  - `router.py`：`ChannelRouter` 统一入口，维护"渠道名 -> 消息处理器"路由表，负责渠道注册、统一分发与渠道启动
  - `feishu.py`：基于 `lark_oapi` 长连接接收事件、通过 OpenAPI 回复消息的 `FeishuChannel`
  - `handler.py`：与渠道无关的消息处理管线（身份映射 -> 记忆上下文 -> Agent -> 持久化）
- 后端启动时按配置构建渠道、注册到路由并启动，运行在独立线程，不影响 HTTP 服务
- 新增 IM 身份映射表 `t_im_identities`，用 `channel + sender_id` 映射到系统 `user_id`，IM 身份与 `t_users` 解耦
- 首次收到某个 IM 用户消息时，自动创建系统用户与映射记录（不参与 Web 登录）
- 接入鉴权边界：IM 渠道在进程内直接调用 Agent 与记忆服务，不经过 `/api/chat`，不需要 JWT 与登录态
- 新增配置项 `FEISHU_ENABLED`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET`
- `requirements.txt` 增加 `lark-oapi` 依赖，`.env.example` 增加飞书配置说明

## Impact
- Affected specs: SPC-001（Agent Harness）、SPC-002（用户体系）、SPC-003（对话持久化与记忆）
- Affected code:
  - 新增 `backend/app/channels/base.py`、`router.py`、`feishu.py`、`handler.py`
  - 新增 `backend/app/models/im_identity.py`（IM 身份映射 ORM 模型）
  - 修改 `backend/app/core/db.py`（建表时导入新模型）
  - 修改 `backend/app/core/config.py`（飞书配置）
  - 修改 `backend/app/services/user_service.py`（IM 身份映射与用户获取或创建）
  - 修改 `backend/app/main.py`（启动时构建路由并拉起渠道）
  - 修改 `backend/requirements.txt`、`backend/.env.example`

## ADDED Requirements

### Requirement: 多渠道接入与入口路由
系统 SHALL 提供与 IM 无关的渠道抽象和统一消息入口路由，本期仅落地飞书渠道。

- `Channel` 抽象定义渠道名、启动监听、回复消息三个能力；渠道从原始事件解析出统一 `IncomingMessage`（渠道名、会话 ID、发送者 ID、消息 ID、文本）
- `ChannelRouter` 维护"渠道名 -> 消息处理器"路由表：`dispatch(message)` 按 `message.channel` 查找处理器并返回回复文本，未注册的渠道直接报错
- 渠道收到消息后统一提交给路由入口，不直接绑定业务处理器；新增 IM 只需实现 `Channel` 适配器并注册，不改路由与处理管线
- `ChannelRouter.start_all()` 在后台守护线程中启动全部已注册渠道，单个渠道异常只记录日志，不阻断其他渠道与 HTTP 服务

#### Scenario: 飞书渠道注册与分发
- **WHEN** 后端启动且飞书渠道已启用并注册到路由
- **THEN** 飞书消息经 `dispatch` 路由到 IM 消息处理器，处理结果由飞书渠道回复

#### Scenario: 新增第二种 IM
- **WHEN** 后续新增企业微信等渠道适配器并注册到路由
- **THEN** 仅新增适配器与配置项，路由层、消息处理管线与记忆逻辑无需改动

#### Scenario: 渠道异常隔离
- **WHEN** 某个渠道建立连接失败
- **THEN** 系统记录错误日志，其他渠道与 FastAPI 接口正常运行

### Requirement: 飞书长连接渠道
系统 SHALL 通过飞书长连接（WebSocket）接收 `im.message.receive_v1` 事件，不依赖公网回调地址。

- 渠道由 `FEISHU_ENABLED` 开关控制，默认关闭；关闭时不启动 `lark_oapi` 客户端
- 开启时后端启动阶段在独立后台线程中建立长连接
- 仅处理文本消息：解析 `message.content` 中的 `text`，剥离群聊 @ 提及占位符（形如 `@_user_1`）后为空则忽略
- 回复使用 OpenAPI `im.v1.message.reply`，以纯文本消息回复原消息

#### Scenario: 私聊提问
- **WHEN** 飞书用户私聊机器人发送"预算15万，推荐一台家用SUV"
- **THEN** 机器人调用 Agent 生成回答，并以文本消息回复该用户

#### Scenario: 群聊 @ 机器人
- **WHEN** 用户在群聊中 @ 机器人提问
- **THEN** 系统剥离 @ 占位符后得到问题文本，正常调用 Agent 并回复

#### Scenario: 非文本消息
- **WHEN** 用户发送图片、文件或语音消息
- **THEN** 系统记录日志并忽略，不调用 Agent、不回复

#### Scenario: 未启用飞书渠道
- **WHEN** `FEISHU_ENABLED=false`
- **THEN** 后端启动时不建立飞书长连接，Web 接口行为不变

### Requirement: IM 身份与会话映射
系统 SHALL 通过独立映射表把 IM 身份映射为系统用户，并按渠道、会话与发送者隔离记忆。

- 新增 `t_im_identities` 表：`channel`、`sender_id`、`user_id`、创建/更新时间，`(channel, sender_id)` 唯一
- 首次收到某渠道发送者消息时：创建系统用户 `user_id={channel}_{sender_id}`（飞书为 `feishu_{open_id}`），并在映射表写入一条记录
- 后续消息先查映射表得到 `user_id`，再复用已有系统用户；映射表是 IM 身份与 Web 账号解耦的唯一依据，后续可与 Web 账号绑定并更新映射
- 系统用户创建时 `user_name` 为可读的渠道用户标识，`user_pwd` 为随机密码的 bcrypt 哈希，`state=1`，不生成登录 Token
- 对话线程 `thread_id` 为 `{channel}_{chat_id}_{sender_id}`，保证不同渠道、群聊中不同用户、不同会话的 Agent 状态与记忆互不串扰
- 对话记录与摘要复用现有 `conversation_store` / `memory_manager`，落在 `data/conversations/{user_id}/` 下

#### Scenario: 首次交互自动创建用户与映射
- **WHEN** 某飞书用户第一次向机器人发送消息
- **THEN** `t_users` 中出现 `user_id=feishu_{open_id}` 的新用户，`t_im_identities` 中出现对应映射记录，且本轮对话正常完成

#### Scenario: 再次交互复用映射
- **WHEN** 同一飞书用户第二次发送消息
- **THEN** 通过映射表直接定位用户，不重复创建用户与映射记录

#### Scenario: 群聊多用户隔离
- **WHEN** 两个飞书用户在同一群聊中分别向机器人提问
- **THEN** 两人使用不同的 `thread_id` 与用户目录，记忆与 Agent 状态互不影响

#### Scenario: 后续绑定 Web 账号
- **WHEN** 后续把某个 IM 映射绑定到已有 Web 账号
- **THEN** 该映射记录的 `user_id` 更新为目标账号，IM 侧后续消息使用该账号的会话与记忆

### Requirement: Agent 调用与记忆
系统 SHALL 复用与 Web 端一致的上下文构建与持久化逻辑处理 IM 消息。

- 使用 `memory_manager.build_context` 组装"历史摘要 + 最近 3 轮"上下文，再追加当前用户消息
- 以 `agent.ainvoke` 调用现有 Harness 单例，追踪配置包含业务标识、渠道场景标签（如 `feishu`）与 `user_id`、`thread_id`
- 从结果中提取最后一条 AI 消息的文本作为回复内容
- 回复后调用 `memory_manager.update_memory` 持久化本轮对话并增量更新摘要

#### Scenario: 多轮对话
- **WHEN** 飞书用户连续提出多个购车相关问题
- **THEN** 后续回答能引用摘要与最近轮次中的预算、偏好等信息

#### Scenario: 消息顺序
- **WHEN** 同一用户短时间内连续发送多条消息
- **THEN** 渠道按到达顺序串行处理，回复与提问一一对应

### Requirement: 接入鉴权边界
系统 SHALL 让 IM 渠道在进程内直接调用 Agent 与记忆服务，不经过 Web HTTP 接口与 JWT 鉴权。

- 渠道处理管线直接使用 `get_agent()`、`memory_manager`、`conversation_store`、`user_service`，不请求 `/api/chat` 等需要登录态的接口
- 不为 IM 用户生成 JWT，不要求 IM 用户登录 Web，不依赖 `get_current_user` 依赖
- Agent 工具（车型数据、知识库检索）均在进程内调用，不产生额外 HTTP 鉴权
- 飞书侧身份校验由长连接与飞书应用凭据保证，不做业务侧登录校验

#### Scenario: 飞书用户未登录 Web
- **WHEN** 从未在 Web 端注册或登录的飞书用户直接向机器人提问
- **THEN** 系统在进程内完成身份映射与 Agent 调用，正常回复，不出现 401/未授权错误

#### Scenario: Web 鉴权不受影响
- **WHEN** IM 渠道启用并运行
- **THEN** Web 端接口仍按原有 JWT 鉴权逻辑工作，IM 渠道不共享也不绕过 Web 登录态


系统 SHALL 在 Agent 触发 `final_recommendation_tool` 人工确认中断时，向 IM 用户返回推荐内容并提示到 Web 端确认。

- 从本轮结果的最后一条 AI 消息中识别 `final_recommendation_tool` 调用，取出参数 `recommendation`
- 回复文本为推荐内容追加固定提示"该推荐需人工确认，请登录 Web 端完成确认"
- 本轮回复内容照常持久化到对话记录，保证后续上下文连续

#### Scenario: 触发推荐审批
- **WHEN** Agent 在给出最终购车推荐前调用 `final_recommendation_tool` 并触发中断
- **THEN** 飞书收到推荐内容与"请登录 Web 端完成确认"的提示，本轮对话被记录

#### Scenario: 未触发中断
- **WHEN** Agent 正常完成回答，没有触发审批中断
- **THEN** 直接回复回答文本，不附加审批提示

### Requirement: 配置与依赖
系统 SHALL 通过配置项与依赖声明支持渠道的启停与部署。

- `backend/app/core/config.py` 增加 `FEISHU_ENABLED: bool = False`、`FEISHU_APP_ID: str = ""`、`FEISHU_APP_SECRET: str = ""`
- `backend/.env.example` 增加上述三项及说明
- `backend/requirements.txt` 增加 `lark-oapi`

#### Scenario: 配置缺省
- **WHEN** 未配置 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`
- **THEN** 飞书渠道不启动，后端其他功能不受影响

## Assumptions
- 飞书开放平台已创建企业自建应用并开启机器人能力，订阅 `im.message.receive_v1` 事件，使用长连接接收方式
- 开发环境已安装 `lark-oapi`（实测 1.7.5 可用）
- MySQL 可正常连接，用户自动创建依赖 `t_users` 表，映射表 `t_im_identities` 由启动时 `create_all` 自动创建
- 每个渠道使用单个后台工作线程串行处理消息，当前业务量级下足够，不引入消息队列
- 群聊中机器人默认仅在 @ 时收到消息（受飞书应用权限配置影响）

## Non-Goals
- 本期不接入飞书以外的第二种 IM，仅完成抽象与路由预留
- 本期不实现 IM 身份与 Web 账号的绑定入口，仅预留 `t_im_identities` 映射表
- 不支持卡片、图片、文件、富文本消息的解析与回复
- 不实现 IM 内的"确认/取消"审批交互，审批统一在 Web 端完成
- 不做 IM 消息去重、失败重投与消息队列
- 不新增飞书 HTTP 回调接口，不做 Web 端与 IM 会话的双向同步
- 不支持在 Web 端查看 IM 渠道产生的会话列表或消息记录界面

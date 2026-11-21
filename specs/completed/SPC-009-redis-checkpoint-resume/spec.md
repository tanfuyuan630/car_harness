# Spec: LangGraph 会话持久化到 Redis 并支持跨重启中断恢复

## 1. Problem

当前 Agent 的 Checkpointer 默认使用 `MemorySaver`，LangGraph 的线程状态只存在于后端进程内存，且缺少统一的错误分级与恢复策略：

1. 后端重启或进程崩溃后，`final_recommendation_tool` 触发的中断现场丢失，用户无法再点击“批准”恢复执行。
2. 多实例部署时，请求落到不同实例会读不到对方的会话状态。
3. Web 端刷新页面或切换会话后，不会重新查询中断，审批卡片消失；切换会话还可能残留上一个会话的审批卡片。
4. 飞书 IM 用户收到“请登录 Web 端确认”的提示，但 IM 用户由渠道自动创建，没有 Web 登录密码，实际无法完成审批。
5. 现有 `CHECKPOINTER_TYPE=sqlite` 分支依赖本地文件，仅适合单机，与统一外部存储的方向不一致。
6. 错误处理没有分级：网络抖动、限流、超时直接失败；工具异常或 JSON 解析失败直接冒泡；缺少参数或指令模糊时 Agent 容易猜测；未知异常与临时错误混在一起。

## 2. Users

- Web 端购车用户：提交需求后离开页面，重新打开仍能看到待审批推荐并完成批准；信息不足时能收到追问并补充。
- 飞书 IM 用户：在对话中直接回复审批指令或补充信息，无需登录 Web。
- 销售顾问：多实例部署下，任意实例都能读取同一会话的中断现场。
- 开发者/运维：临时错误自动恢复；可恢复错误不打断用户；致命错误带线程与检查点信息，便于人工排查后断点重跑。

## 3. Goals

1. 使用 Redis 8.0 作为 LangGraph Checkpointer 存储，会话检查点与待处理写入全部持久化。
2. Agent 中断后，后端重启或换实例仍能查询中断并完成恢复执行。
3. 中断恢复覆盖 Web 非流式、Web 流式、页面刷新、会话切换与飞书 IM。
4. 按四类错误执行不同策略：
   - 临时错误：tenacity 在节点内自动重试。
   - LLM 可恢复错误：错误写入 State，路由回 Agent 节点重新生成。
   - 用户可修复错误：`interrupt()` 暂停，等待用户补充后 resume。
   - 未知/致命错误：冒泡并记录线程与检查点，人工排查后断点重跑。
5. 检查点默认 3 天过期；未完成任务续期，已完成且超过保留期的任务主动清理。

## 4. Non-Goals

- 不改造对话 Markdown 持久化（`data/conversations`）与增量摘要机制。
- 不引入 Redis Cluster、Sentinel 或多租户隔离。
- 不新增前端页面，只在现有审批卡内增加“补充信息”与“重试”状态。
- 不实现 IM 富交互审批卡片或“修改后通过”；IM 仅支持批准/拒绝与文本补充。
- 不实现同一线程的并发请求串行化；并发写入仍由 LangGraph 最后写入者覆盖。
- 不实现子 Agent 内部独立中断；本期中断统一由主 Agent 工具触发。
- 不保留 `sqlite` Checkpointer 分支。
- 不在本 Spec 内安装 RedisJSON/RediSearch 模块；由用户稍后安装并重启 Redis。
- 不改造 Redis 服务端架构（不引入 Cluster 或 Sentinel）。

## 5. Constraints

- **Redis 版本**：8.0 及以上，使用 `.env` 中已提供的实例（实测 8.0.6）。
- **依赖**：`langgraph-checkpoint-redis>=0.5.2`、`redis>=5.2.1`、`tenacity>=8.2`。
- **模块前置**：当前实例尚未启用 RedisJSON/RediSearch（`JSON.SET`、`FT.CREATE` 均返回 `unknown command`）。用户将稍后安装并重启 Redis；安装完成前后端启动会失败，不做内存兜底。
- **失败策略**：Redis 不可用或初始化失败时后端启动失败并输出明确错误，不自动回退到内存或文件。
- **重试边界**：只重试可恢复的临时错误；有次数上限；鉴权、参数、业务校验错误不重试。
- **安全**：Redis 密码只从环境变量读取，不写入代码与日志。
- **兼容性**：现有中断查询与恢复接口的路径、请求体保持兼容；`interrupts[].value` 保留，新增 `kind` 字段。

## 6. 场景覆盖矩阵

| 场景 | 改造前 | 改造后 |
|------|--------|--------|
| Web 流式对话中断 | 支持（`done` 后查询中断） | 支持 |
| Web 非流式 `/api/chat` | 支持，但使用同步 `get_state` | 改为 `aget_state` 后支持 |
| 刷新页面 / 重新打开会话 | 不支持，审批卡不出现 | 支持，挂载时查询中断 |
| 切换会话 | 不支持，且残留旧审批卡 | 支持，清空后重新查询 |
| 后端重启 | 不支持，MemorySaver 丢失 | 支持，检查点在 Redis |
| 多实例部署 | 不支持 | 支持，共享同一 Redis |
| 飞书 IM 审批 | 不支持，提示去 Web | 支持，回复“批准/拒绝”或补充信息 |
| 临时错误（网络抖动、429、超时） | 直接 502 或流式错误 | tenacity 节点内重试，重试耗尽后保留检查点 |
| LLM 可恢复错误（工具失败、JSON 解析失败） | 直接冒泡 | 错误写入 State，回 Agent 重新生成，最多 2 次 |
| 用户可修复错误（缺参数、指令模糊） | Agent 容易猜测 | `interrupt()` 追问，Web/IM 补充后 resume |
| 未知/致命错误（逻辑 Bug、依赖崩溃） | 直接 500 | 冒泡并记录 thread_id/checkpoint_id，人工修复后断点重跑 |
| Redis 瞬时断连 | 不涉及 | 客户端指数退避重试；持续失败返回 503，不回退 |
| 同一线程并发请求 | 不支持 | 明确限制，不在本期处理 |

## 7. Functional Requirements

### FR-1: Redis 与错误重试配置项

在 `backend/app/core/config.py` 新增/调整：

- `CHECKPOINTER_TYPE: Literal["redis", "memory"] = "redis"`：默认 Redis；`memory` 仅用于测试。
- `REDIS_HOST: str = "127.0.0.1"`
- `REDIS_PORT: int = 6379`
- `REDIS_PASSWORD: str = ""`
- `REDIS_DB: int = 0`
- `REDIS_CHECKPOINT_TTL_MINUTES: int = 4320`：检查点默认保留 3 天。
- `REDIS_MAINTENANCE_INTERVAL_SECONDS: int = 3600`：维护任务扫描间隔。
- `REDIS_SOCKET_TIMEOUT_SECONDS: int = 5`
- `REDIS_RETRY_ATTEMPTS: int = 3`
- `LLM_MAX_RETRIES: int = 3`：临时错误自动重试次数。
- `MAX_RECOVERABLE_RETRIES: int = 2`：工具/解析错误回到 Agent 的最大次数。
- `OPENAI_TIMEOUT_SECONDS: int = 120`。
- 新增 `redis_url` 属性，密码使用 URL 编码。

同步更新 `backend/.env.example`。

### FR-2: 官方 Redis Checkpointer 构建与生命周期

使用 `langgraph-checkpoint-redis` 的 `AsyncRedisSaver`，新建 `backend/app/services/checkpoint_store.py`：

1. `memory` 模式返回 `MemorySaver`。
2. `redis` 模式创建 `AsyncRedisSaver`：
   - 连接使用 `redis_url`，并传入 `ttl={"default_ttl": REDIS_CHECKPOINT_TTL_MINUTES, "refresh_on_read": True}`。
   - 通过连接参数配置 `REDIS_SOCKET_TIMEOUT_SECONDS` 与 `Retry(ExponentialBackoff(base=0.2, cap=2.0), retries=REDIS_RETRY_ATTEMPTS)`；实现时按已安装版本签名选择 `from_conn_string(..., connection_args={...})` 或传入预配置的 `redis.asyncio.Redis` 客户端。
3. `setup_checkpointer()`：进入异步上下文并调用 `await saver.asetup()`，由官方包创建 RediSearch 索引。
   - 连接失败：抛出包含 Redis 地址的 `RuntimeError`。
   - 模块缺失（`JSON.SET`/`FT.CREATE` 不可用）：抛出明确错误，提示需安装 RedisJSON/RediSearch 或使用 Redis Stack。
   - 不降级为内存或文件。
4. `close_checkpointer()`：退出异步上下文、关闭客户端并清空单例。

### FR-3: 注册中心与启动接线

- `registry.checkpointer` 复用 `checkpoint_store`，删除 `sqlite` 分支。
- `main.py` 启动时先 `await setup_checkpointer()`，关闭时 `await close_checkpointer()`。
- 启动失败直接终止，不进入服务状态。

### FR-4: 检查点读取与中断类型

- `GET /api/threads/{thread_id}/interrupts` 改为异步，使用 `await agent.aget_state(config)`。
- `POST /api/chat` 结束后的中断判断改为 `await agent.aget_state`。
- `POST /api/threads/{thread_id}/resume` 恢复后的再次中断检查改为 `await agent.aget_state`。
- 中断项返回 `{"value": <原值>, "kind": "recommendation" | "input_required"}`：
  - 字符串或包含 `recommendation` 的值视为 `recommendation`；
  - 包含 `type="input_required"` 的字典视为 `input_required`。
- 保持原有 `value` 字段，前端与 IM 按 `kind` 分支处理。
- 恢复后继续调用 `update_last_assistant`。

### FR-5: 会话跟踪登记

新建 `backend/app/services/thread_registry.py`：

- `track_thread(user_id, thread_id)`：写入 `lg:threads`（SET）与 `lg:thread:{thread_id}`（HASH：`user_id`、`last_active_at`），TTL 与检查点一致。
- `list_threads`、`get_thread_meta`、`untrack_thread`。
- 创建会话、普通/流式对话、恢复、重试、IM 消息成功路径均登记。

### FR-6: 检查点过期与维护任务

新建 `backend/app/services/checkpoint_maintenance.py`：

1. 遍历已登记线程，`aget_state` 存在 `interrupts` 的线程刷新 TTL（包含待补充信息与待审批）。
2. 无中断且 `now - last_active_at > TTL` 的线程调用 `adelete_thread` 并 `untrack_thread`。
3. 启动时创建后台任务，关闭时取消；间隔由 `REDIS_MAINTENANCE_INTERVAL_SECONDS` 控制。
4. 单线程失败只记录日志，不中断整轮扫描。

### FR-7: 错误分级与恢复策略

新建 `backend/app/agent/error_policy.py`，定义统一错误类型与分类器：

```text
ErrorKind: TRANSIENT | RECOVERABLE | USER_FIXABLE | FATAL
```

分类规则：

- **TRANSIENT**：`RateLimitError`、`APITimeoutError`、`APIConnectionError`、`InternalServerError`、Redis `ConnectionError`/`TimeoutError`、外部 HTTP 超时。
- **RECOVERABLE**：工具调用异常、参数校验失败、`JSONDecodeError`、结构化输出解析失败。
- **USER_FIXABLE**：业务关键参数缺失（预算、用途、车型、城市等）或指令存在多解，由 Agent 判断并主动追问。
- **FATAL**：其余未识别异常，包括代码逻辑错误与底层依赖崩溃。

#### 7.1 临时错误：tenacity 节点内重试

- 在 `backend/app/agent/llm.py` 与可重试的工具调用外使用 tenacity：
  - `retry_if_exception` 使用分类器判定 `TRANSIENT`；
  - `stop_after_attempt(LLM_MAX_RETRIES)`；
  - `wait_exponential_jitter(initial=0.5, max=8)`；
  - `reraise=True`。
- 模型请求传入 `OPENAI_TIMEOUT_SECONDS`。
- 流式响应一旦向用户输出 token，不再做整段重试；中途失败按 FR-9 的可重试错误处理。
- 重试耗尽抛出 `TransientExhausted`，由接口层返回 502/503 并标记 `retryable=true`。

#### 7.2 LLM 可恢复错误：写入 State 并回到 Agent

- 工具调用统一经过 `recoverable_tool` 包装：捕获异常后返回 `ToolMessage(status="error", content="[工具错误] ...")`，不向上抛。
- 结构化输出解析失败时，将原始文本与解析错误作为错误消息追加到 `messages`。
- LangGraph 的工具节点会把错误消息送回 Agent 节点，Agent 可重新生成参数或改用其他工具。
- 连续错误 ToolMessage 数量超过 `MAX_RECOVERABLE_RETRIES` 时升级为 `FatalError`，避免无限循环。
- 成功恢复后对用户无感，不返回 502，也不写入错误文本到正式对话。

#### 7.3 用户可修复错误：interrupt 等待补充

- 新增工具 `ask_user_for_input(question, missing_fields)`，注册到 `interrupt_on`。
- 主提示词补充规则：最终推荐或高成本动作前，若预算、用途、车型、城市等关键参数缺失或存在多解，必须调用该工具，不得猜测。
- 中断值为 `{"type": "input_required", "question": "...", "missing_fields": [...]}`。
- 恢复时沿用 `/api/threads/{thread_id}/resume`：`decision="edit"` 且 `edited_content` 为用户补充内容；`decision="reject"` 表示取消。
- Web 审批卡按 `kind=input_required` 展示问题、输入框与提交按钮。
- IM 在 `input_required` 状态下，除“拒绝/取消”外的任意非空文本都作为补充内容恢复。

#### 7.4 未知/致命错误：冒泡并保留检查点

- 图执行与工具层不捕获 `FATAL`；统一在接口层记录日志：`thread_id`、`checkpoint_id`、异常栈。
- 非流式返回 HTTP 500，body `{"detail": "...", "fatal": true, "retryable": false}`。
- 流式 `error` 事件带 `kind="fatal"` 与 `retryable=false`。
- 检查点保留，开发者修复后通过 `/retry` 从最后成功检查点重跑。
- 不自动重试致命错误。

### FR-8: 断点续跑接口

新增 `POST /api/threads/{thread_id}/retry`：

- `aget_state` 存在待处理中断（审批或补充信息）返回 409，并提示先完成当前中断。
- `state.next` 为空返回 409“该线程没有可重试的任务”。
- 否则 `await agent.ainvoke(None, config)`，从最后一个成功检查点继续未完成步骤。
- 不重新拼接历史消息、不重复写入用户轮次。
- 成功后 `update_last_assistant`，返回 `{"thread_id", "content", "interrupted"}`。
- 失败按 FR-7 分类处理；临时错误可再次调用，致命错误需开发者修复后调用。

### FR-9: 失败持久化与响应约定

- 非流式 `/api/chat`：
  - 临时错误耗尽：502，`{"detail", "retryable": true}`。
  - 可恢复错误：由 Agent 内部恢复，不返回错误。
  - 致命错误：500，`{"detail", "fatal": true, "retryable": false}`。
  - Redis 持续不可用：503，`{"detail": "Redis 不可用", "retryable": true}`。
- 流式 `/api/chat/stream`：`error` 事件 data 包含 `kind`（transient/recoverable/fatal）与 `retryable`；可重试错误不把错误文本写入正式对话，仅保存用户轮次。
- 失败轮次均保留检查点，供 `/retry` 使用。

### FR-10: 前端交互

`frontend/src/views/ChatView.vue`：

- 挂载与切换会话后查询中断；切换/新建时清空旧审批卡。
- 按 `kind` 渲染：
  - `recommendation`：保留批准、拒绝、修改后通过。
  - `input_required`：展示问题与输入框，提交调用 `resume(edit, 用户输入)`，取消调用 `resume(reject)`。
- 收到 `retryable=true` 错误时显示“重试”按钮，调用 `/retry`，成功后替换最后一条助手消息；若返回 `interrupted=true` 则重新查询中断。
- 致命错误显示“已保留会话进度，请联系开发排查”的提示，不展示重试按钮。

### FR-11: 飞书 IM 处理

`backend/app/channels/handler.py`：

1. Agent 调用前读取 `aget_state` 判断中断类型。
2. `recommendation`：识别“批准/通过/同意/approve”与“拒绝/驳回/reject”；其他文本返回审批提示。
3. `input_required`：除“拒绝/取消”外的任意非空文本作为补充内容，通过 `Command(resume=文本)` 恢复；拒绝则 `resume("reject")`。
4. 恢复后 `update_last_assistant` 覆盖中断时保存的内容；若再次中断，按新类型返回提示。
5. `APPROVAL_TIP` 改为“请回复「批准」或「拒绝」完成确认”；补充信息场景提示“请直接回复需要补充的内容”。
6. IM 消息与恢复都调用 `track_thread`。

### FR-12: 依赖与文档

- `requirements.txt` 增加 `langgraph-checkpoint-redis>=0.5.2`、`redis>=5.2.1`、`tenacity>=8.2`。
- `.env.example` 增加 Redis、TTL、维护、重试与超时配置。
- `README.md` 更新 Redis 8 前置条件、错误分级策略、Web/IM 审批与补充信息、重试与断点续跑、并发限制。

### FR-13: 测试

- 单元测试（不依赖 Redis）：
  - `redis_url` 拼接、memory/redis 模式选择、Redis 不可用失败。
  - 错误分类：429/超时/连接错误为 TRANSIENT；工具异常/JSONDecodeError 为 RECOVERABLE；缺失参数为 USER_FIXABLE；其余 FATAL。
  - tenacity 重试：首次 429 后成功；401/400 不重试。
  - 工具错误包装：异常变为错误 ToolMessage；连续错误超过上限升级 FATAL。
  - `ask_user_for_input` 中断结构、resume 补充文本。
  - `/retry` 的 409 分支与 `ainvoke(None, config)` 调用。
  - IM 两类中断的指令解析与分支。
  - 维护任务续期与清理。
- 集成测试（Redis 8，DB 15）：
  - 检查点写入/读取、TTL、`adelete_thread`、双 saver 读取。
  - 跨重启：Web 审批恢复、IM 审批恢复、补充信息恢复。
  - 模拟 429 自动重试成功；模拟工具异常后 Agent 重新生成。
- 现有 40 个测试保持通过。

## 8. Acceptance Criteria

- AC-01：`CHECKPOINTER_TYPE` 默认 `redis`，`memory` 仅测试使用，`sqlite` 分支移除。
- AC-02：Redis 不可用时启动失败，错误含 Redis 地址，不回退内存。
- AC-03：普通对话后 Redis 中存在该线程检查点与写入记录。
- AC-04：触发中断后重启后端，中断查询仍返回待处理内容。
- AC-05：重启后批准恢复成功，返回最终回答且 `interrupted=false`。
- AC-06：检查点默认 TTL 为 3 天，读取自动续期。
- AC-07：维护任务对未完成（审批/补充信息）线程续期。
- AC-08：维护任务删除已完成且超过 3 天的线程并移出索引。
- AC-09：会话列表、历史、审批接口路径与返回结构兼容，`value` 字段保留。
- AC-10：单元测试全部通过；Redis 集成测试在提供 Redis 8 后通过。
- AC-11：所有检查点读取使用 `aget_state`，不再出现同步 `get_state`。
- AC-12：Web 刷新与切换会话后审批卡正确显示且不残留。
- AC-13：IM 批准/拒绝可恢复同一线程，重启后仍有效。
- AC-14：README 说明并发限制，memory 非默认。
- AC-15：临时错误由 tenacity 自动重试，最多 `LLM_MAX_RETRIES` 次；401/400 不重试。
- AC-16：工具调用失败或 JSON 解析失败写入 State（错误 ToolMessage/消息），Agent 重新生成；超过 `MAX_RECOVERABLE_RETRIES` 升级为致命错误。
- AC-17：致命错误冒泡，日志包含 `thread_id` 与 `checkpoint_id`，检查点保留，返回 `fatal=true`。
- AC-18：缺少关键参数或指令模糊时触发 `input_required` 中断；Web 与 IM 补充后 resume 成功。
- AC-19：`/retry` 可从最后成功检查点续跑且不重复用户消息；待审批/无可续跑任务返回 409。
- AC-20：流式失败不把错误文本写入正式对话；前端可重试或补充信息。
- AC-21：Redis 瞬时断连由客户端退避重试；持续不可用返回 503，不回退内存。
- AC-22：中断查询返回 `kind`，前端按 `recommendation` / `input_required` 正确渲染。

## 9. Risks

- **官方包对 Redis 模块的依赖**：当前实例缺少 RedisJSON/RediSearch，用户安装并重启前 `asetup()` 会失败；启动错误需明确提示模块要求，不做静默降级。
- **TTL 与索引一致性**：Redis 自动过期不会同步清理 `lg:threads` 索引，维护任务需补删。
- **异步单例生命周期**：Redis saver 与客户端需在应用启动/关闭钩子内正确初始化与释放。
- **恢复态与 Markdown 双写**：Web 与 IM 恢复成功后都依赖 `update_last_assistant`，两条链路都需测试。
- **可恢复错误的循环风险**：必须限制连续错误 ToolMessage 次数，超过上限转致命错误，避免 Agent 无限重试。
- **重试与副作用**：自动重试只包裹模型调用与幂等工具；图级续跑从最后成功检查点开始，已完成的工具节点不重放。
- **流式丢弃部分输出**：失败时已展示的 token 会被最终回答覆盖，前端需明确“生成中断，可重试”状态。
- **IM 状态机**：待审批期间非指令消息会被拦截为提示，需在文档中说明，避免用户误以为消息丢失。

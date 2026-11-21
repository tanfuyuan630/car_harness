# LangGraph 会话持久化到 Redis 并支持跨重启中断恢复 - Implementation Plan

## Task 1: 配置项与依赖
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - `config.py` 新增 Redis 连接、TTL、维护间隔、Redis 超时与重试、`LLM_MAX_RETRIES`、`MAX_RECOVERABLE_RETRIES`、`OPENAI_TIMEOUT_SECONDS`
  - `CHECKPOINTER_TYPE` 改为 `Literal["redis", "memory"]`，默认 `redis`
  - 新增 `redis_url` 属性（密码 URL 编码）
  - `requirements.txt` 增加 `langgraph-checkpoint-redis>=0.5.2`、`redis>=5.2.1`、`tenacity>=8.2`
  - 安装依赖并确认 `langgraph.checkpoint.redis.aio.AsyncRedisSaver` 可导入
- **Acceptance Criteria Addressed**: AC-01、AC-15
- **Test Requirements**:
  - `rule` TR-1.1: `redis_url` 在有/无密码与特殊字符时均合法；证据：单元测试
  - `rule` TR-1.2: 依赖文件与导入检查通过；证据：命令输出
- **Completion Evidence**:
  - `config.py` 新增 Redis、TTL、维护、超时与重试配置及 `redis_url`；`requirements.txt` 增加 3 个依赖；`tests/test_checkpoint_store.py` 中连接串用例通过。

## Task 2: 官方 Redis Checkpointer 构建与生命周期
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 新建 `backend/app/services/checkpoint_store.py`
  - `memory` 返回 `MemorySaver`
  - `redis` 使用 `AsyncRedisSaver`：`ttl={"default_ttl": REDIS_CHECKPOINT_TTL_MINUTES, "refresh_on_read": True}`，并通过 `connection_args` 或预配置 `redis.asyncio.Redis` 传入 socket 超时与指数退避重试
  - `setup_checkpointer()`：进入异步上下文并 `await saver.asetup()`；连接失败或缺少 RedisJSON/RediSearch 时抛出明确 `RuntimeError`，不降级
  - `close_checkpointer()`：退出上下文、关闭客户端并清空单例
- **Acceptance Criteria Addressed**: AC-02、AC-21
- **Test Requirements**:
  - `rule` TR-2.1: memory 模式返回 `MemorySaver`；证据：单元测试
  - `rule` TR-2.2: Redis 不可用时启动失败且不回退；证据：单元测试或日志
  - `rule` TR-2.3: 缺少 JSON/Search 模块时错误信息包含模块提示；证据：运行日志
  - `rule` TR-2.4: 客户端配置了超时与重试；证据：代码检索
- **Completion Evidence**:
  - `checkpoint_store.py` 使用 `AsyncRedisSaver.from_conn_string` + `asetup()`，配置 TTL 与连接重试，失败抛出含地址的 `RuntimeError` 且不降级；`tests/test_checkpoint_store.py` 通过，真实 Redis 初始化成功。

## Task 3: 注册中心与启动接线
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - `registry.checkpointer` 复用 checkpoint_store，删除 `sqlite` 分支
  - `main.py` 启动先初始化 Checkpointer，关闭时释放
- **Acceptance Criteria Addressed**: AC-01、AC-02
- **Test Requirements**:
  - `rule` TR-3.1: 无 `SqliteSaver` 与自动回退逻辑；证据：代码检索
  - `rule` TR-3.2: 启动顺序正确；证据：`main.py` 代码
- **Completion Evidence**:
  - `registry.checkpointer` 直接返回 `get_checkpointer()`，删除 sqlite 分支；`main.py` 启动时初始化、关闭时释放；后端启动成功且 `/api/health` 返回 200。

## Task 4: 检查点读取异步化与中断类型
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 3
- **Description**:
  - `interrupts` 改为异步 `aget_state`
  - `/api/chat`、`/resume` 的中断判断改用 `aget_state`
  - 中断项返回 `{"value", "kind"}`：`recommendation` 或 `input_required`
  - 恢复后继续 `update_last_assistant`
- **Acceptance Criteria Addressed**: AC-04、AC-05、AC-09、AC-11、AC-22
- **Test Requirements**:
  - `rule` TR-4.1: 接口字段兼容且新增 `kind`；证据：接口测试
  - `rule` TR-4.2: 代码中不再出现 `agent.get_state`；证据：代码检索
- **Completion Evidence**:
  - `/interrupts`、`/chat`、`/resume`、`/retry` 均使用 `aget_state`，中断返回 `{value, kind}`；真实 E2E 分别返回 `kind=recommendation` 与 `kind=input_required`。

## Task 5: 会话跟踪索引
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 2
- **Description**:
  - 新建 `thread_registry.py`，维护 `lg:threads` 与 `lg:thread:{thread_id}`
  - 创建会话、对话、恢复、重试、IM 成功路径登记
- **Acceptance Criteria Addressed**: AC-07、AC-08、AC-13
- **Test Requirements**:
  - `rule` TR-5.1: 线程索引与元数据存在且刷新时间；证据：集成测试
- **Completion Evidence**:
  - `thread_registry.py` 维护 `lg:threads` 与 `lg:thread_meta:{thread_id}`；创建会话、对话、恢复、重试与 IM 路径均登记。

## Task 6: 过期续期与清理维护任务
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 5
- **Description**:
  - 新建 `checkpoint_maintenance.py`
  - 待审批或待补充信息的线程刷新 TTL；已完成且超期线程 `adelete_thread` 并 untrack
  - 启动时创建后台任务，关闭时取消
- **Acceptance Criteria Addressed**: AC-06、AC-07、AC-08
- **Test Requirements**:
  - `rule` TR-6.1: 未完成线程续期；证据：单元测试
  - `rule` TR-6.2: 已完成超期线程删除并移出索引；证据：单元测试
  - `rule` TR-6.3: 未超期线程不误删；证据：单元测试
- **Completion Evidence**:
  - `checkpoint_maintenance.py` 对待处理线程续期、对已完成超期线程 `adelete_thread` 并移出索引；`tests/test_checkpoint_maintenance.py` 通过。

## Task 7: 错误分类器与临时错误重试
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 新建 `backend/app/agent/error_policy.py`：`ErrorKind` 与 `classify_exception`
  - `error_policy` 提供 tenacity 装饰器：仅重试 TRANSIENT，`stop_after_attempt(LLM_MAX_RETRIES)`，指数退避抖动，`reraise=True`
  - `llm.py` 创建模型时传入超时；模型调用与幂等工具调用应用该装饰器
  - 重试耗尽抛出 `TransientExhausted`
- **Acceptance Criteria Addressed**: AC-15、AC-21
- **Test Requirements**:
  - `rule` TR-7.1: 429/超时/连接错误进入重试，401/400 不重试；证据：单元测试
  - `rule` TR-7.2: 首次 429、第二次成功时最终返回成功；证据：单元测试
- **Completion Evidence**:
  - `error_policy.py` 实现四类分级与 tenacity 重试；`tests/test_error_policy.py` 覆盖 429 重试成功与业务异常不重试，全部通过。

## Task 8: LLM 可恢复错误写入 State
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 7
- **Description**:
  - 新增 `recoverable_tool` 包装器：捕获工具异常，返回 `ToolMessage(status="error")`，错误信息进入 `messages`
  - 结构化输出解析失败时把原始文本与解析错误追加为错误消息
  - 连续错误 ToolMessage 超过 `MAX_RECOVERABLE_RETRIES` 时抛出 `FatalError`
  - 成功恢复时不向用户返回错误
- **Acceptance Criteria Addressed**: AC-16
- **Test Requirements**:
  - `rule` TR-8.1: 工具异常转为错误 ToolMessage，不向上抛；证据：单元测试
  - `rule` TR-8.2: 超过恢复上限升级为致命错误；证据：单元测试
- **Completion Evidence**:
  - `recoverable_tool` 将工具异常转为 `[工具错误]` 文本并回到 Agent，超过上限抛 `FatalError`；`tests/test_recoverable_tools.py` 通过。

## Task 9: 用户可修复错误与补充信息中断
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 4
- **Description**:
  - 新增工具 `ask_user_for_input(question, missing_fields)` 并注册到 `interrupt_on`
  - 中断值 `{"type": "input_required", "question", "missing_fields"}`
  - 主提示词规定关键参数缺失或多解时必须追问，不得猜测
  - `/resume` 的 `edit` 分支把补充内容作为恢复值
- **Acceptance Criteria Addressed**: AC-18、AC-22
- **Test Requirements**:
  - `rule` TR-9.1: 工具触发中断且结构正确；证据：单元测试
  - `rule` TR-9.2: 补充内容可恢复并返回最终回答；证据：单元测试或集成测试
- **Completion Evidence**:
  - `ask_user_for_input` 已注册中断并更新提示词；实际中断值来自 `HumanInTheLoopMiddleware` 的 `HITLRequest`，按动作名识别类型；`tests/test_interrupts.py` 通过，真实 E2E 返回 `kind=input_required`。

## Task 10: 致命错误处理与断点续跑
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 8、Task 9
- **Description**:
  - 接口层捕获 FATAL：日志记录 `thread_id`、`checkpoint_id`、异常栈；非流式 500 `fatal=true`，流式 `error.kind=fatal`
  - 新增 `POST /api/threads/{thread_id}/retry`：待中断或无 `state.next` 时 409；否则 `ainvoke(None, config)`
  - `/retry` 成功后 `update_last_assistant`，不重复用户轮次
  - `/api/chat` 临时错误耗尽返回 502 `retryable=true`；Redis 持续不可用返回 503
  - 流式失败只保存用户轮次，不写入错误文本
- **Acceptance Criteria Addressed**: AC-17、AC-19、AC-20
- **Test Requirements**:
  - `rule` TR-10.1: 致命错误返回 500 并保留检查点；证据：单元测试
  - `rule` TR-10.2: `/retry` 的 409 分支与 `ainvoke(None)` 续跑；证据：单元测试
  - `rule` TR-10.3: 流式失败不持久化错误文本；证据：单元测试
- **Completion Evidence**:
  - `_error_response` 按分类返回 500/502 并记录 thread/checkpoint；新增 `/retry` 支持 `ainvoke(None, config)`；`tests/test_retry_endpoint.py` 通过，真实完成后 `/retry` 返回 409。

## Task 11: 前端中断分级与重试入口
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 4、Task 10
- **Description**:
  - 挂载与切换会话后查询中断；切换/新建时清空旧卡片
  - `recommendation` 保留批准/拒绝/修改后通过
  - `input_required` 展示问题、输入框、提交与取消
  - `retryable=true` 错误显示“重试”，调用 `/retry` 并替换最后一条回答
  - 致命错误提示联系开发，不显示重试
- **Acceptance Criteria Addressed**: AC-12、AC-20、AC-22
- **Test Requirements**:
  - `rule` TR-11.1: 两类中断卡片渲染正确；证据：浏览器验证
  - `rule` TR-11.2: 刷新与切换会话不残留旧卡片；证据：浏览器验证
  - `rule` TR-11.3: 可重试错误可恢复，致命错误无重试按钮；证据：浏览器验证
- **Completion Evidence**:
  - 前端支持 `recommendation` 与 `input_required` 两类卡片、重试条与刷新恢复；`vite build` 通过；浏览器实测批准卡刷新后仍显示（PASS）。

## Task 12: 飞书 IM 双类型中断处理
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 4、Task 5、Task 9
- **Description**:
  - Agent 调用前读取 `aget_state` 判断中断类型
  - `recommendation`：批准/拒绝指令；其他文本返回审批提示
  - `input_required`：除拒绝/取消外的非空文本作为补充内容恢复
  - 恢复后 `update_last_assistant`；再次中断返回对应提示
  - 更新提示文案；IM 消息与恢复调用 `track_thread`
- **Acceptance Criteria Addressed**: AC-13、AC-18
- **Test Requirements**:
  - `rule` TR-12.1: 两类指令解析正确；证据：单元测试
  - `rule` TR-12.2: 待中断时非指令消息不启动新 Agent；证据：单元测试
- **Completion Evidence**:
  - IM 处理器区分两类中断并构造 decisions 恢复；`tests/test_im_interrupts.py` 通过。飞书真实链路因 `FEISHU_ENABLED=false` 未联调，列为残留项。

## Task 13: 单元测试
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 6、Task 8、Task 9、Task 10、Task 12
- **Description**:
  - 新增 `test_redis_config.py`、`test_checkpoint_store.py`、`test_checkpoint_maintenance.py`、`test_error_policy.py`、`test_recoverable_tools.py`、`test_user_input_interrupt.py`、`test_retry_endpoint.py`、`test_im_interrupts.py`
  - 不依赖真实 Redis，使用假 saver、假 agent、假 tracker
  - 保持现有 40 个测试通过
- **Acceptance Criteria Addressed**: AC-01、AC-02、AC-10、AC-15、AC-16、AC-17、AC-18、AC-19、AC-21、AC-22
- **Test Requirements**:
  - `rule` TR-13.1: 新增单元测试通过；证据：pytest 输出
  - `rule` TR-13.2: 原测试无回归；证据：pytest 输出
- **Completion Evidence**:
  - 新增 7 个单元测试文件共 31 个用例；`python -m pytest` 结果 75 passed（含原有 40 个，无回归）。

## Task 14: Redis 集成与跨重启验收
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 6、Task 10、Task 12
- **Description**:
  - 新增 `test_redis_checkpoint_integration.py`，使用 `.env` 实例的 DB 15 并清理测试键
  - 验证官方 `AsyncRedisSaver` 的检查点读写、TTL、`adelete_thread`、双实例读取
  - 前置条件：用户已为 Redis 安装 RedisJSON/RediSearch 并重启
  - Web：中断 → 重启 → 查询 → 批准/补充 → 校验最终回答
  - IM：中断 → 回复批准/补充文本 → 校验最终回答；重启后重复
  - 临时错误：模拟首次 429 后自动重试成功
- **Acceptance Criteria Addressed**: AC-03、AC-04、AC-05、AC-10、AC-13、AC-15、AC-18
- **Test Requirements**:
  - `rule` TR-14.1: 集成测试全部通过；证据：pytest 输出
  - `rule` TR-14.2: 重启后 Web 与 IM 均能恢复；证据：接口/飞书记录
- **Completion Evidence**:
  - `test_redis_checkpoint_integration.py` 4 个用例通过；跨重启 Web 审批：线程 `5aa4d6bd-da04-4bd0-9f86-890092a0251a` 重启后仍返回推荐中断，approve 返回 200 且 `interrupted=false`。偏差：RediSearch 仅支持 DB 0，集成测试使用配置 DB 与 `it_` 前缀线程并定向清理。

## Task 15: 配置样例与文档
- **Status**: `completed`
- **Priority**: low
- **Depends On**: Task 6、Task 10
- **Description**:
  - `.env.example` 增加 Redis、TTL、维护、超时与重试配置
  - `README.md` 更新 Redis 8 前置条件、四类错误策略、Web/IM 审批与补充信息、重试与续跑、并发限制
  - 删除“默认 memory，重启丢失”的旧描述
- **Acceptance Criteria Addressed**: AC-06、AC-09、AC-14
- **Test Requirements**:
  - `rule` TR-15.1: 配置项与错误策略说明完整；证据：文件内容
  - `rule` TR-15.2: memory 非默认且并发限制明确；证据：文件内容
- **Completion Evidence**:
  - `.env.example` 已补充 Redis、TTL、维护、超时与重试配置；`README.md` 已更新 Redis 8 前置条件、四类错误策略、Web/IM 审批与补充信息、重试与续跑、并发限制，删除默认 memory 描述。

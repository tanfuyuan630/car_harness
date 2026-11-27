# 后端接口依赖降级 - Implementation Plan

## Task 1: 降级配置项
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - `backend/app/core/config.py` 新增 `DEGRADE_ENABLED`（默认 `True`）、`DEGRADE_FORCE`（默认 `False`）、`RAG_DEGRADE_COOLDOWN_SECONDS`（默认 `60`）
  - `backend/.env.example` 增加同名配置，注明总开关、强制降级与冷却窗口的含义及“修改后重启生效”
- **Acceptance Criteria Addressed**: AC-01、AC-07
- **Test Requirements**:
  - `manual` TR-1.1: 三个配置项均可从环境变量覆盖，代码中无写死数值；证据：代码检索与 `.env.example`

## Task 2: 降级状态与日志模块
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 新建 `backend/app/agent/degrade.py`
  - `DegradeComponent` 枚举：`llm`、`rag`、`checkpoint`、`subagent`
  - `degrade_enabled()`、`force_degraded()` 读取配置
  - `log_degrade(component, reason, **fields)` 统一输出 `[Degrade] component=... reason=... thread=...` 格式的 `WARNING` 日志
  - 请求级 LLM 降档状态：`get_degraded_level()`、`set_degraded_level()`、`reset_request_degrade()`，使用 `ContextVar`
  - 进程级组件状态：`mark_component_degraded()`、`is_component_degraded()`
  - 日志频率控制：同请求同组件只记首次；RAG 冷却期内只记窗口开始一次
- **Acceptance Criteria Addressed**: AC-07、AC-08
- **Test Requirements**:
  - `manual` TR-2.1: 日志格式含组件、原因、线程字段，且不含用户原文；证据：日志抽样

## Task 3: 模型降档
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - `backend/app/agent/llm.py` 的 `TieredChatOpenAI` 增加降档链：`high → medium → low`、`medium → low`、`low` 无更低档
  - 仅在该次调用未输出任何 token 时降档；流式下发首 chunk 后不再降档
  - 逐级尝试，每档一次；全部失败抛出最后一次原始异常
  - 降档成功后写入请求级降档状态，本请求后续模型调用直接使用新档位
  - `LLM_TIER_ENABLED=false` 时不执行降档
- **Acceptance Criteria Addressed**: AC-02、AC-03
- **Test Requirements**:
  - `manual` TR-3.1: 高档模型故障注入后出现 medium、low 降档日志并成功返回；证据：日志与接口响应
  - `manual` TR-3.2: 流式已输出首 token 后断开，不出现降档与重复内容；证据：响应内容与日志

## Task 4: 分类器与强制档位降级
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - `backend/app/agent/tiering.py` 的 `classify_complexity` 异常时，降级开启则返回 `ComplexityLevel.MODERATE` 并记录日志；关闭时保持现有上抛行为
  - `DEGRADE_FORCE=true` 时 `resolve_main_level` 与 `resolve_subagent_level` 直接返回 `SIMPLE`，不调用分类器
  - 同步修订 `tiering.py` 与 SPC-010 冲突的注释说明（降级非静默，有日志）
- **Acceptance Criteria Addressed**: AC-02、AC-07
- **Test Requirements**:
  - `manual` TR-4.1: 分类模型故障注入后按 medium 执行并出现降级日志；证据：日志
  - `manual` TR-4.2: `DEGRADE_FORCE=true` 时无分类器调用日志，模型为 low 档；证据：日志

## Task 5: RAG 降级
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - `backend/app/rag/service.py` 的 `retrieve` 与 `ensure_index` 外层捕获异常，记录降级日志并返回 `[]`
  - 增加冷却截止时间，窗口内直接返回 `[]`，不调用 Chroma、embedding、rerank
  - 冷却到期后允许重试，仍失败则重新冷却并记录新日志
  - `backend/app/agent/tools/rag_tools.py` 的 `_search` 捕获异常作为第二层保护，返回 `{"results": [], "degraded": true}`
  - `DEGRADE_FORCE=true` 时不调用 `rag_service`，直接返回降级载荷
- **Acceptance Criteria Addressed**: AC-04
- **Test Requirements**:
  - `manual` TR-5.1: 断开 Chroma 或使 embedding 失败后，子 Agent 工具返回空结果，整轮仍能回答；证据：日志与接口响应
  - `manual` TR-5.2: 冷却窗口内连续检索不产生底层调用；证据：日志计数

## Task 6: 检查点降级
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - `backend/app/services/checkpoint_store.py` 的 `setup_checkpointer`：Redis 初始化失败且降级开启时改用 `MemorySaver()`，标记 `checkpoint` 降级并记录含地址与原因的日志
  - `DEGRADE_FORCE=true` 时直接使用 `MemorySaver()`，不尝试连接
  - 降级关闭时保持现有抛错行为
  - `backend/app/main.py` 在 `checkpoint` 降级时不启动 `checkpoint_maintenance` 并记录日志
- **Acceptance Criteria Addressed**: AC-05、AC-01
- **Test Requirements**:
  - `manual` TR-6.1: 停止 Redis 后启动应用，服务可用且 `/api/health` 返回 ok；证据：启动日志与接口响应
  - `manual` TR-6.2: `DEGRADE_ENABLED=false` 且 Redis 不可用时启动失败；证据：启动异常堆栈

## Task 7: 子 Agent 委派降级
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - `backend/app/agent/registry.py` 的 `_build_subagents`：降级开启时用 `create_sub_agent(spec)` 预编译并 `with_fallbacks([降级 runnable], exception_key="degrade_error")` 包装为 `CompiledSubAgent`
  - 降级 runnable 记录日志并返回带简短提示的 `AIMessage`，保证返回状态含 `messages`
  - `DEGRADE_FORCE=true` 时不注册任何领域子 Agent（含车型专家），主 Agent 直接回答并记录日志
  - 降级关闭时保持现有 raw `SubAgent` spec 行为
- **Acceptance Criteria Addressed**: AC-06、AC-07、AC-01
- **Test Requirements**:
  - `manual` TR-7.1: 子 Agent 模型故障注入后主 Agent 仍返回 200 且有完整回答；证据：日志与接口响应
  - `manual` TR-7.2: `DEGRADE_FORCE=true` 时无 `task` 委派日志；证据：日志

## Task 8: 请求入口统一重置
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 3
- **Description**:
  - `/api/chat`、`/api/chat/stream`、`/api/threads/{thread_id}/resume`、`/api/threads/{thread_id}/retry` 在调用 Agent 前重置请求级降档状态
  - `backend/app/channels/handler.py` 的 IM 处理管线同样重置，保证 Web 与飞书共用同一逻辑
- **Acceptance Criteria Addressed**: AC-02、AC-09
- **Test Requirements**:
  - `manual` TR-8.1: 连续多轮请求互不影响，上一轮降档状态不残留；证据：日志

## Task 9: 编译检查与回归验证
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1、Task 2、Task 3、Task 4、Task 5、Task 6、Task 7、Task 8
- **Description**:
  - `pyenv exec python -m compileall -q app` 通过
  - 按 AC-01 至 AC-09 逐项核对
  - `DEGRADE_ENABLED=false` 全量回归，确认与改造前一致
- **Acceptance Criteria Addressed**: AC-01 至 AC-09
- **Test Requirements**:
  - `manual` TR-9.1: 关闭降级后四类依赖异常行为与改造前一致；证据：对照日志
  - `manual` TR-9.2: 开启降级后四类场景均可继续服务；证据：降级日志与接口响应

## 验证记录

- Task 1：`config.py` 与 `.env.example` 均含 `DEGRADE_ENABLED`、`DEGRADE_FORCE`、`RAG_DEGRADE_COOLDOWN_SECONDS`，代码中无写死数值。
- Task 2：新增 `app/agent/degrade.py`；实测日志 `[Degrade] component=rag reason=retrieve_failed domain=sales cooldown=60 error=chroma down`，字段完整且不含消息原文。
- Task 3：故障注入实测 `CALLS ['qwen3.8-max-0902', 'qwen-plus', 'qwen-turbo']`、`RESULT ok`、`DEGRADED ComplexityLevel.SIMPLE`；SIMPLE 档失败仅调用 1 次即上抛。
- Task 4：强制降级实测日志 `[Degrade] component=llm reason=forced role=main tier=low`，且 `registry.subagents` 为空，未调用分类器。
- Task 5：`_retrieve` 故障注入后 `retrieve` 两次调用均返回 `[]`，底层仅调用 1 次（冷却窗口生效）。
- Task 6：Redis 指向不可用端口时返回 `SAVER InMemorySaver` 并记录降级日志；`DEGRADE_ENABLED=false` 时抛 `RuntimeError`，启动失败行为保持不变。
- Task 7：`registry.subagents` 构建 8 个子 Agent，`runnable` 类型均为 `RunnableWithFallbacks`；降级 runnable 返回 `【name】暂不可用，请基于通用知识回答，并说明信息可能不完整。`
- Task 8：`main.py` 的 chat、chat-stream、resume、retry 以及 `channels/handler.py` 均在调用 Agent 前执行 `reset_request_degrade()`。
- Task 9：`pyenv exec python -m compileall -q app` 通过；默认模式、强制降级模式、内存检查点模式下 `get_agent()` 均可正常构建。

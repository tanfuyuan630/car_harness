# Spec: 后端接口依赖降级

## 1. Problem

当前后端对四类外部依赖采用“失败即报错”的策略，任一依赖抖动都会让整轮请求失败：

1. **模型**：`TieredChatOpenAI` 选定档位后，若该档位模型限流、超时或不可用，重试耗尽即向上抛错，接口返回 502。SPC-010 明确把“自动降级链”列为 Non-Goal，因此没有任何降档能力。
2. **RAG 知识库**：`RAGService.retrieve` 调用 Chroma、embedding、rerank 任一处异常都会冒泡到子 Agent 工具，最终整轮请求失败；Chroma 索引构建失败同样如此，且每次请求都会重新尝试，耗时被反复放大。
3. **Redis 检查点**：`setup_checkpointer` 在 Redis 不可用或缺少 RedisJSON/RediSearch 时直接抛 `RuntimeError`，应用启动失败，Web 与飞书渠道全部不可用。代码注释明确写了“不回退到内存或文件”。
4. **子 Agent 委派**：deepagents 的 `task` 工具只捕获 `ModelRefusalError` 与 `StructuredOutputValidationError`，其余异常（子 Agent 模型失败、工具未捕获异常、递归超限）直接冒泡，导致主 Agent 整轮失败。

结果是：单个依赖故障会造成全站不可用，而不是局部能力下降。

## 2. Users

- Web 端购车用户与飞书 IM 用户：依赖局部故障时仍能得到回答，而不是直接看到报错。
- 开发者/运维：通过配置开关控制降级行为，通过统一日志定位降级原因、时间与组件。

## 3. Goals

1. 四类依赖（模型、RAG、检查点、子 Agent）在异常时降级，而不是整轮请求失败。
2. 降级既支持**自动触发**（依赖真实异常），也支持**手动强制**（演练与应急）。
3. 降级对用户**完全不可见**：不新增响应字段、不改前端、不改飞书回复文案，只写服务端日志。
4. 提供统一降级日志格式，包含组件、原因、线程与降级目标，便于检索与告警。
5. 关闭降级总开关时，行为与当前完全一致，便于灰度与回滚。

## 4. Non-Goals

- 不实现熔断器的半开自动恢复状态机；仅 RAG 设一个固定冷却窗口，避免对已故障依赖反复发起慢调用。
- 不实现运行时 Redis 热切换：检查点降级只在启动阶段决定，启动成功后 Redis 断开仍按现有策略返回 503。
- 不为降级设计多实例一致性：内存检查点只在当前进程有效，明确不支持多 worker 部署。
- 不引入第二家模型供应商或备用端点，降档只在现有三档模型内部进行。
- 不新增降级状态查询接口、前端提示、飞书提示或数据库记录。
- 不改变现有中断、记忆、会话持久化、RAG 领域隔离与提示词逻辑。
- 不改变 `/api/chat`、`/api/chat/stream` 的响应结构与事件类型。

## 5. Constraints

- **与 SPC-010 的关系**：本 Spec 正式取代 SPC-010 的 Non-Goal“不为模型档位增加自动降级链”与 Constraint“无静默降级”。降级可自动发生，但必须写日志，不属于静默行为。
- **配置驱动**：所有开关与窗口参数来自 `.env`，不写死在代码；修改后重启生效（沿用现有配置机制）。
- **不泄露内容**：降级日志不得记录用户消息原文与模型输出，只记录组件、原因摘要、线程 ID、档位与模型名。
- **并发安全**：请求级降档状态用 `ContextVar` 承载，禁止修改共享模型实例字段。
- **流式不重复**：流式响应一旦已输出 token，不切换模型重试，避免出现重复内容。
- **最小侵入**：不修改 deepagents 内部实现，只使用其公开的 `CompiledSubAgent` 与 `create_sub_agent` 能力。
- **环境**：Windows + PowerShell；后端 cwd 为 `backend`，运行脚本需 `PYTHONPATH=.`。

## 6. 场景覆盖矩阵

| 场景 | 改造前 | 改造后 |
|------|--------|--------|
| 高档模型限流，重试耗尽，尚未输出 token | 502 可重试错误 | 降到 medium 重试一次；仍失败再降到 low；全失败才抛错 |
| 低档模型限流 | 502 | 无更低档，抛原错误 |
| 流式输出中途模型断开 | 报 error 事件 | 保持现状，不切换模型（避免重复 token） |
| 复杂度分类模型超时 | 502，不换档 | 按 medium 执行并记日志（降级开启时） |
| embedding/Chroma/rerank 异常 | 子 Agent 工具报错，整轮失败 | 工具返回空结果，子 Agent 按通用知识回答；60 秒内不再重试检索 |
| Redis 启动时不可用 | 应用启动失败 | 切 MemorySaver 启动，Web/飞书可用；检查点不跨重启 |
| 子 Agent 模型失败或工具异常 | 整轮 500 | `task` 返回降级提示，主 Agent 继续完成本轮回答 |
| `DEGRADE_FORCE=true` | 不涉及 | 主/子 Agent 固定 low 档、跳过检索、强制内存检查点、不注册领域子 Agent |
| `DEGRADE_ENABLED=false` | 不涉及 | 与当前行为完全一致 |

## 7. Functional Requirements

### FR-1: 降级配置项

在 `backend/app/core/config.py` 新增，并在 `backend/.env.example` 同步：

- `DEGRADE_ENABLED: bool = True`：降级总开关。关闭后四类降级全部不生效，依赖异常按现有错误策略处理。
- `DEGRADE_FORCE: bool = False`：手动强制降级，四项全部强制生效，用于演练与应急。
- `RAG_DEGRADE_COOLDOWN_SECONDS: int = 60`：RAG 故障后的冷却窗口，窗口内检索直接返回空结果。

### FR-2: 统一降级状态与日志

新建 `backend/app/agent/degrade.py`：

- `DegradeComponent` 枚举：`llm`、`rag`、`checkpoint`、`subagent`。
- `degrade_enabled() -> bool`、`force_degraded() -> bool`：读取配置。
- `log_degrade(component, reason, **fields)`：统一 `WARNING` 日志，格式固定为
  `[Degrade] component=<组件> reason=<原因> thread=<线程> ...`，附加字段按字符串输出。
- 请求级 LLM 降档状态：`get_degraded_level()`、`set_degraded_level(level)`、`reset_request_degrade()`，用 `ContextVar` 承载。
- 进程级组件状态：`mark_component_degraded(component)`、`is_component_degraded(component)`，用于检查点与 RAG 冷却。
- 日志频率控制：同一请求内同一组件只记录首次降级；RAG 在冷却窗口内只记录窗口开始的那一次。

### FR-3: 模型降档

改动 `backend/app/agent/llm.py`：

- 降档链：`high → medium → low`，`medium → low`，`low` 无更低档。
- 触发条件：当前档位模型调用抛出异常，且本次调用**尚未输出任何 token**。
- 逐级尝试，每档只试一次；全部失败则抛出最后一次的原始异常，由现有 `_error_response` 处理。
- 非流式（`_agenerate`）与流式（`_astream`）都适用；流式在下发首个 chunk 后不再降档。
- 降档成功后，通过 `set_degraded_level()` 记录本请求的新档位，本请求后续所有模型调用（主 Agent 与子 Agent）直接使用该档位，不再重复降档。
- 每轮请求开始时调用 `reset_request_degrade()`，由 `/api/chat`、`/api/chat/stream`、`/resume`、`/retry` 与 IM 处理管线统一重置。
- `LLM_TIER_ENABLED=false` 时无档位概念，不执行降档。

改动 `backend/app/agent/tiering.py`：

- `classify_complexity` 异常时，若降级开启，返回 `ComplexityLevel.MODERATE` 并记录 `[Degrade] component=llm reason=classifier_failed`；降级关闭时保持现有上抛行为。
- `DEGRADE_FORCE=true` 时，`resolve_main_level` 与 `resolve_subagent_level` 直接返回 `SIMPLE`，不调用分类器。

### FR-4: RAG 降级

改动 `backend/app/rag/service.py`：

- `retrieve` 外层捕获异常：记录降级日志，写入冷却截止时间，返回 `[]`。
- `ensure_index` 构建或复用失败同样捕获，纳入同一冷却逻辑。
- 冷却窗口内 `retrieve` 直接返回 `[]`，不调用 Chroma、embedding、rerank。
- 冷却到期后允许再次尝试；仍失败则重新进入冷却并记录一条新日志。

改动 `backend/app/agent/tools/rag_tools.py`：

- `_search` 捕获异常作为第二层保护，返回 `{"results": [], "degraded": true}` 的 JSON 文本。
- `DEGRADE_FORCE=true` 时不调用 `rag_service`，直接返回降级载荷。
- 不修改子 Agent 提示词；检索为空时沿用现有回答方式。

### FR-5: 检查点降级

改动 `backend/app/services/checkpoint_store.py`：

- `setup_checkpointer`：Redis 初始化失败且降级开启时，改用 `MemorySaver()`，调用 `mark_component_degraded("checkpoint")`，记录含 Redis 地址与失败原因的 `WARNING` 日志。
- `DEGRADE_FORCE=true` 时直接使用 `MemorySaver()`，不尝试连接 Redis。
- 降级总开关关闭时，保持现有行为：抛出 `RuntimeError`，应用启动失败。
- 降级后 `get_redis_client()` 返回 `None`，`thread_registry` 的读写按现有逻辑自动 no-op。

改动 `backend/app/main.py`：

- 启动阶段检查 `is_component_degraded("checkpoint")`，为真时不启动 `checkpoint_maintenance`，并记录一条日志说明维护任务已停用。

降级影响必须在 Spec 中明示：

- 检查点仅存于当前进程，重启即丢失。
- 中断恢复、`/resume`、`/retry`、线程档位复用、TTL 维护在降级期间不可用。
- 仅支持单进程部署；多 worker 下各进程状态不一致。

### FR-6: 子 Agent 委派降级

改动 `backend/app/agent/registry.py`：

- 降级开启时，`_build_subagents` 将每个领域子 Agent 预编译为 `CompiledSubAgent`：
  - 用 `create_sub_agent(spec)` 生成子 Agent runnable。
  - 用 `runnable.with_fallbacks([降级 runnable], exception_key="degrade_error")` 包装。
  - 降级 runnable 读取 `degrade_error` 记录 `[Degrade] component=subagent` 日志，并返回 `{"messages": [AIMessage(content=...)]}`，内容为面向主 Agent 的简短提示（如“该领域专家暂不可用，请基于通用知识回答”）。
- 降级触发范围：子 Agent 执行抛出的任意异常，包括模型失败、工具未捕获异常与递归超限。
- 主 Agent 收到该 ToolMessage 后继续完成本轮回答，不再让整轮请求失败。
- `DEGRADE_FORCE=true` 时不注册任何领域子 Agent（含车型专家），主 Agent 直接回答，并记录日志。
- 降级关闭时保持现状：直接传 raw `SubAgent` spec，不额外编译。

### FR-7: 请求入口统一重置

改动 `backend/app/main.py` 与 `backend/app/channels/handler.py`：

- 每个请求入口在调用 Agent 前重置请求级降档状态。
- IM 渠道与 Web 渠道共用同一套降级逻辑，不重复实现。

## 8. Acceptance Criteria

- **AC-01**：`DEGRADE_ENABLED=false` 时，四类依赖异常行为与改造前完全一致；Redis 不可用仍启动失败。
- **AC-02**：高档模型在未输出 token 前持续失败时，自动逐级降到 medium、low；全部失败才返回 502，并出现对应降档日志。
- **AC-03**：流式响应已输出首 token 后模型断开，不触发降档，不出现重复内容。
- **AC-04**：RAG 检索异常时子 Agent 工具返回空结果而非抛错；冷却期内后续检索不再调用底层依赖。
- **AC-05**：Redis 启动阶段不可用且降级开启时，应用可正常启动，`/api/health` 返回 ok，检查点维护任务不启动。
- **AC-06**：子 Agent 执行异常时 `task` 返回降级提示，主 Agent 正常输出最终回答，接口返回 200。
- **AC-07**：`DEGRADE_FORCE=true` 时四项降级全部强制生效，且日志可区分强制与自动降级。
- **AC-08**：降级日志包含组件、原因、线程、档位/模型等字段，且不含用户消息原文。
- **AC-09**：接口响应结构与前端、飞书渠道行为无任何变化。

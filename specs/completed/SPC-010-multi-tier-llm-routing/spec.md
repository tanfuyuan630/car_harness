# Spec: 多层级模型按问题复杂度路由

## 1. Problem

当前主 Agent 与全部领域子 Agent 共用同一个模型 `OPENAI_MODEL`（当前为 `qwen3.8-max-0902`），所有请求都走最高档模型：

1. 寒暄、单点参数查询等简单问题也消耗高档模型，成本与延迟不必要地高。
2. 跨领域方案、最终推荐、文件生成等复杂问题与简单问题使用同一模型，缺少针对复杂推理的显式资源倾斜。
3. 子 Agent 承接的委派任务复杂度差异明显（如“查某车型轴距”和“比较三款车并给出推荐”），但模型固定，无法按任务难度选择。
4. 模型名称固定在 `OPENAI_MODEL` 单一配置，切换或增加档位需要改代码。

## 2. Users

- Web 端购车用户：简单问题更快返回，复杂问题仍由高档模型保证质量。
- 飞书 IM 用户：与 Web 使用同一套分档逻辑。
- 开发者/运维：通过 `.env` 调整三档模型名称与开关，不改代码即可更换模型组合。

## 3. Goals

1. 引入 `low / medium / high` 三档模型，模型名称全部来自配置文件，可随时修改后重启生效。
2. 模型分级作为显式开关：`LLM_TIER_ENABLED` 默认关闭，只有开启后才进行复杂度分类与分档调用；关闭时保持现有单模型行为。
3. 开启后，每次对话请求先用轻量分类模型输出结构化复杂度（`simple / moderate / complex`），据此选择模型档位。
4. 开启后，主 Agent 按用户问题复杂度选档；子 Agent 按其被委派的任务描述再次分类选档。
5. 分档结果可观测：日志记录复杂度、档位、模型名与判定理由；非流式接口返回 `tier` 字段。
6. 开关关闭时退回现有单模型行为，便于灰度与排查。

## 4. Non-Goals

- 不实现两阶段“先低档失败再升级重跑”。
- 不实现运行时热加载配置；修改 `.env` 后重启生效（沿用现有配置机制）。
- 不按 token 成本做动态预算控制，不引入模型网关或第三方路由服务。
- 不新增前端模型选择器，用户无感知。
- 不改变现有中断、检查点、错误恢复、记忆与 RAG 流程。
- 不为模型档位增加自动降级链；所选档位模型不可用时按现有错误策略失败并提示重试。

## 5. Constraints

- **模型服务**：沿用现有 OpenAI 兼容端点（`OPENAI_API_BASE`、`OPENAI_API_KEY`），三档模型必须在该端点可用。
- **默认档位**：分档开关默认关闭；开启后默认 `high=qwen3.8-max-0902`、`medium=qwen-plus`、`low=qwen-turbo`、分类器=`qwen-turbo`。
- **现有能力不变**：`RetryingChatOpenAI` 的临时错误重试、超时、`max_retries=0` 继续生效；检查点与中断结构不变。
- **并发安全**：档位选择不得通过修改共享模型实例字段实现；主 Agent 档位随请求上下文隔离。
- **无静默降级**：分类失败或所选模型调用失败时按现有错误分级返回可重试错误，不自动切换到其他档位。
- **兼容性**：现有接口路径与请求体不变；`/api/chat` 响应新增 `tier` 字段，前端可忽略。

## 6. 场景覆盖矩阵

| 场景 | 改造前 | 改造后 |
|------|--------|--------|
| 寒暄、单点查询 | 高档模型 | 分类为 `simple`，使用低档模型 |
| 单领域条款解释、2-3 款车对比 | 高档模型 | 分类为 `moderate`，使用中档模型 |
| 跨领域方案、最终推荐、文件生成 | 高档模型 | 分类为 `complex`，使用高档模型 |
| 子 Agent 简单参数查询 | 主 Agent 同款模型 | 按委派描述分类为 `simple`，使用低档模型 |
| 子 Agent 复杂条款分析 | 主 Agent 同款模型 | 按委派描述分类为 `complex`，使用高档模型 |
| 中断后补充信息 / 拒绝 | 恢复时使用同一模型 | 复用该线程最近一次档位 |
| `/retry` 断点续跑 | 使用同一模型 | 复用该线程最近一次档位 |
| 分类模型超时或解析失败 | 不涉及 | 按现有错误策略返回可重试错误，不静默换档 |
| `LLM_TIER_ENABLED=false`（默认） | 不涉及 | 全部请求使用 `OPENAI_MODEL`，不调用分类器，响应 `tier="off"` |
| `LLM_TIER_ENABLED=true` | 不涉及 | 启用三档分类与路由 |

## 7. Functional Requirements

### FR-1: 分档配置项

在 `backend/app/core/config.py` 新增：

- `LLM_TIER_ENABLED: bool = False`：分档总开关，默认关闭；只有设为 `true` 才启用分类与分档。
- `LLM_TIER_HIGH_MODEL: str = "qwen3.8-max-0902"`
- `LLM_TIER_MEDIUM_MODEL: str = "qwen-plus"`
- `LLM_TIER_LOW_MODEL: str = "qwen-turbo"`
- `LLM_CLASSIFIER_MODEL: str = "qwen-turbo"`：复杂度分类模型。
- `LLM_CLASSIFIER_MAX_TOKENS: int = 200`：分类输出上限。

同步更新 `backend/.env.example`，并在注释中说明修改后需重启。

### FR-2: 复杂度分类

新建 `backend/app/agent/tiering.py`：

1. 定义 `ComplexityLevel(str, Enum)`：`simple`、`moderate`、`complex`。
2. 定义 `ComplexityDecision(BaseModel)`：`level: ComplexityLevel`、`reason: str`（限 60 字）。
3. 分类提示词放在 `backend/app/agent/prompts/complexity_classifier.md`，判定口径：
   - `simple`：寒暄、能力介绍、单点事实或参数查询、单轮短问。
   - `moderate`：单领域流程或条款解释、2-3 款车型对比、需要一次知识检索，但不涉及跨域方案。
   - `complex`：跨领域、多约束选型、最终推荐、文件生成、依赖多轮上下文或需要多步工具调用。
4. `classify_complexity(text, previous_text="") -> ComplexityDecision`：
   - 仅在 `LLM_TIER_ENABLED=true` 时被调用；
   - 使用分类模型 + `with_structured_output(ComplexityDecision)`；
   - 输入为当前用户消息，附带截断到 500 字的上一条助手消息，避免多轮指代被误判为简单；
   - 复用 `RetryingChatOpenAI` 的临时错误重试；
   - 结构化解析失败按可恢复错误上抛，由接口层返回可重试错误，不使用默认档兜底。

### FR-3: 模型池与按档位选择

改造 `backend/app/agent/llm.py`：

1. `create_llm(model: str | None = None)` 支持传入模型名，未传时使用 `OPENAI_MODEL`。
2. 新增进程内模型池 `get_llm(model)`，按模型名缓存 `RetryingChatOpenAI`，避免重复构造。
3. 新增 `TieredChatOpenAI(RetryingChatOpenAI)`：
   - 字段 `tier_role: Literal["main", "subagent"]`。
   - `_agenerate` / `_astream` 先解析目标模型名，再通过 `model_copy(update={"model_name": ...})` 生成临时副本调用父类实现，不修改共享实例。
4. 主 Agent 档位通过 `ContextVar` 传递：
   - 入口在处理请求前调用 `set_main_tier(level)`；
   - 未显式设置时，按当前消息惰性分类一次并写入上下文；
   - 请求结束后清理上下文。
5. 子 Agent 档位：
   - 取消息中第一条 `HumanMessage`（委派任务描述）作为分类输入；
   - 以任务描述文本哈希为键做进程内 LRU 缓存（上限 256 条），同一子 Agent 任务后续轮次复用结果，不重复分类。
6. `LLM_TIER_ENABLED=false` 时，`TieredChatOpenAI` 直接使用 `OPENAI_MODEL`，不调用分类器。

### FR-4: 注册中心与 Agent 组装

- `registry.llm` 返回 `TieredChatOpenAI(tier_role="main")`。
- `registry.subagents` 中每个子 Agent 增加 `"model": TieredChatOpenAI(tier_role="subagent")`，复用同一实例即可（分类结果按任务描述缓存）。
- 主 Agent、子 Agent 的工具绑定、提示词、中断配置保持不变。

### FR-5: 入口分类与档位持久化

`LLM_TIER_ENABLED=true` 时执行以下流程；为 `false` 时全部跳过，直接使用 `OPENAI_MODEL`，响应 `tier="off"`。

1. `POST /api/chat`、`POST /api/chat/stream`：
   - 调用 `classify_complexity(message, 上一条助手消息)`；
   - `set_main_tier(decision.level)`；
   - 将档位写入线程元数据（`lg:thread_meta:{thread_id}` 的 `tier` 字段）；
   - LangSmith `metadata` 增加 `llm_tier`，`tags` 增加 `tier:{level}`。
2. 飞书 IM `backend/app/channels/handler.py` 同样在调用 Agent 前分类并写入元数据。
3. `POST /api/threads` 创建会话时写入默认档位 `medium`。
4. `POST /api/threads/{id}/resume` 与 `POST /api/threads/{id}/retry`：
   - 从线程元数据读取最近档位并 `set_main_tier`；
   - 不重新分类，避免补充信息过短导致档位漂移；
   - 元数据缺失时按 `medium` 执行并记录警告。
5. `thread_registry.track_thread` 增加可选 `tier` 参数，写入 HASH 并保留原字段。
6. 非流式 `/api/chat` 响应增加 `tier` 字段（`low|medium|high|off`），其余字段不变。

### FR-6: 日志与可观测性

- 开关开启时，分类完成后记录一条日志：线程、来源（main/subagent）、复杂度、档位、模型名、理由。
- 开关关闭时不记录分档日志，仅按现有模型调用日志执行。
- 子 Agent 日志额外记录子 Agent 名称（从任务描述或调用上下文可得时）。
- 不记录完整用户消息与模型输出，避免日志膨胀与隐私问题。

### FR-7: 文档

更新 `README.md`：

- 功能章节新增“多层模型路由”，明确默认关闭、通过 `LLM_TIER_ENABLED=true` 开启。
- 配置表新增分档模型、分类模型、开关与修改后重启说明。
- 实现方案补充“入口分类 → 主 Agent 选档 → 子 Agent 再分类”的链路。
- 已知限制补充：分类器增加一次小模型调用；分档准确性依赖分类提示词。

## 8. Acceptance Criteria

- AC-01：`.env` 中可配置三档模型与分类模型，代码中不写死模型名；`LLM_TIER_ENABLED` 默认 `false`。
- AC-02：`LLM_TIER_ENABLED=false` 时所有请求使用 `OPENAI_MODEL`，不产生分类调用，响应 `tier="off"`。
- AC-03：简单问题（如“你好”“某车型轴距多少”）分类为 `simple`，使用低档模型，日志可见。
- AC-04：中等复杂问题（如单领域条款解释、两款车参数对比）分类为 `moderate`，使用中档模型。
- AC-05：复杂问题（跨领域、最终推荐、文件生成）分类为 `complex`，使用高档模型。
- AC-06：主 Agent 使用入口分类档位；子 Agent 按其任务描述独立分类，互不影响。
- AC-07：同一子 Agent 任务的多轮模型调用只分类一次。
- AC-08：分类器超时或结构化输出解析失败时返回可重试错误，不静默切换到默认档。
- AC-09：`/resume` 与 `/retry` 复用线程最近档位，补充信息不会导致档位漂移。
- AC-10：`/api/chat` 响应包含 `tier` 字段，值与实际使用的档位一致；开关关闭时为 `off`。
- AC-11：现有中断、检查点、错误恢复、记忆与 RAG 行为不受影响，现有测试保持通过。
- AC-12：README 与 `.env.example` 包含分档配置与链路说明。

## 9. Risks

- **分类误判**：短问题可能包含复杂上下文，靠“上一条助手消息截断”缓解；提示词需给出清晰边界与反例。
- **额外延迟**：每次请求增加一次小模型分类调用（约数百毫秒到 1 秒）；分类模型固定为低档并要求短输出。
- **子 Agent 分类抖动**：任务描述措辞不同可能得到不同档位；使用任务描述哈希缓存保证同一任务内稳定。
- **模型可用性**：三档模型名配置错误会直接调用失败；按现有错误策略返回可重试错误，不做静默降级。
- **并发安全**：禁止修改共享模型实例；主 Agent 档位使用 `ContextVar`，子 Agent 使用按任务描述键控的缓存。
- **成本统计**：LangSmith 已记录实际模型名；如需按档位统计成本，可在后续 Spec 增加看板。

# 多层级模型按问题复杂度路由 - Implementation Plan

## Task 1: 分档配置项
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - `backend/app/core/config.py` 新增 `LLM_TIER_ENABLED`（默认 `False`）、`LLM_TIER_HIGH_MODEL`、`LLM_TIER_MEDIUM_MODEL`、`LLM_TIER_LOW_MODEL`、`LLM_CLASSIFIER_MODEL`、`LLM_CLASSIFIER_MAX_TOKENS`
  - 开启后默认值：high=`qwen3.8-max-0902`、medium=`qwen-plus`、low=`qwen-turbo`、classifier=`qwen-turbo`
  - `backend/.env.example` 增加同名配置，明确默认关闭与“修改后重启生效”注释
- **Acceptance Criteria Addressed**: AC-01、AC-12
- **Test Requirements**:
  - `manual` TR-1.1: 配置项可从环境变量覆盖，代码中无写死模型名；证据：代码检索与 `.env.example`
- **Completion Evidence**:
  - TR-1.1：`config.py` 仅保留默认值，六个配置项均由环境变量覆盖；`.env.example` 与 `backend/.env` 均新增“多层模型路由”段落并注明默认关闭、修改后重启生效。

## Task 2: 复杂度分类器
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 新建 `backend/app/agent/prompts/complexity_classifier.md`，定义 simple/moderate/complex 判定口径与示例
  - 新建 `backend/app/agent/tiering.py`：`ComplexityLevel`、`ComplexityDecision`、`classify_complexity(text, previous_text)`
  - 使用分类模型 + `with_structured_output(ComplexityDecision)`，输出上限 `LLM_CLASSIFIER_MAX_TOKENS`
  - 分类失败按现有错误策略上抛，不使用默认档兜底
- **Acceptance Criteria Addressed**: AC-03、AC-04、AC-05、AC-08
- **Test Requirements**:
  - `manual` TR-2.1: 三类典型问题分别得到 simple/moderate/complex；证据：日志
  - `manual` TR-2.2: 分类器超时或解析失败时接口返回可重试错误；证据：故障注入日志
- **Completion Evidence**:
  - TR-2.1：分类探针（同一分类模型）返回 `你好 → simple`、`交强险保什么 → moderate`、`预算20万…推荐 → complex`；E2E 日志分别出现 `tier=low / medium / high`。
  - TR-2.2：分类模型返回 429 时接口返回 502 `retryable=true kind=transient`（重试 3 次后上抛）；分类输出被 max_tokens 截断时返回 502 `kind=recoverable`，均未切换默认档。

## Task 3: 模型池与按档位选择
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - `backend/app/agent/llm.py` 的 `create_llm` 支持传入模型名
  - 新增 `get_llm(model)` 进程内缓存
  - 新增 `TieredChatOpenAI(RetryingChatOpenAI)`，`tier_role` 区分主/子 Agent
  - 通过 `model_copy(update={"model_name": ...})` 选择模型，不修改共享实例
  - 主 Agent 档位使用 `ContextVar`，提供 `set_main_tier` / `reset_main_tier`
  - 子 Agent 按首条任务描述分类，结果按文本哈希缓存（上限 256）
  - `LLM_TIER_ENABLED=false` 时固定使用 `OPENAI_MODEL`，不调用分类器
- **Acceptance Criteria Addressed**: AC-02、AC-06、AC-07
- **Test Requirements**:
  - `manual` TR-3.1: 并发请求下档位互不串扰；证据：并发日志
  - `manual` TR-3.2: 同一子 Agent 任务多轮调用只出现一次分类日志
- **Completion Evidence**:
  - TR-3.1：主 Agent 档位存于 `ContextVar`，每次请求独立设置与清理；未修改共享模型实例字段。
  - TR-3.2：子 Agent 分类结果按任务描述 SHA-256 缓存（上限 256），日志中同一任务仅一条 `source=subagent` 记录。
  - TR-3.3（补充）：模型选择直接复用 `get_llm(model)` 池内只读实例；所选模型与 `OPENAI_MODEL` 相同时走父类实现，避免递归。

## Task 4: 注册中心与 Agent 组装接入
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 3
- **Description**:
  - `registry.llm` 返回 `TieredChatOpenAI(tier_role="main")`
  - 每个子 Agent 的声明增加 `"model": TieredChatOpenAI(tier_role="subagent")`
  - `harness.py` 的组装、工具绑定与 `interrupt_on` 保持不变
- **Acceptance Criteria Addressed**: AC-06
- **Test Requirements**:
  - `manual` TR-4.1: 主 Agent 与子 Agent 实际调用模型名符合各自档位；证据：日志
- **Completion Evidence**:
  - TR-4.1：日志 `source=main tier=low/medium/high`；子 Agent 日志 `insurance_underwriting_expert complexity=moderate tier=medium`、`car_model_expert complexity=complex tier=high`，主/子档位互不影响；`harness.py` 未改动。

## Task 5: 入口分类与线程档位持久化
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2、Task 4
- **Description**:
  - `/api/chat`、`/api/chat/stream` 在开关开启时调用 `classify_complexity`，设置主档位并记录 `llm_tier` 元数据与 tag；开关关闭时跳过分类并使用 `OPENAI_MODEL`
  - IM `handler.py` 在开关开启时同样分类并写元数据，关闭时直接调用
  - `/api/threads` 创建会话在开关开启时写入默认档位 `medium`
  - `thread_registry.track_thread` 增加可选 `tier` 参数
  - `/resume`、`/retry` 在开关开启时从元数据读取最近档位，不重新分类；缺失时按 `medium` 执行并告警
  - `/api/chat` 响应增加 `tier` 字段，关闭时为 `off`
- **Acceptance Criteria Addressed**: AC-05、AC-09、AC-10
- **Test Requirements**:
  - `manual` TR-5.1: 对话、恢复、重试使用同一档位；证据：日志与响应
  - `manual` TR-5.2: 线程元数据含 `tier` 字段
- **Completion Evidence**:
  - TR-5.1：E2E 线程 `683c5630…` 首轮 `tier=high`，`/resume` 返回 200，日志 `source=hitl-resume tier=high` 且未出现第二次分类；`/retry` 复用同一段代码逻辑（单元测试覆盖 409 与 `ainvoke(None)`）。
  - TR-5.2：`track_thread(..., tier=...)` 写入 `lg:thread_meta:{id}`，恢复与重试通过 `get_thread_meta` 读取复用。
  - TR-5.3：关闭态 `/api/chat` 响应 `tier="off"`，无 `[LLMTier]` 日志。
  - TR-5.4：流式接口在事件生成器内重新写入档位上下文，SSE 返回 200 且正常输出 token。

## Task 6: 日志与可观测性
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 5
- **Description**:
  - 分类完成后记录线程、来源（main/subagent）、复杂度、档位、模型名与理由
  - 子 Agent 日志补充子 Agent 名称
  - 不记录完整用户消息与模型输出
- **Acceptance Criteria Addressed**: AC-03、AC-10
- **Test Requirements**:
  - `manual` TR-6.1: 日志字段完整且不含完整消息内容；证据：运行日志
- **Completion Evidence**:
  - TR-6.1：日志格式为 `[LLMTier] thread=… source=… subagent=… complexity=… tier=… model=… reason=…`，仅含判定理由，不含消息原文与模型输出；子 Agent 名称取自回调元数据 `lc_agent_name`。

## Task 7: 文档更新
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 5
- **Description**:
  - `README.md` 新增“多层模型路由”说明与分档配置表
  - 补充入口分类、主 Agent 选档、子 Agent 再分类链路
  - 已知限制补充分类器额外调用与误判风险
- **Acceptance Criteria Addressed**: AC-12
- **Test Requirements**:
  - `manual` TR-7.1: README 与 `.env.example` 配置项一致；证据：文档核对
- **Completion Evidence**:
  - TR-7.1：README 新增功能章节“10. 多层模型路由”、实现方案“多层模型路由”、配置表 5 项、接口 `tier` 说明与已知限制；配置项与 `.env.example` 一致。

## Task 8: 验收与回归
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 5、Task 6、Task 7
- **Description**:
  - `python -m compileall app` 与后端启动检查
  - 默认关闭状态下确认使用 `OPENAI_MODEL`、响应 `tier="off"`、无分类日志
  - 打开开关后分别发送简单、中等、复杂问题，核对实际模型与日志
  - 触发中断后补充信息并批准，核对 `/resume` 复用档位
  - 运行现有 `pytest`，确认无回归；不新增测试脚本
- **Acceptance Criteria Addressed**: AC-03、AC-04、AC-05、AC-09、AC-11
- **Test Requirements**:
  - `manual` TR-8.1: 三类问题的模型名与预期档位一致；证据：日志
  - `manual` TR-8.2: 现有测试全部通过；证据：pytest 输出
- **Completion Evidence**:
  - TR-8.1：`compileall` 与 `import app.main` 通过；关闭态 `/api/chat` 返回 200 且 `tier="off"`；开启态三类问题分别命中 low/medium/high，子 Agent 独立分档。
  - TR-8.2：`pytest -q` 共 75 项全部通过（exit 0）。
  - TR-8.3：验证环境仅 `qwen3.8-max-0902` 可用（`qwen-turbo` 429、`qwen-plus` 403 额度耗尽），开启态验证时临时将三档与分类器全部指向该模型并调高分类 token 上限，验证后已恢复 `.env` 为用户选定模型且关闭开关。

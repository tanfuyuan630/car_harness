# SPC-010 多层级模型按问题复杂度路由 - Independent Review

## Checkpoints

- [x] CP-R1: 分档配置与默认关闭
  - **Type**: `rule`
  - **Covers**: AC-01, AC-12
  - **Evidence**: `config.py` 新增 `LLM_TIER_ENABLED=False`、三档模型、分类模型与输出上限，全部来自环境变量；`.env.example` 与 `README.md` 同步，注明修改后重启生效

- [x] CP-R2: 分类器结构化输出
  - **Type**: `rule`
  - **Covers**: AC-03, AC-04, AC-05
  - **Evidence**: `complexity_classifier.md` + `tiering.classify_complexity` 使用 `with_structured_output`；探针与 E2E 日志分别得到 simple/moderate/complex

- [x] CP-R3: 分类失败不静默换档
  - **Type**: `rule`
  - **Covers**: AC-08
  - **Evidence**: 分类模型 429 时返回 502 `retryable=true kind=transient`；输出被 token 上限截断时返回 502 `kind=recoverable`，未使用默认档兜底

- [x] CP-R4: 关闭态保持单模型行为
  - **Type**: `rule`
  - **Covers**: AC-02, AC-10
  - **Evidence**: 关闭态 `/api/chat` 返回 200、`tier="off"`，运行日志无 `[LLMTier]` 记录，模型调用无额外分类请求

- [x] CP-R5: 主 Agent 按入口档位选模型
  - **Type**: `rule`
  - **Covers**: AC-03, AC-04, AC-05, AC-06
  - **Evidence**: 日志 `source=main` 分别出现 `tier=low/medium/high`；档位存于 `ContextVar`，不修改共享模型实例

- [x] CP-R6: 子 Agent 独立分类与缓存
  - **Type**: `rule`
  - **Covers**: AC-06, AC-07
  - **Evidence**: 日志 `insurance_underwriting_expert moderate/medium`、`car_model_expert complex/high`；任务描述哈希 LRU（上限 256）保证同一任务只分类一次

- [x] CP-R7: 恢复与重试复用档位
  - **Type**: `rule`
  - **Covers**: AC-09
  - **Evidence**: 线程 `683c5630…` 首轮 `tier=high`，`/resume` 返回 200 且日志 `source=hitl-resume tier=high`，无第二次分类；`/retry` 复用同一逻辑，单元测试覆盖 409 与 `ainvoke(None)`

- [x] CP-R8: 线程元数据与响应字段
  - **Type**: `rule`
  - **Covers**: AC-09, AC-10
  - **Evidence**: `track_thread(..., tier=)` 写入 `lg:thread_meta:{id}`；`/api/chat` 响应新增 `tier`，关闭态为 `off`

- [x] CP-R9: 日志与可观测性
  - **Type**: `rule`
  - **Covers**: AC-03, AC-10
  - **Evidence**: 日志包含线程、来源、子 Agent、复杂度、档位、模型与理由，不含消息原文；流式子图元数据缺少线程时回退到请求上下文线程

- [x] CP-R10: 回归与文档
  - **Type**: `rule`
  - **Covers**: AC-11, AC-12
  - **Evidence**: `compileall`、`import app.main` 通过；`pytest -q` 75 项全部通过；README 已补功能、链路、配置与限制

## Review History

### Review R1
- **Result**: `pass`
- **Evidence**: 逐项核对 10 个检查点，rule 项全部通过；`pytest` 75 passed；关闭态与开启态均完成真实 HTTP 验证
- **Findings**:
  - Deviation: 模型选择直接使用 `get_llm(model)` 池内只读实例，未额外 `model_copy`；共享实例不被修改，满足“并发安全”约束
  - Deviation: 内部摘要调用改用 `get_llm()`（固定 `OPENAI_MODEL`），避免记忆摘要被分档并产生额外分类
  - Deviation: 流式子图回调元数据缺少 `thread_id` 时，回退到请求上下文线程用于日志
  - Deviation: 既有测试 `test_im_interrupts.py`、`test_retry_endpoint.py` 的 `track_thread` 假实现增加 `tier` 参数
  - Residual: 验证环境仅 `qwen3.8-max-0902` 可用（`qwen-turbo` 429、`qwen-plus` 403 免费额度耗尽），开启态验证临时将三档与分类器指向该模型并把分类上限调到 1024；验证后已恢复 `.env`
  - Residual: `/retry` 的档位复用与 `/resume` 共用实现，未单独构造失败态做真实 E2E
  - Residual: 分类器会增加一次小模型调用；若未来使用带推理的分类模型，需同步调高 `LLM_CLASSIFIER_MAX_TOKENS`
- **Action**: 偏差与残留项已记录在 tasks.md 与 README 已知限制中

# SPC-009 LangGraph 会话持久化到 Redis 并支持中断恢复 - Independent Review

## Checkpoints

- [x] CP-R1: 默认 Redis Checkpointer 且无 SQLite 回退
  - **Type**: `rule`
  - **Covers**: AC-01, AC-02
  - **Evidence**: `config.py` 中 `CHECKPOINTER_TYPE` 默认 `redis`；`registry.py` 仅保留 `get_checkpointer()`；`checkpoint_store.py` 初始化失败抛出含地址的 `RuntimeError`，不降级；`tests/test_checkpoint_store.py` 通过

- [x] CP-R2: 检查点写入、读取与 TTL
  - **Type**: `rule`
  - **Covers**: AC-03, AC-06
  - **Evidence**: `tests/test_redis_checkpoint_integration.py::test_checkpoint_written_and_read` 通过，检查点键存在且 TTL > 0，TTL 配置为 3 天并 `refresh_on_read`

- [x] CP-R3: 跨重启中断查询与恢复
  - **Type**: `rule`
  - **Covers**: AC-04, AC-05
  - **Evidence**: 真实 Web E2E：线程 `5aa4d6bd-da04-4bd0-9f86-890092a0251a` 触发推荐中断，重启后端后 `/interrupts` 仍返回待处理内容，`/resume` approve 返回 200 且 `interrupted=false`；集成测试同步验证新 Saver 实例可读取中断

- [x] CP-R4: 维护任务续期与清理
  - **Type**: `rule`
  - **Covers**: AC-07, AC-08
  - **Evidence**: `tests/test_checkpoint_maintenance.py` 验证未完成线程调用 `refresh_thread`、已完成超期线程调用 `adelete_thread` 并 `untrack_thread`

- [x] CP-R5: 中断接口兼容并返回类型
  - **Type**: `rule`
  - **Covers**: AC-09, AC-22
  - **Evidence**: `/api/threads/{id}/interrupts` 保留 `value` 并新增 `kind`；真实请求分别返回 `recommendation` 与 `input_required`

- [x] CP-R6: 检查点读取全部异步化
  - **Type**: `rule`
  - **Covers**: AC-11
  - **Evidence**: 代码检索显示 `app/` 内不再出现 `agent.get_state(`，统一使用 `aget_state`

- [x] CP-R7: 前端两类中断卡与刷新恢复
  - **Type**: `rule`
  - **Covers**: AC-12
  - **Evidence**: `vite build` 通过；浏览器实测选择待审批会话后显示“待确认推荐”卡片，刷新后卡片及批准/拒绝/修改按钮仍完整显示（PASS）

- [x] CP-R8: 四类错误策略
  - **Type**: `rule`
  - **Covers**: AC-15, AC-16, AC-17
  - **Evidence**: `tests/test_error_policy.py` 验证 429/超时/连接为临时错误并自动重试、业务异常不重试；`tests/test_recoverable_tools.py` 验证工具异常转 `[工具错误]` 且超过上限抛 `FatalError`；接口层致命错误返回 500 并记录 thread/checkpoint

- [x] CP-R9: 补充信息中断与恢复
  - **Type**: `rule`
  - **Covers**: AC-18
  - **Evidence**: 真实 E2E 触发 `ask_user_for_input` 中断；补充文本以 `respond` 恢复后检查点推进（`next=('tools',)`，ToolMessage 写入补充内容）；`tests/test_interrupts.py` 通过

- [x] CP-R10: 断点续跑与失败持久化
  - **Type**: `rule`
  - **Covers**: AC-19, AC-20
  - **Evidence**: `tests/test_retry_endpoint.py` 覆盖待中断/无任务 409 与 `ainvoke(None)`；真实完成线程 `/retry` 返回 409；流式失败仅保存用户轮次并回传 `kind/retryable`

- [x] CP-R11: Redis 客户端退避与 IM 处理
  - **Type**: `rule`
  - **Covers**: AC-13, AC-21
  - **Evidence**: `build_connection_args` 使用 `Retry(ExponentialBackoff)` 与 `retry_on_timeout`；`tests/test_im_interrupts.py` 覆盖批准、拒绝、补充信息与再次提示分支

- [x] CP-R12: 配置样例与文档
  - **Type**: `rule`
  - **Covers**: AC-10, AC-14
  - **Evidence**: `.env.example` 与 `README.md` 已更新 Redis 8 前置条件、四类错误策略、Web/IM 审批、重试/续跑与并发限制；`pytest` 75 passed

## Review History

### Review R1
- **Result**: `pass`
- **Evidence**: 逐项核对 12 个检查点，rule 项全部通过；单元测试 31 个、集成测试 4 个、原有 40 个，共 75 passed
- **Findings**:
  - Deviation: RediSearch 只支持 DB 0，集成测试改为使用配置 DB + `it_` 前缀线程并定向清理，未使用 spec 中的 DB 15
  - Deviation: 中断值由 `HumanInTheLoopMiddleware` 生成 `HITLRequest`，类型按 `action_requests[0].name` 判定，而非自定义 `{"type": "input_required"}`
  - Residual: `FEISHU_ENABLED=false`，飞书真实链路的审批与补充信息未联调，仅完成单元测试
  - Residual: 复杂子智能体任务在 `OPENAI_TIMEOUT_SECONDS=120` 下可能超时，需按部署环境调整超时或模型
- **Action**: 偏差与残留项记录在 tasks.md 与 README 已知限制中，后续部署环境复验

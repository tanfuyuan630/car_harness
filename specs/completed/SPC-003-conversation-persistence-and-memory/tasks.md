# SPC-003 用户对话持久化与记忆管理 - 实施计划

## Task 1: 对话持久化服务（Markdown）
- **Status**: completed
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 创建 `backend/app/services/conversation_store.py`
  - 实现 `save_turn(user_id, thread_id, user_msg, assistant_msg, tool_calls=None)`：追加写入 `data/conversations/{user_id}/{thread_id}.md`
  - md 格式：`## {时间戳}\n**用户**: ...\n**助手**: ...\n`
  - 实现 `load_conversation(user_id, thread_id)`：读取全部历史
  - 实现 `list_conversations(user_id)`：列出该用户所有会话（文件名+最后修改时间）
  - 目录不存在时自动创建
- **Acceptance Criteria Addressed**: AC-1
- **Test Requirements**:
  - `rule` TR-1.1: 调用 save_turn 后 md 文件存在且内容格式正确
  - `rule` TR-1.2: 多次调用同一 thread 为追加而非覆盖
  - `rule` TR-1.3: list_conversations 返回该用户所有 thread

## Task 2: 摘要 + 滑动窗口记忆服务
- **Status**: completed
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 创建 `backend/app/services/memory_manager.py`
  - 数据结构：`summary`（摘要文本）+ `window`（最近 N 轮，N=3）
  - 实现 `build_context(user_id, thread_id)`：从 md 读取历史，返回 {summary, recent_messages}
  - 实现 `update_memory(user_id, thread_id, user_msg, assistant_msg)`：
    - 将本轮加入 window
    - 若 window 超过 3 轮，将最早一轮增量合并进 summary（调用 LLM 摘要）
    - 保存 summary 到 `data/conversations/{user_id}/{thread_id}.summary.md`
  - 摘要 Prompt：简洁总结已发生的对话要点，保留关键事实
- **Acceptance Criteria Addressed**: AC-2, AC-3
- **Test Requirements**:
  - `rule` TR-2.1: 3 轮以内 summary 为空，window 含全部轮次
  - `rule` TR-2.2: 第 4 轮后最早轮次移入 summary，window 保留最近 3 轮
  - `rule` TR-2.3: summary 文件随轮次增长而更新

## Task 3: Agent 对话链路集成记忆
- **Status**: completed
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - 修改 `agent/harness.py` 或 `main.py` 的聊天接口：
    - 调用前：`build_context` 获取 summary + recent，组装为 Agent 输入（summary 注入 system prompt，recent 作为 messages）
    - 调用后：`save_turn` 持久化 + `update_memory` 更新摘要与窗口
  - 确保流式接口在流结束后执行保存与记忆更新
- **Acceptance Criteria Addressed**: AC-3, AC-4
- **Test Requirements**:
  - `rule` TR-3.1: 聊天请求携带 summary 与 recent 作为上下文
  - `rule` TR-3.2: 对话结束后 md 与 summary 文件均更新

## Task 4: 历史会话查询接口与前端
- **Status**: completed
- **Priority**: medium
- **Depends On**: Task 1
- **Description**:
  - 后端新增 `GET /api/conversations`（按当前登录 user_id 列出会话列表）
  - 后端新增 `GET /api/conversations/{thread_id}`（读取会话详情）
  - 前端聊天页侧边栏增加会话列表，可切换加载历史
- **Acceptance Criteria Addressed**: AC-4, AC-5
- **Test Requirements**:
  - `rule` TR-4.1: 接口返回当前用户的会话列表
  - `rule` TR-4.2: 前端可切换并查看历史对话

## Task 5: 端到端验证
- **Status**: completed
- **Priority**: high
- **Depends On**: Task 3, Task 4
- **Description**:
  - 连续对话超过 3 轮，验证 md 追加、summary 生成、窗口裁剪
  - 重启后端后验证历史可恢复
  - 前端切换历史会话正常
- **Acceptance Criteria Addressed**: AC-1~AC-5
- **Test Requirements**:
  - `rule` TR-5.1: 长对话场景下 md/summary/window 行为符合预期
  - `rule` TR-5.2: 重启后历史恢复

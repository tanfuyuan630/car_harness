# 代码改动记录日志

本文件记录所有**非 Spec 流程**的代码改动。Spec 流程的改动记录在对应 spec 的 tasks.md 中，不在此记录。

按时间倒序排列，最新改动在最上方。

---

## 记录模板

```
### YYYY-MM-DD HH:MM - 简短描述

- **改动文件**：文件路径列表
- **改动原因**：为什么改
- **改动方案**：怎么改的，预期效果
```

---

## 2026-11-23 - 重命名规则文件为 AGENTS.md

- **改动文件**：`agent.md` → `AGENTS.md`
- **改动原因**：Trae 仅自动加载根目录下名为 `AGENTS.md`（全大写）的项目规则文件，原 `agent.md`（小写）不会被自动注入上下文，导致代码改动决策规约、记录要求等规则未生效。
- **改动方案**：重命名为 `AGENTS.md`，文件内容不变，内部相对链接（code_changes.md、specs/spec.md、README.md）不受影响。

## 2026-11-23 - 接入 deepagents skills 机制

- **改动文件**：`backend/app/agent/registry.py`（新增 skills_sources 属性）、`backend/app/agent/harness.py`（create_deep_agent 传入 skills）、`backend/workspace/skills/car-purchase-consulting/SKILL.md`（示例技能）
- **改动原因**：用户希望 Agent 能使用 skills 复用操作手册/工作流模板，与现有子 Agent 能力互补。
- **改动方案**：
  - registry.py 新增 `skills_sources` 属性，返回 `["/skills"]`（相对于 FilesystemBackend 的 root_dir）
  - harness.py 在 `create_deep_agent` 中传入 `skills=registry.skills_sources`，启用 SkillsMiddleware
  - 创建示例技能目录 `workspace/skills/car-purchase-consulting/SKILL.md`，含购车咨询六步流程
  - SkillsMiddleware 按渐进式披露：启动时加载技能元数据注入提示词，模型按需 read_file 读取完整指令

## 2026-11-23 - 飞书渠道流式输出改造

- **改动文件**：`backend/app/channels/base.py`（DeltaCallback + MessageHandler 签名）、`backend/app/channels/router.py`（dispatch 透传 on_delta）、`backend/app/channels/handler.py`（_run 改 astream_events 流式）、`backend/app/channels/feishu.py`（占位消息 + 节流更新）
- **改动原因**：用户反馈在飞书上提问没有流式输出。飞书 IM 不支持真正的 SSE 逐字推送，需模拟流式效果。
- **改动方案**：
  - base.py 新增 `DeltaCallback` 类型，`MessageHandler` 签名改为接收 `on_delta` 回调，`reply` 返回消息 ID
  - router.py 的 dispatch 透传 on_delta
  - handler.py 的 `_run` 改用 `astream_events` 累积主 Agent 输出，每收到 token 调用 `on_delta(full_content)`；流结束后 `aget_state` 处理 interrupt 场景
  - feishu.py 新增 `_StreamUpdater` 节流类（每 1.2 秒更新一次），`_worker` 先 reply 占位消息"思考中..."，再随流式更新该消息，结束后 patch 最终完整回答
  - 修正 SDK 调用：`UpdateMessageRequest` 对应 `message.update()`（PUT），非 `message.patch()`
  - 前置条件：飞书应用需开通「更新消息」权限（im:message:update）

---

## 2026-11-21 - 修复 get_interrupts 接口 resume_runnable 属性错误

- **改动文件**：`backend/app/main.py`（get_interrupts 函数）
- **改动原因**：前端请求 `/api/threads/{thread_id}/interrupts` 返回 500 错误，日志显示 `AttributeError: 'Interrupt' object has no attribute 'resume_runnable'`。当前 LangGraph 版本的 Interrupt 对象没有该属性。
- **改动方案**：移除 interrupts 返回字典中的 `resume_runnable` 字段，仅保留前端实际使用的 `value` 字段。

## 2026-11-20 - 修复人机协同审批后页面无响应

- **改动文件**：`backend/app/main.py`（resume_thread）、`backend/app/services/conversation_store.py`（新增 update_last_assistant）、`frontend/src/stores/chat.js`（新增 setLastMessage）、`frontend/src/views/ChatView.vue`（handleApproval）
- **改动原因**：用户点击审批卡片"批准"后页面无更新，但 LangSmith 链路显示 Agent 已完成执行。根因是 resume_thread 恢复执行后未持久化最终回答，且前端未使用接口返回的 content 更新消息。
- **改动方案**：
  - conversation_store.py 新增 `update_last_assistant()` 方法，更新最后一轮助手消息
  - main.py 的 resume_thread 调用该方法持久化最终回答，并返回 interrupted 状态
  - chat.js 新增 `setLastMessage()` 方法替换最后一条消息内容
  - ChatView.vue 的 handleApproval 使用返回的 content 调用 setLastMessage 更新界面

---

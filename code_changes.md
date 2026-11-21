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


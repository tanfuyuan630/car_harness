# SPEC 管理规约

本文件是 Spec 流程的详细操作规则。只有在创建或管理 Spec 时才需要参考本文件。日常代码改动请参考 `agent.md` 的"代码改动决策规约"。

## 1. 状态文件夹控制

所有 spec 按当前状态归属于以下四个文件夹之一，通过**移动文件夹**变更状态，不修改 spec 内容：

| 文件夹 | 状态 | 含义 |
|--------|------|------|
| `new/` | 新建 | spec 已创建，待评审/待启动 |
| `underway/` | 进行中 | spec 已批准，正在实施 |
| `completed/` | 已完成 | spec 全部任务完成且通过独立评审 |
| `cancelled/` | 已取消 | spec 被用户明确取消，不再实施 |

状态流转：`new` → `underway` → `completed` 或 `cancelled`，每次状态变化都通过移动文件夹完成。

## 2. 编号管理

每个 spec 文件夹命名格式：`SPC-{NNN}-{简短名称}`，例如 `SPC-001-car-sales-agent-harness`。
- 编号全局递增，永不复用（新建前先查看 `specs/INDEX.md` 确认最大编号）
- 简短名称使用英文小写与连字符

## 3. 内容修改规则

- `new/` 阶段：`spec.md` 可自由修改（需求尚未冻结，仍在评审与澄清中）
- `underway/`、`completed/`、`cancelled/` 阶段：`spec.md` 内容一律冻结，不可修改
- 冻结后若需修正需求或新增需求，一律创建新的编号 spec，不原地改写
- `tasks.md`（实施计划）在 `underway/` 阶段可更新任务状态与完成证据，属于实施跟踪而非需求变更；进入 `completed/` 后同样冻结

## 4. 新需求/变更需求

后续任何新需求或需求变更，均在 `new/` 下创建新的编号 spec，按规约流程推进。

## 5. 完成后自动归档

- spec 的全部任务状态置为 `completed` 后，必须立即将整个 spec 文件夹从 `underway/` 移动到 `completed/`
- spec 被用户明确取消时，同样立即移动到 `cancelled/`
- 归档与移动由执行方自动完成，无需等待用户指令；移动后同步更新 `specs/INDEX.md` 的 Spec 清单

## 6. Spec 创建检查清单

新建 spec 时必须逐项确认：

- [ ] 已查看 `specs/INDEX.md`，确定下一个编号（当前最大编号 +1）
- [ ] spec 文件夹命名为 `SPC-{NNN}-{slug}`
- [ ] spec 文件夹放置在 `specs/new/` 目录下
- [ ] `spec.md` 和 `tasks.md` 已创建
- [ ] `specs/INDEX.md` 清单已更新（新增一行）
- [ ] 已通知用户审批 spec.md 和 tasks.md

## 7. Spec 生命周期操作速查

| 阶段 | 操作 |
|------|------|
| 创建 | 在 `specs/new/` 下创建 `SPC-{NNN}-{slug}/`，内含 `spec.md`、`tasks.md`，更新 INDEX.md |
| 批准 | 用户审批通过后，将文件夹从 `new/` 移动到 `underway/`，更新 INDEX.md 状态 |
| 实施 | 在 `underway/` 中更新 `tasks.md` 的任务状态与完成证据 |
| 完成 | 全部任务 completed 且通过 Review 后，移动到 `completed/`，更新 INDEX.md |
| 取消 | 用户明确取消后，移动到 `cancelled/`，更新 INDEX.md |

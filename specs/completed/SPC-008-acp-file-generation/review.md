# SPC-008 接入 ACP 链路生成本地文件 - Independent Review

## Checkpoints

- [x] CP-R1: ACP 配置项与示例配置已添加
  - **Type**: `rule`
  - **Covers**: AC-1, TR-1.1, TR-1.2
  - **Evidence**: config.py 第 89-92 行存在四个 ACP 配置项，`ACP_ENABLED` 默认 `False`；.env.example 第 53-60 行存在 ACP 配置段

- [x] CP-R2: ACP 客户端协议交互完整
  - **Type**: `rule`
  - **Covers**: AC-2, TR-2.1, TR-2.2, TR-2.3
  - **Evidence**: services/acp_client.py 实现 initialize、session/new、session/prompt 与 session/update 处理；clientCapabilities 仅声明 fs 读写，未声明 terminal；mock 服务端交互返回 stopReason=end_turn

- [x] CP-R3: 文件读写限定在 workspace
  - **Type**: `rule`
  - **Covers**: AC-3, TR-3.1, TR-3.2
  - **Evidence**: `_resolve_workspace_path` 对绝对路径做 resolve 与 is_relative_to 校验；mock 越界写入返回 JSON-RPC 错误，workspace 外未产生文件

- [x] CP-R4: 权限请求自动授权
  - **Type**: `rule`
  - **Covers**: AC-4, TR-3.3
  - **Evidence**: `session/request_permission` 优先选择 allow_once，mock 交互返回 optionId=allow-1

- [x] CP-R5: 文件生成工具已实现
  - **Type**: `rule`
  - **Covers**: AC-5, TR-4.1, TR-4.2, TR-4.3
  - **Evidence**: tools/acp_file_tools.py 中工具名与参数为 `generate_file_via_acp(filename, instruction)`；`../`、绝对路径、空串均返回错误；成功返回 status/path/name/size 且 size 与文件一致

- [x] CP-R6: 工具注册受开关控制且子 Agent 隔离
  - **Type**: `rule`
  - **Covers**: AC-6, TR-5.1, TR-5.2
  - **Evidence**: registry.py 第 108-110 行按 `ACP_ENABLED` 追加工具；运行时验证开关两种状态下工具列表正确，子 Agent 工具列表不含该工具

- [x] CP-R7: 主 Agent 路由规则已更新
  - **Type**: `rule`
  - **Covers**: AC-7, TR-5.3
  - **Evidence**: system_prompt.md 第 20 行要求生成文件时先汇总内容再调用 `generate_file_via_acp`，并在回答中告知文件名

- [x] CP-R8: 文件列表与下载接口已实现且受保护
  - **Type**: `rule`
  - **Covers**: AC-8, TR-6.1, TR-6.2, TR-6.3
  - **Evidence**: main.py 第 270-301 行两个接口均依赖 `get_current_user`；未带 Token 返回 401，带 Token 列表 200，中文文件下载内容一致，不存在文件 404，越界路径 400

- [x] CP-R9: 前端可下载生成文件
  - **Type**: `rule`
  - **Covers**: AC-9, TR-7.1, TR-7.2
  - **Evidence**: api/index.js 使用 blob 下载且 Token 走请求头；ChatView.vue 右侧“生成文件”面板展示文件名、大小、时间；浏览器实测登录后可见文件并成功触发下载

- [x] CP-R10: 异常场景可诊断
  - **Type**: `rule`
  - **Covers**: AC-11, TR-3.4, TR-8.3
  - **Evidence**: 命令缺失返回“未找到命令…”，超时返回“ACP 生成超时”，认证错误码 -32000 转换为登录提示；上述场景服务进程未崩溃

- [x] CP-U1: 生成文件内容与指令一致性
  - **Type**: `rubric`
  - **Covers**: AC-10, TR-8.2
  - **Scale**: 0-2
  - **Anchors**: 0 = 未生成或内容无关; 1 = 已生成但内容有遗漏; 2 = 覆盖指令要点且结构清晰
  - **Pass Threshold**: >= 1
  - **Evidence**: 评分 1/2。mock ACP 服务端按指令路径生成文件并成功落盘、可下载；本机未安装 `traecli`，真实 Agent 生成内容的质量未验证

## Review History

### Review R1
- **Result**: `pass`
- **Evidence**: 逐项检查 11 项 AC：10 项 rule 全部 PASS；1 项 rubric 评分 1/2，达到 >=1 阈值
- **Findings**:
  - Advisory: `system_prompt.md` 静态包含生成文件规则，而工具仅在 `ACP_ENABLED=true` 时注册；关闭开关时模型可能尝试调用不存在的工具，后续可按开关动态拼接该规则
  - Advisory: `WORKSPACE_DIR` 相对路径实际解析到 `backend/app/workspace`，与启动说明中的 `backend/workspace` 不一致；本次沿用既有行为，未改动
  - Residual: 本机未安装 TRAE CLI，真实端到端内容生成需在部署环境复验
- **Action**: 记录 advisory 供后续变更参考；残留项作为部署验收条件写入 tasks.md

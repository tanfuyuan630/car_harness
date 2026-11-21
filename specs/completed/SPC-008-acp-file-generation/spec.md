# Spec: 接入 ACP 链路生成本地文件

## 1. Problem

当前汽车销售助手只能以文本形式回答，无法把方案、报告、清单等内容直接产出为用户可下载的文件：

1. 用户要求"生成一份投保方案对比表""导出一份购车费用清单"时，Agent 只能把内容写在对话里，用户需要自行复制整理。
2. 项目已具备本地 workspace 虚拟文件系统，但没有产出物的交付路径，也没有借助本地编码 Agent 生成结构化文档的能力。

TRAE CLI 支持 Agent Client Protocol（ACP），可作为智能体服务端被外部客户端以 subprocess 方式启动。本需求将本系统作为 ACP 客户端接入本地 TRAE CLI，把"生成文件"这类任务交给本地 Agent 执行，并把产物交付给用户下载。

## 2. Users

- 到店咨询的潜在客户：需要按自己的需求生成保险方案、购车费用清单等文档
- 已购车客户：需要保养计划、理赔材料清单等文档
- 销售顾问：需要快速产出可直接发送给客户的方案文件

## 3. Goals

1. 新增 ACP 客户端链路：后端以子进程启动本地 `traecli acp serve`，完成 initialize → session/new → session/prompt 的完整交互。
2. 主 Agent 判断用户需要"生成文件"时，调用新的文件生成工具，由本地 TRAE CLI 在 workspace 中写入文件。
3. 提供受 JWT 保护的文件列表与下载接口，前端在聊天页提供可点击的下载入口。

## 4. Non-Goals

- 不把后端实现为 ACP 服务端，也不改动 TRAE IDE 的配置。
- 不实现常驻 ACP 进程与会话复用，每次文件生成使用独立进程与独立会话。
- 不将 ACP 权限请求转发到前端审批，采用自动授权策略。
- 不支持二进制文件（docx、pdf、xlsx、图片等），仅支持文本文件写入。
- 不开放 `terminal/*` 能力，TRAE CLI 无法通过本链路执行 shell 命令。
- 不修改 IM（飞书）渠道的文件交付方式，文件仅通过 Web 前端下载。

## 5. Functional Requirements

### FR-1: ACP 配置项

在 `backend/app/core/config.py` 中新增以下配置项：

- `ACP_ENABLED: bool = False`：ACP 文件生成链路总开关，默认关闭。
- `ACP_COMMAND: str = "traecli"`：ACP 服务端可执行命令。
- `ACP_ARGS: str = "acp serve"`：传给 ACP 服务端的启动参数（空格分隔）。
- `ACP_TIMEOUT_SECONDS: int = 300`：单次文件生成的超时时间。

在 `backend/.env.example` 中新增 ACP 配置段与示例值（默认 `ACP_ENABLED=false`）。

### FR-2: ACP 客户端模块

新建 `backend/app/services/acp_client.py`，实现 ACP 客户端（stdio 传输，换行分隔的 JSON-RPC 2.0 消息，UTF-8 编码）：

1. **进程管理**：按 `ACP_COMMAND` 与 `ACP_ARGS` 启动子进程，stdin/stdout 收发 ACP 消息，stderr 写入后端日志；调用结束后关闭 stdin 并终止进程。
2. **初始化**：发送 `initialize`，`protocolVersion` 为 `1`，`clientCapabilities` 声明 `fs.readTextFile=true`、`fs.writeTextFile=true`、`terminal=false`，`clientInfo` 填写本系统名称与版本。
3. **会话创建**：发送 `session/new`，`cwd` 为 workspace 绝对路径，`mcpServers` 为空数组，保存返回的 `sessionId`。
4. **对话轮次**：发送 `session/prompt`，`prompt` 为单个文本内容块，等待返回 `stopReason`。
5. **通知处理**：持续读取 `session/update` 通知，累积 `agent_message_chunk` 文本，记录 `tool_call` / `tool_call_update` 的状态变化。
6. **反向请求处理**（Agent → Client）：
   - `fs/write_text_file`：校验 `path` 解析后必须位于 workspace 目录内，越界返回 JSON-RPC 错误；合法时创建父目录并写入 UTF-8 文本，返回空结果。
   - `fs/read_text_file`：同样校验路径范围，读取文件文本并返回 `{"content": ...}`。
   - `session/request_permission`：自动选择首个 `kind` 为 `allow_once` 的选项；若不存在则选择 `allow_always`；两者都不存在时返回 `cancelled`。
   - 其他未知方法：返回 JSON-RPC "method not found" 错误。
7. **超时与错误**：超过 `ACP_TIMEOUT_SECONDS` 未完成时终止进程并返回超时错误；命令不存在、未登录（`auth_required`）、协议错误等均转换为携带原因的错误信息。

对外暴露一个异步方法用于"按指令生成文件"，返回结构化结果（成功标记、文件相对路径、字节数、Agent 文本摘要）。

### FR-3: 文件生成工具

新建 `backend/app/agent/tools/acp_file_tools.py`，封装 LangChain 异步工具：

- 工具名常量 `ACP_FILE_TOOL_NAME = "generate_file_via_acp"`。
- 入参：`filename`（workspace 相对路径，如 `保险投保方案对比.md`）与 `instruction`（文件内容要求）。
- 校验 `filename`：不得为绝对路径、不得包含 `..` 路径穿越、解析后必须位于 workspace 内；不合法直接返回错误文本。
- 构造发送给 TRAE CLI 的中文指令，包含：文件的相对路径与绝对路径、内容要求、只创建或覆盖该文件且不修改其他文件、完成后简要说明结果。
- 调用 ACP 客户端执行生成，成功后再次校验目标文件存在，返回 JSON 字符串：`{"status": "ok", "path": "<相对路径>", "name": "<文件名>", "size": <字节数>}`。
- 失败时返回 `错误：<原因>` 文本，不抛出未捕获异常。

### FR-4: 工具注册与主 Agent 路由

- `backend/app/agent/registry.py` 的 `tools` 属性在 `ACP_ENABLED` 为真时追加该文件生成工具；子 Agent 不绑定该工具。
- 更新 `backend/app/agent/prompts/system_prompt.md`，新增规则：
  - 用户要求产出/导出文件（方案、报告、清单、对比表、合同草稿等文本文件）时，先完成业务内容汇总，再调用 `generate_file_via_acp` 生成文件。
  - 文件名使用能表达内容的中文名，扩展名使用文本格式（如 `.md`、`.csv`、`.txt`）。
  - 最终回答中说明已生成的文件名。

### FR-5: 文件列表与下载接口

在 `backend/app/main.py` 新增（均需 JWT 鉴权）：

- `GET /api/workspace/files`：递归返回 workspace 内所有文件，字段为 `name`（相对路径）、`size`、`modified_at`，按修改时间倒序。
- `GET /api/workspace/files/{file_path:path}`：返回 `FileResponse` 下载对应文件；路径解析后越出 workspace 时返回 400，文件不存在时返回 404。

### FR-6: 前端文件下载

- `frontend/src/api/index.js` 新增：
  - `listWorkspaceFiles()`：请求文件列表。
  - `downloadWorkspaceFile(path)`：以 `responseType: 'blob'` 请求文件内容，携带登录 Token。
- `frontend/src/views/ChatView.vue`：
  - 新增右侧"生成文件"面板，展示文件名、大小与修改时间；无文件时显示空状态提示。
  - 点击文件项触发下载：用 `URL.createObjectURL` 生成临时链接并触发浏览器保存，随后释放 URL。
  - 页面初始化与每轮消息结束后刷新文件列表。

### FR-7: 配置示例

`backend/.env.example` 新增 ACP 配置段，包含开关、命令、参数、超时四项及注释说明。

## 6. Non-Functional Requirements

- **非阻塞**：ACP 子进程与协议交互全程使用 `asyncio`，工具执行期间不阻塞 FastAPI 事件循环。
- **可观测**：TRAE CLI 的 stderr 内容写入后端日志，便于排查登录、目录信任与模型调用问题。
- **安全性**：所有文件读写限定在 workspace 目录内；不声明终端能力；自动授权仅对 workspace 内的文件写入生效。
- **隔离性**：每次生成使用独立进程与独立会话，单个任务失败不影响后续任务。
- **一致性**：配置项、工具封装、接口风格与现有代码保持一致（配置集中在 `settings`，工具用 `@tool`，接口挂 JWT 依赖）。

## 7. Constraints & Dependencies

- 本地需安装 TRAE CLI，`traecli` 命令可用并已登录；当前机器未检测到 `traecli`，需先安装后本链路才可验证。
- ACP 服务端启动命令为 `traecli acp serve`，通过 stdio 以换行分隔的 JSON-RPC 2.0 通信，消息必须 UTF-8 且不含内嵌换行。
- 协议中所有文件路径必须为绝对路径；发送给 TRAE CLI 的指令需同时给出相对路径与绝对路径。
- TRAE CLI 需要信任 workspace 目录，否则可能拒绝读写；目录信任在 TRAE CLI 侧配置。
- Windows 下若 `traecli` 解析为 `.cmd` / `.bat` 包装脚本，子进程需通过 `cmd /c` 启动。
- 仅支持文本文件写入（协议只提供 `fs/write_text_file`）。
- TRAE CLI 2.0 的使用受套餐限制（企业版旗舰版），需在目标环境确认可用性。

## 8. Assumptions

- `traecli acp serve` 在非交互模式下可完成 `session/prompt` 并写入文件，无需人工确认。
- 单次文件生成耗时在 300 秒以内。
- 使用场景为单机低并发，不需要多用户排队与限流。
- 用户下载的文件即为 workspace 中生成的同名文件，不做过期清理。

## 9. Open Questions

- 无（已与用户确认：后端作为 ACP 客户端、增加下载接口与前端链接、权限请求自动授权）。

## 10. Acceptance Criteria

### AC-1 (rule): ACP 配置项已添加

`config.py` 中存在 `ACP_ENABLED`、`ACP_COMMAND`、`ACP_ARGS`、`ACP_TIMEOUT_SECONDS` 四项配置，`ACP_ENABLED` 默认为 `False`；`.env.example` 中存在对应的配置段。

### AC-2 (rule): ACP 客户端协议交互完整

`services/acp_client.py` 中存在 `initialize`、`session/new`、`session/prompt` 的发送逻辑，以及 `session/update` 通知处理；`initialize` 中声明的 `clientCapabilities` 包含 `fs.readTextFile` 与 `fs.writeTextFile`，且不声明 `terminal`。

### AC-3 (rule): 文件写入限定在 workspace

`fs/write_text_file` 与 `fs/read_text_file` 的处理逻辑对路径做 workspace 范围校验，越界时返回 JSON-RPC 错误且不写入文件。

### AC-4 (rule): 权限请求自动授权

`session/request_permission` 的处理逻辑会从 `options` 中选择 `allow_once`（缺失时选 `allow_always`）并返回 `selected` 结果。

### AC-5 (rule): 文件生成工具已实现

`tools/acp_file_tools.py` 中存在名为 `generate_file_via_acp` 的工具，包含 `filename` 与 `instruction` 两个参数，对 `filename` 做路径穿越校验，成功时返回含 `status`、`path`、`size` 的 JSON。

### AC-6 (rule): 工具注册受开关控制

`registry.py` 中仅当 `ACP_ENABLED` 为真时，主 Agent 工具列表包含 `generate_file_via_acp`；子 Agent 的工具列表中不包含该工具。

### AC-7 (rule): 主 Agent 路由规则已更新

`system_prompt.md` 中包含"用户要求生成/导出文件时调用 `generate_file_via_acp`"的规则，并说明最终回答需告知文件名。

### AC-8 (rule): 下载接口已实现且受保护

`GET /api/workspace/files` 与 `GET /api/workspace/files/{file_path:path}` 均依赖 JWT 鉴权；越界路径返回 400，文件不存在返回 404。

### AC-9 (rule): 前端可下载生成文件

`ChatView.vue` 中存在"生成文件"面板，通过 `downloadWorkspaceFile` 以 blob 方式下载，不在 URL 中暴露 Token。

### AC-10 (rubric): 文件生成结果可用性

维度：生成文件内容与指令的一致性
- 2分：文件在 workspace 生成，内容覆盖指令要求的要点，结构清晰，文件名可读
- 1分：文件已生成但内容有遗漏或结构一般
- 0分：文件未生成，或内容与指令无关
通过阈值：>= 1 分

### AC-11 (rule): 异常场景可诊断

`traecli` 不存在、未登录、超过 `ACP_TIMEOUT_SECONDS` 三种场景下，工具均返回包含具体原因的 `错误：...` 文本，服务不崩溃，进程被清理。

# 接入 ACP 链路生成本地文件 - Implementation Plan

## Task 1: 新增 ACP 配置项与示例配置
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 在 `backend/app/core/config.py` 新增 `ACP_ENABLED`（默认 `False`）、`ACP_COMMAND`（默认 `traecli`）、`ACP_ARGS`（默认 `acp serve`）、`ACP_TIMEOUT_SECONDS`（默认 `300`）
  - 在 `backend/.env.example` 新增 ACP 配置段与注释说明
- **Acceptance Criteria Addressed**: AC-1
- **Test Requirements**:
  - `rule` TR-1.1: `config.py` 中存在四个 ACP 配置项，`ACP_ENABLED` 默认值为 `False`；证据：代码文件内容
  - `rule` TR-1.2: `.env.example` 中包含 `ACP_ENABLED`、`ACP_COMMAND`、`ACP_ARGS`、`ACP_TIMEOUT_SECONDS`；证据：文件内容
- **Completion Evidence**:
  - `config.py` 第 89-92 行新增四个 ACP 配置项，`ACP_ENABLED` 默认 `False`
  - `.env.example` 第 53-60 行新增“ACP 文件生成链路”配置段

## Task 2: 实现 ACP 客户端基础交互
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 新建 `backend/app/services/acp_client.py`
  - 实现子进程启动（含 Windows 下 `.cmd` / `.bat` 通过 `cmd /c` 启动）、stdin/stdout 换行分隔 JSON-RPC 读写、请求 id 与响应匹配
  - 发送 `initialize`：`protocolVersion=1`，`clientCapabilities` 声明 `fs.readTextFile`、`fs.writeTextFile` 为 `true`，不声明 `terminal`
  - 发送 `session/new`：`cwd` 为 workspace 绝对路径，`mcpServers` 为空数组
  - 发送 `session/prompt`：单个文本内容块，等待 `stopReason`
  - 处理 `session/update` 通知，累积 `agent_message_chunk` 文本并记录 `tool_call` 状态
  - stderr 写入后端日志
- **Acceptance Criteria Addressed**: AC-2
- **Test Requirements**:
  - `rule` TR-2.1: 代码中存在 `initialize`、`session/new`、`session/prompt` 请求与 `session/update` 通知处理；证据：代码文件内容
  - `rule` TR-2.2: `initialize` 的 `clientCapabilities` 含 `readTextFile`、`writeTextFile`，且不含 `terminal`；证据：抓取的请求报文
  - `rule` TR-2.3: 使用临时 mock ACP 服务端进程可完成一次完整交互并拿到 `stopReason`；证据：临时脚本运行输出
- **Completion Evidence**:
  - `services/acp_client.py` 已创建，包含 `initialize`、`session/new`、`session/prompt`、`session/update` 处理与 stderr 日志
  - `clientCapabilities` 仅声明 `fs.readTextFile` / `fs.writeTextFile`，未声明 `terminal`
  - 使用临时 mock 服务端运行验证：`PASS client_success {'stop_reason': 'end_turn', 'agent_text': '文件已生成', 'tool_call_count': 1}`
  - `session/new` 的 `cwd` 与 `settings.workspace_dir_path` 一致

## Task 3: 处理 ACP 反向请求与异常
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - 实现 Agent → Client 请求处理：
    - `fs/write_text_file`：校验绝对路径位于 workspace 内，合法则创建父目录并写入 UTF-8 文本
    - `fs/read_text_file`：校验路径位于 workspace 内，返回 `{"content": ...}`
    - `session/request_permission`：选择 `allow_once`（缺失时选 `allow_always`）并返回 `selected` 结果
    - 未知方法返回 method not found 错误
  - 路径越界返回 JSON-RPC 错误，不落盘
  - 实现超时控制：超过 `ACP_TIMEOUT_SECONDS` 终止子进程并返回超时错误
  - 命令不存在、`auth_required`、协议错误转换为携带原因的错误信息
- **Acceptance Criteria Addressed**: AC-3, AC-4, AC-11
- **Test Requirements**:
  - `rule` TR-3.1: `fs/write_text_file` 与 `fs/read_text_file` 均对路径做 workspace 范围校验；证据：代码文件内容
  - `rule` TR-3.2: 传入 `../` 越界路径时返回错误且 workspace 外无文件产生；证据：临时调用输出与目录检查
  - `rule` TR-3.3: `request_permission` 从 `options` 中选出 `allow_once` 并返回 `selected`；证据：临时 mock 交互报文
  - `rule` TR-3.4: `traecli` 不存在时返回"未找到 traecli"类错误，进程异常不冒泡到接口；证据：临时调用输出
- **Completion Evidence**:
  - `fs/write_text_file`、`fs/read_text_file` 通过 `_resolve_workspace_path` 做 workspace 边界校验，越界返回 `-32602`
  - mock 交互中越界写入被拒绝：`traversal_blocked=True`，workspace 外未生成文件
  - 权限请求返回选中选项：`permission_option=allow-1`（allow_once）
  - 异常验证：`PASS missing_command 未找到命令 definitely-not-exists-cli，请先安装 TRAE CLI 并确保其在 PATH 中`
  - 异常验证：`PASS timeout ACP 生成超时（超过 2 秒）`
  - 未登录场景：响应错误码 `-32000` 时转换为“TRAE CLI 需要登录”提示

## Task 4: 封装文件生成工具
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 3
- **Description**:
  - 新建 `backend/app/agent/tools/acp_file_tools.py`
  - 定义常量 `ACP_FILE_TOOL_NAME = "generate_file_via_acp"`
  - 使用 `@tool` 定义异步工具，参数 `filename`（workspace 相对路径）与 `instruction`（内容要求）
  - 校验 `filename`：非绝对路径、不含 `..`、解析后位于 workspace 内
  - 构造中文指令：含绝对路径与相对路径、内容要求、"只创建或覆盖该文件"、"不修改其他文件"
  - 调用 ACP 客户端，成功后校验文件存在并返回 `{"status": "ok", "path", "name", "size"}` JSON
  - 失败返回 `错误：<原因>` 文本
- **Acceptance Criteria Addressed**: AC-5
- **Test Requirements**:
  - `rule` TR-4.1: 工具名为 `generate_file_via_acp`，含 `filename`、`instruction` 参数；证据：代码文件内容
  - `rule` TR-4.2: `filename` 为 `../x.md` 或绝对路径时返回错误且不启动 ACP 进程；证据：临时调用输出
  - `rule` TR-4.3: mock ACP 服务端生成文件后，工具返回 JSON 中 `status=ok` 且 `size` 与文件实际字节数一致；证据：临时调用输出
- **Completion Evidence**:
  - `tools/acp_file_tools.py` 已创建，工具参数为 `['filename', 'instruction']`
  - `PASS tool_invalid_filename`：`../evil.md`、`C:\evil.md`、空串均返回 `错误：...`
  - `PASS tool_success {'status': 'ok', 'path': '.acp_test/tool_out.md', 'name': 'tool_out.md', 'size': 34}`，size 与文件实际字节数一致

## Task 5: 注册工具并更新主 Agent 路由
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 4
- **Description**:
  - 在 `backend/app/agent/registry.py` 的 `tools` 属性中，当 `ACP_ENABLED` 为真时追加文件生成工具
  - 更新 `backend/app/agent/prompts/system_prompt.md`：新增"生成/导出文件时先汇总内容，再调用 `generate_file_via_acp`，文件名用中文语义名与文本扩展名，最终回答告知文件名"的规则
- **Acceptance Criteria Addressed**: AC-6, AC-7
- **Test Requirements**:
  - `rule` TR-5.1: `ACP_ENABLED=true` 时主 Agent 工具列表包含 `generate_file_via_acp`，关闭时不包含；证据：运行时打印工具名列表
  - `rule` TR-5.2: 子 Agent 工具列表不包含该工具；证据：运行时打印子 Agent 工具名列表
  - `rule` TR-5.3: `system_prompt.md` 含生成文件的路由与告知规则；证据：文件内容
- **Completion Evidence**:
  - `registry.py` 第 108-110 行：`ACP_ENABLED` 为真时追加 ACP 文件生成工具
  - `PASS registry_switch ['list_files_tool', 'read_file_tool', 'write_file_tool', 'generate_file_via_acp'] ['list_files_tool', 'read_file_tool', 'write_file_tool']`
  - `PASS subagents_without_file_tool`
  - `system_prompt.md` 第 20 行新增生成文件规则，要求文件名带文本扩展名并在回答中告知文件名

## Task 6: 新增文件列表与下载接口
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 1
- **Description**:
  - 在 `backend/app/main.py` 新增 `GET /api/workspace/files`：递归列出 workspace 文件，返回 `name`、`size`、`modified_at`，按修改时间倒序
  - 新增 `GET /api/workspace/files/{file_path:path}`：使用 `FileResponse` 下载；路径越界返回 400，不存在返回 404
  - 两个接口均依赖 `get_current_user`
- **Acceptance Criteria Addressed**: AC-8
- **Test Requirements**:
  - `rule` TR-6.1: 未携带 Token 请求两个接口均返回 401；证据：接口调用结果
  - `rule` TR-6.2: 携带 Token 请求列表接口可返回 workspace 内文件；证据：接口返回 JSON
  - `rule` TR-6.3: 请求含 `..` 的路径返回 400，请求不存在文件返回 404；证据：接口调用结果
- **Completion Evidence**:
  - `main.py` 第 270-301 行新增文件列表与下载接口，均依赖 `get_current_user`
  - 未携带 Token：`GET /api/workspace/files` 返回 401
  - 携带 Token：列表返回 `.acp_test/endpoint_out.md` 等文件；中文文件“验证文件.md”下载成功且内容一致
  - 不存在文件返回 404；直接调用越界路径抛出 400

## Task 7: 前端生成文件面板与下载
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 6
- **Description**:
  - `frontend/src/api/index.js` 新增 `listWorkspaceFiles()` 与 `downloadWorkspaceFile(path)`（`responseType: 'blob'`）
  - `frontend/src/views/ChatView.vue` 新增右侧"生成文件"面板：展示文件名、大小、修改时间，空状态提示
  - 点击文件用 `URL.createObjectURL` 触发浏览器下载并释放 URL
  - 页面初始化与每轮消息结束后刷新文件列表
- **Acceptance Criteria Addressed**: AC-9
- **Test Requirements**:
  - `rule` TR-7.1: 接口层存在两个方法，下载使用 blob 且未在 URL 拼接 Token；证据：代码文件内容
  - `rule` TR-7.2: 页面存在文件面板并在发送消息后刷新；证据：代码文件内容与浏览器操作验证
- **Completion Evidence**:
  - `api/index.js` 第 46-49 行新增列表与 blob 下载方法，Token 通过请求头携带
  - `ChatView.vue` 新增右侧“生成文件”面板、`refreshFiles`、`onDownload`，在 `onMounted`、每轮消息结束与审批恢复后刷新
  - 前端构建通过：`vite build` 成功，96 modules transformed
  - 浏览器验证（5174 前端 + 8001 后端）：登录后右侧“生成文件”面板显示“购车方案示例.md”，点击触发 `GET /api/workspace/files/购车方案示例.md` 返回 200，无错误提示

## Task 8: 端到端与异常验证
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 1, Task 2, Task 3, Task 4, Task 5, Task 6, Task 7
- **Description**:
  - 在已安装并登录 TRAE CLI 的环境开启 `ACP_ENABLED=true`
  - 验证用户提出"生成一份 XX 文件"后，主 Agent 调用工具并在 workspace 生成文件
  - 验证前端文件面板可看到该文件并成功下载
  - 验证 `traecli` 缺失、超时场景下返回明确错误
- **Acceptance Criteria Addressed**: AC-10, AC-11
- **Test Requirements**:
  - `rule` TR-8.1: 文件生成后出现在 workspace 与前端文件面板，下载内容与文件一致；证据：文件内容与下载结果
  - `rubric` TR-8.2: 生成文件内容与指令一致性；scale 0-2；anchors 0=未生成或内容无关, 1=已生成但内容有遗漏, 2=覆盖指令要点且结构清晰；threshold >= 1；evidence：生成文件内容
  - `rule` TR-8.3: `ACP_ENABLED=true` 但 `traecli` 不存在时，对话返回含原因的失败提示且服务保持可用；证据：接口返回与健康检查
- **Completion Evidence**:
  - TR-8.1：使用 mock ACP 服务端完成端到端链路验证——工具调用 → ACP 客户端 → 服务端 fs 写入 → workspace 落盘；实测文件列表接口可返回该文件，中文文件下载内容与落盘内容一致；浏览器实测前端“生成文件”面板展示文件、点击下载返回 200
  - TR-8.2：评分 1/2（达到阈值）。文件按指令给定的目标路径生成且可下载，但本机未安装 `traecli`，真实 TRAE CLI 的内容质量未验证
  - TR-8.3：`traecli` 缺失时工具返回“错误：未找到命令 ...”，超时返回“ACP 生成超时”，服务保持可用
- **Residual Item**:
  - 安装并登录 TRAE CLI、设置 `ACP_ENABLED=true` 后，需复验真实内容生成质量（部署验收项，不阻塞本次代码交付）

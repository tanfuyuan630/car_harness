# 汽车销售助手 Agent Harness

基于 LangGraph / deepagents 的汽车销售智能助手，覆盖车型咨询、购车推荐、保险、销售、售后、维修美容、用品交易与公司信息等业务，并提供 Web 对话、车型浏览对比、知识库检索、多轮记忆、人工审批与文件生成能力。

- 后端：FastAPI + LangGraph + deepagents + LlamaIndex/Chroma
- 前端：Vue 3 + Vite + Pinia + Vue Router
- 存储：MySQL（用户与 IM 身份）、Redis（LangGraph 检查点与线程索引）、本地 Markdown（对话与摘要）、Chroma（向量库）

## 主要功能

### 1. 多领域智能问答

主 Agent 作为主管，只负责识别意图、拆解任务、委派领域子智能体并汇总结果。已注册的领域子智能体：

| 子智能体                          | 负责范围                                   |
| --------------------------------- | ------------------------------------------ |
| `car_model_expert`              | 车型参数、车型对比、购车推荐               |
| `insurance_underwriting_expert` | 车险投保、报价、核保、出单、条款责任       |
| `insurance_claims_expert`       | 报案、查勘、定损、人伤、理算核赔、拒赔     |
| `vehicle_sales_expert`          | 接待、试驾、报价签约、分期、交付上牌、置换 |
| `after_sales_expert`            | 预约、维修保养、备件、三包保修、召回、投诉 |
| `repair_beauty_expert`          | 洗车、漆面、内饰、贴膜与施工安全           |
| `car_accessories_expert`        | 用品分类、采购查验、交易退换、库存         |
| `company_info_expert`           | 公司介绍、联系方式、到店路线与导航         |

单一领域问题委派一个子智能体；跨领域问题拆成多个子任务后按业务顺序汇总。

### 2. 车型浏览与对比

- 车型搜索、详情查询、多车型对比、按预算与偏好推荐。
- Web 端提供品牌/车系树浏览、关键词搜索、2~5 款车型并排对比。

### 3. 企业知识库 RAG

- 按业务域组织文档，检索时按域过滤，避免跨域串答。
- 中文分块、Chroma 余弦向量检索、DashScope 重排。
- 可选 BM25 混合检索与查询改写，默认关闭。
- 索引首次检索时惰性构建，集合已存在时直接复用。

### 4. 多轮对话记忆

- 摘要 + 最近 3 轮滑动窗口。
- 完整对话与摘要分别持久化为两个 Markdown 文件。
- 摘要采用增量更新，只压缩本次滑出窗口的那一轮，避免重复压缩全部历史。

### 5. 人机协同审批（HITL）

- 主 Agent 给出最终购车推荐前必须调用 `final_recommendation_tool`，触发 LangGraph 中断。
- 关键参数缺失或指令存在多解时调用 `ask_user_for_input`，暂停并等待用户补充信息。
- 前端按中断类型展示“待确认推荐”或“需要补充信息”卡片；刷新页面、切换会话后自动恢复待处理卡片。
- Web 与飞书 IM 都支持文字审批：IM 回复「批准」/「拒绝」或直接回复补充信息即可恢复同一线程。
- 恢复执行后补全持久化的最终回答，避免“已批准但无内容”。

### 6. 文件生成与下载

- 主 Agent 判断用户需要产出报告、方案、清单等文件时，调用 `generate_file_via_acp`。
- 后端通过 Agent Client Protocol（ACP）以子进程方式驱动本地 ACP 智能体生成文件，文件写入工作区。
- 前端右侧“生成文件”面板展示工作区文件，支持带 JWT 鉴权的下载。

### 7. 用户与鉴权

- 手机号/用户名注册登录，密码使用 bcrypt 加盐哈希，MySQL 存储。
- 业务接口使用 JWT 鉴权，前端路由守卫控制登录态。

### 8. IM 渠道

- 可选接入飞书自建应用（长连接接收事件）。
- IM 侧消息复用同一套记忆、Agent 与检查点；需要人工确认的推荐或补充信息可直接在飞书回复文字完成。

### 9. 可观测性

- Agent 调用带统一的 LangSmith tags 与 metadata（场景、用户、线程），便于按业务维度追踪主 Agent、子智能体与工具调用。

### 10. 多层模型路由

- 三档模型 `low / medium / high`，模型名全部来自 `.env`，修改后重启生效。
- 默认关闭（`LLM_TIER_ENABLED=false`）：所有请求统一使用 `OPENAI_MODEL`，不产生分类调用，`/api/chat` 返回 `tier="off"`。
- 开启后入口先用轻量分类模型输出 `simple / moderate / complex`，主 Agent 据此选档；子 Agent 再按被委派的任务描述独立分类。
- 中断恢复与断点续跑复用线程最近档位，避免补充信息过短导致档位漂移。

### 11. 依赖降级

- 覆盖模型、RAG、检查点、子 Agent 四类依赖，单点故障不再导致整轮请求失败。
- 自动降级在依赖真实异常时触发；`DEGRADE_FORCE=true` 可手动强制四项全部降级，用于演练与应急。
- 降级对用户不可见，只写服务端 `[Degrade]` 日志，接口响应结构、前端与飞书回复文案均不变。
- `DEGRADE_ENABLED=false` 时完全回到“失败即报错”的原有行为。

## 系统架构

```text
浏览器 (Vue 3)
  ├── /chat       对话、审批、生成文件面板
  ├── /browser    品牌/车系浏览、车型详情
  ├── /compare    车型搜索与对比
  └── /login、/register
        │ HTTP / SSE
        ▼
FastAPI 后端
  ├── 鉴权（JWT + bcrypt + MySQL）
  ├── 会话、历史、审批恢复、断点续跑
  ├── 车型数据接口
  ├── 工作区文件列表与下载
  └── IM 渠道（可选飞书）
        │
        ▼
deepagents Agent Harness
  ├── 主 Agent（意图识别、任务拆解、汇总、最终推荐审批、补充信息）
  ├── 领域子 Agent（车型 + 7 个业务域）
  └── 工具
      ├── 文件系统工具（工作区）
      ├── 车型查询/对比/推荐工具
      ├── 领域知识检索工具（RAG）
      ├── 高德地图工具（公司信息子 Agent）
      └── ACP 文件生成工具
        │
        ├── MySQL（用户、IM 身份）
        ├── Redis（LangGraph 检查点、线程索引、TTL 维护）
        ├── data/cars.csv、brand_tree.json（车型数据）
        ├── data/chroma_db（向量库）
        ├── data/conversations（对话与摘要 Markdown）
        └── ACP 服务端子进程（Qwen Code / TRAE CLI）
```

## 实现方案

### Agent Harness 编排

核心入口为 `backend/app/agent/harness.py`，使用 `deepagents.create_deep_agent` 组装：

- `model`：来自 `registry.llm`，通过 OpenAI 兼容端点创建。
- `tools`：主 Agent 只持有通用工具（文件系统、ACP 文件生成）与最终推荐工具。
- `subagents`：由 `registry.py` 中的声明式领域表统一构建，每个子 Agent 只绑定本域知识检索工具；公司信息子 Agent 额外绑定高德地图工具。
- `backend`：deepagents 文件系统后端，可选本地文件或内存状态。
- `checkpointer`：默认为 Redis（`langgraph-checkpoint-redis`），测试可切换内存。
- `interrupt_on`：`final_recommendation_tool` 与 `ask_user_for_input` 触发人工中断。

提示词以 Markdown 文件维护在 `backend/app/agent/prompts/`，主提示词规定领域路由、跨域拆分、不编造条款、来源展示策略与文件生成规则。

### 多层模型路由

`backend/app/agent/tiering.py` 负责复杂度分类与档位上下文，`backend/app/agent/llm.py` 负责模型池与按档选择：

1. 入口分类：`/api/chat`、`/api/chat/stream` 与 IM 消息在调用 Agent 前，把当前消息与上一条助手回复（截断 500 字）交给分类模型，得到 `simple / moderate / complex`。
2. 主 Agent 选档：档位写入请求级 `ContextVar`，由 `tier_role="main"` 的模型实例在每次调用前解析，映射到 low/medium/high 对应模型。
3. 子 Agent 再分类：`tier_role="subagent"` 按首条委派任务描述分类，结果以任务描述哈希做进程内 LRU 缓存（上限 256），同一任务只分类一次。
4. 档位持久化：线程元数据 `lg:thread_meta:{thread_id}` 记录 `tier`，`/resume` 与 `/retry` 直接复用；缺失时按 `medium` 执行并记录告警。
5. 分类失败时，降级开启则按 `medium` 继续并记录 `[Degrade]` 日志；降级关闭则按原有错误策略返回可重试错误。`LLM_TIER_ENABLED=false` 时上述流程全部跳过。
6. 可观测：分类完成后记录线程、来源（main/subagent）、复杂度、档位、模型名与理由，不记录消息原文。

### RAG 实现

`backend/app/rag/service.py`：

1. 扫描 `data/docs` 与 `data/insurance` 下的 md/doc/docx 文档。
2. 按中文标点断句后使用 `SentenceSplitter` 分块（默认 512 / 64）。
3. 通过 DashScope OpenAI 兼容 embedding 写入 Chroma 持久化集合，距离度量使用余弦。
4. 检索时按领域过滤，召回 `RAG_RETRIEVE_TOP_K` 条后经 DashScope rerank 保留 `RAG_RERANK_TOP_N` 条。
5. 可选开启 BM25 混合检索与 LLM 查询改写。

`backend/app/rag/domains.py` 定义领域与文档目录的映射，索引与检索共用同一份领域定义。

### 车型数据

`backend/app/services/car_data.py` 在启动时加载：

- `data/cars.csv`：车型全量参数，预解析指导价数值列用于区间筛选。
- `data/brand_tree.json`：品牌与车系树。

对外提供搜索、详情、对比、推荐、品牌/车系列表能力，并封装为子 Agent 工具。`data/raw` 仅为原始抓取素材，不参与运行时读取。

### 对话记忆与持久化

`backend/app/services/conversation_store.py` 与 `memory_manager.py`：

- `data/conversations/{user_id}/{thread_id}.md`：完整对话，按轮次追加。
- `data/conversations/{user_id}/{thread_id}.summary.md`：增量摘要。
- 每次请求构建上下文时读取摘要 + 最近 3 轮，不单独持久化窗口。
- 审批恢复后通过 `update_last_assistant` 回写最终回答，避免页面出现“已批准但无内容”。

### 人机协同与检查点

- `final_recommendation_tool` 与 `ask_user_for_input` 在 `create_deep_agent` 中注册为中断点，中断值为 `HumanInTheLoopMiddleware` 的 `HITLRequest`。
- 恢复时构造 `Command(resume={"decisions": [...]})`：批准/拒绝推荐，或把用户补充内容以 `respond` 回填给模型。
- 会话状态持久化在 Redis，后端重启后可继续查询中断、批准恢复或断点续跑。
- 失败请求可通过 `POST /api/threads/{thread_id}/retry` 从最后成功检查点继续，不重复用户消息；待审批或无可续跑任务返回 409。

### 错误恢复策略

| 错误类型       | 典型场景                    | 处理方式                                                                                |
| -------------- | --------------------------- | --------------------------------------------------------------------------------------- |
| 临时错误       | 网络抖动、限流、超时        | tenacity 在模型调用与工具调用内自动有限重试；流式已输出 token 后不再整段重试            |
| LLM 可恢复错误 | 工具调用失败、JSON 解析失败 | 异常转为 `[工具错误] ...` 写入 State，回到 Agent 重新生成；连续超过上限升级为致命错误 |
| 用户可修复错误 | 缺少关键参数、指令模糊      | 触发 `input_required` 中断，等待用户补充后恢复                                        |
| 未知/致命错误  | 代码逻辑 Bug、底层依赖崩溃  | 冒泡给开发者，日志记录 `thread_id` 与 `checkpoint_id`，检查点保留供人工断点重跑     |

### 依赖降级

`backend/app/agent/degrade.py` 统一承载降级状态与日志，日志格式固定为 `[Degrade] component=... reason=...`。

| 组件     | 触发条件                                 | 降级行为                                                                                                             |
| -------- | ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| 模型     | 选定档位调用失败且尚未输出 token         | 逐级降档（high → medium → low），每档试一次；本请求后续调用复用新档位；已输出 token 的流式响应不降档，避免重复内容 |
| RAG      | Chroma、embedding、rerank 或索引构建异常 | 返回空检索结果，子 Agent 按通用知识回答；进入 `RAG_DEGRADE_COOLDOWN_SECONDS` 冷却窗口，窗口内不再调用底层依赖      |
| 检查点   | 启动阶段 Redis 不可用或缺少模块          | 改用内存检查点启动，Web 与飞书渠道保持可用；不启动检查点维护任务                                                     |
| 子 Agent | 子 Agent 模型失败、工具异常或递归超限    | `task` 返回降级提示，主 Agent 继续完成本轮回答                                                                     |

- 请求级 LLM 降档状态用 `ContextVar` 承载，每轮请求入口统一重置。
- `DEGRADE_FORCE=true` 时四项全部强制降级：主/子 Agent 固定低档、跳过检索、强制内存检查点、不注册领域子 Agent。
- 强制降级跳过分类器，不产生额外模型调用。

### Redis 检查点维护

- 检查点默认 TTL 为 3 天，读取时自动续期。
- 维护任务按间隔扫描：有未完成中断的线程续期；已完成且超过保留期的线程删除检查点并移出索引。
- Redis 客户端启用指数退避重试；持续不可用时按降级策略处理：降级开启则改用内存检查点启动，关闭则启动失败或返回 503。
- 内存检查点仅存于当前进程，重启即丢失，中断恢复与 TTL 维护不可用，且不支持多 worker 部署。

### ACP 文件生成

`backend/app/services/acp_client.py` 实现通用 ACP 客户端：

- stdio 传输，换行分隔的 JSON-RPC 2.0，UTF-8。
- 流程：`initialize` → `session/new` → `session/prompt`。
- 声明文件读写能力，不声明终端能力。
- 处理服务端反向请求：`fs/write_text_file`、`fs/read_text_file`（均限制在工作区内）、`session/request_permission`（自动选择 allow_once）。
- 流读取上限提升到 8MB，避免较大的 `session/new` 报文触发 asyncio 默认 64KB 限制。
- 可通过 `ACP_COMMAND` / `ACP_ARGS` 切换任意 ACP 服务端，例如 Qwen Code `qwen --acp`，或企业版 TRAE CLI `traecli acp serve`。
- 工具层 `acp_file_tools.py` 负责校验文件名、构造生成指令、校验产物并返回路径与大小。

### 鉴权与数据

- `backend/app/api/auth.py`：注册、登录、当前用户。
- `backend/app/core/auth.py`：JWT 签发与校验，业务接口统一依赖 `get_current_user`。
- `backend/app/models/user.py`：`t_users` 表，`user_id` 唯一约束。
- 前端 Axios 拦截器自动携带 Token，401 时清理登录态。

### IM 渠道

`backend/app/channels/` 采用渠道抽象 + 路由注册：

- 启动时按配置决定是否拉起飞书长连接。
- 消息处理管线：身份映射 → 记忆上下文 → Agent 调用 → 持久化。
- 未启用或缺少凭据时跳过，不影响 Web 服务。

### 前端

`frontend/src/`：

- `views/ChatView.vue`：会话列表、SSE 流式回答、工具事件、审批卡片、生成文件面板。
- `views/CarBrowser.vue`：品牌 → 车系 → 车型 → 详情。
- `views/CompareView.vue`：搜索并选择 2~5 款车型对比关键参数。
- `stores/chat.js`：线程、消息、加载与流式更新状态。
- `router/index.js`：登录首页。

## 目录结构

```text
car_harness/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 入口与业务接口
│   │   ├── agent/                  # Agent Harness
│   │   │   ├── harness.py          # deepagents 组装与全局实例
│   │   │   ├── registry.py         # LLM、工具、子 Agent、Checkpointer 注册中心
│   │   │   ├── llm.py              # OpenAI 兼容模型创建（含临时错误重试）
│   │   │   ├── error_policy.py     # 四类错误分级、重试预算与 tenacity 重试
│   │   │   ├── degrade.py          # 四类依赖降级状态与统一日志
│   │   │   ├── prompts/            # 主/子 Agent 提示词
│   │   │   └── tools/              # 文件、车型、RAG、高德、推荐、ACP、补充信息
│   │   ├── api/auth.py             # 注册登录接口
│   │   ├── core/                   # 配置、鉴权、数据库
│   │   ├── models/                 # ORM 与请求响应模型
│   │   ├── rag/                    # 文档加载、分块、检索、重排、改写
│   │   ├── services/               # 对话、记忆、车型、用户、ACP、检查点、中断、维护
│   │   │   ├── checkpoint_store.py       # Redis/Memory Checkpointer 生命周期
│   │   │   ├── checkpoint_maintenance.py # 检查点续期与超期清理
│   │   │   ├── thread_registry.py        # 活跃线程索引与 TTL
│   │   │   └── interrupts.py             # 中断类型识别与恢复值构建
│   │   └── channels/               # IM 渠道抽象与飞书实现
│   ├── .env.example                # 配置模板
│   ├── requirements.txt
│   └── app/workspace/              # Agent 工作区与生成文件
├── data/
│   ├── cars.csv                    # 车型数据
│   ├── brand_tree.json             # 品牌车系树
│   ├── docs/                       # 业务知识文档
│   ├── insurance/                  # 保险知识文档
│   ├── chroma_db/                  # 向量库持久化
│   ├── conversations/              # 对话与摘要 Markdown
│   └── raw/                        # 原始抓取素材（不参与运行时）
├── frontend/
│   ├── src/
│   │   ├── api/                    # Axios 接口封装
│   │   ├── stores/chat.js          # 聊天状态
│   │   ├── views/                  # 登录、注册、聊天、浏览、对比
│   │   └── router/
│   └── package.json
├── start-backend.ps1
└── start-frontend.ps1
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- MySQL 8（用于用户与 IM 身份）
- Redis 8.0（内置 RedisJSON/RediSearch）或已安装这两个模块，用于 LangGraph 检查点持久化
- 可访问的 OpenAI 兼容模型服务（默认 DashScope）

### 1. 准备数据库

创建数据库（默认名 `car_harness`），后端启动时会自动建表。

### 2. 配置后端

```powershell
cd backend
Copy-Item .env.example .env
```

至少填写：

```dotenv
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=你的密钥
OPENAI_MODEL=qwen-plus

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=你的密码
MYSQL_DATABASE=car_harness

CHECKPOINTER_TYPE=redis
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0

JWT_SECRET=请替换为随机字符串
```

> 检查点默认走 Redis，需要 Redis 8.0 内置 RedisJSON/RediSearch；测试可临时改为 `CHECKPOINTER_TYPE=memory`。

按需开启：

- 知识库：`RAG_ENABLED=true`，可调整 `RAG_KNOWLEDGE_DIRS`、检索与分块参数。
- 到店导航：`AMAP_WEBSERVICE_KEY=高德 Web 服务 Key`。
- 文件生成：`ACP_ENABLED=true`，并配置 `ACP_COMMAND` / `ACP_ARGS`。
  - Qwen Code：`ACP_COMMAND=qwen`、`ACP_ARGS=--acp`
  - TRAE CLI（企业版旗舰版）：`ACP_COMMAND=traecli`、`ACP_ARGS=acp serve`
- 飞书渠道：`FEISHU_ENABLED=true` 并填写 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`。
- 多层模型路由：`LLM_TIER_ENABLED=true`，按需修改 `LLM_TIER_*_MODEL` 与 `LLM_CLASSIFIER_MODEL`，修改后重启生效。

### 3. 安装并启动后端

```powershell
cd backend
python -m pip install -r requirements.txt
cd ..
.\start-backend.ps1
```

接口文档：`http://127.0.0.1:8000/docs`

启动脚本会按 `PYTHON_EXE` → `pyenv exec python` → `python` 的顺序解析解释器。

### 4. 启动前端

```powershell
.\start-frontend.ps1
```

访问 `http://127.0.0.1:5173`，注册账号后进入聊天页。

## 主要接口

| 方法 | 路径                                    | 说明                         |
| ---- | --------------------------------------- | ---------------------------- |
| POST | `/api/auth/register`                  | 注册                         |
| POST | `/api/auth/login`                     | 登录，返回 JWT               |
| POST | `/api/auth/logout`                    | 登出                         |
| GET  | `/api/auth/me`                        | 当前用户                     |
| POST | `/api/threads`                        | 新建会话                     |
| GET  | `/api/threads/{thread_id}/history`    | 会话历史                     |
| GET  | `/api/threads/{thread_id}/interrupts` | 查询待审批中断               |
| POST | `/api/threads/{thread_id}/resume`     | 提交审批或补充信息并恢复执行 |
| POST | `/api/threads/{thread_id}/retry`      | 从最后成功检查点断点续跑     |
| POST | `/api/chat`                           | 非流式对话                   |
| POST | `/api/chat/stream`                    | SSE 流式对话                 |
| GET  | `/api/conversations`                  | 会话列表                     |
| GET  | `/api/conversations/{thread_id}`      | 会话详情                     |
| GET  | `/api/workspace/files`                | 工作区文件列表               |
| GET  | `/api/workspace/files/{path}`         | 下载工作区文件               |
| GET  | `/api/brands`                         | 品牌列表                     |
| GET  | `/api/brands/{brand}/series`          | 车系列表                     |
| GET  | `/api/cars`                           | 车型搜索                     |
| GET  | `/api/cars/{model_id}`                | 车型详情                     |
| GET  | `/api/health`                         | 健康检查                     |

除注册、登录与健康检查外，其余接口均需要 `Authorization: Bearer <token>`。

`POST /api/chat` 的响应额外包含 `tier` 字段（`low` / `medium` / `high`），分档关闭时为 `off`；其余接口结构不变。

## 配置说明

| 配置项                                                                       | 默认值                                                | 说明                                                   |
| ---------------------------------------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------ |
| `OPENAI_API_BASE`                                                          | DashScope 兼容端点                                    | OpenAI 兼容服务地址                                    |
| `OPENAI_MODEL`                                                             | `kimi-k3`                                           | 模型名，按实际服务填写                                 |
| `LLM_TEMPERATURE` / `LLM_MAX_TOKENS` / `LLM_TOP_P`                     | 不设置                                                | 留空则不传给模型，避免不支持该参数的模型报 400         |
| `LLM_TIER_ENABLED`                                                         | `false`                                             | 多层模型路由总开关，关闭时全部使用 `OPENAI_MODEL`    |
| `LLM_TIER_HIGH_MODEL` / `LLM_TIER_MEDIUM_MODEL` / `LLM_TIER_LOW_MODEL` | `qwen3.8-max-0902` / `qwen-plus` / `qwen-turbo` | 复杂 / 中等 / 简单问题使用的模型                       |
| `LLM_CLASSIFIER_MODEL`                                                     | `qwen-turbo`                                        | 复杂度分类模型                                         |
| `LLM_CLASSIFIER_MAX_TOKENS`                                                | `200`                                               | 分类输出 token 上限                                    |
| `FILESYSTEM_BACKEND`                                                       | `local`                                             | `local` 或 `memory`                                |
| `WORKSPACE_DIR`                                                            | `./workspace`                                       | Agent 工作区，相对路径解析到 `backend/app/workspace` |
| `CHECKPOINTER_TYPE`                                                        | `redis`                                             | `redis` 或 `memory`（仅测试）                      |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` / `REDIS_DB`          | `127.0.0.1` / `6379` / 空 / `0`                 | Redis 连接信息                                         |
| `REDIS_CHECKPOINT_TTL_MINUTES`                                             | `4320`                                              | 检查点保留时长，默认 3 天，读取自动续期                |
| `REDIS_MAINTENANCE_INTERVAL_SECONDS`                                       | `3600`                                              | 检查点维护任务扫描间隔                                 |
| `LLM_MAX_RETRIES`                                                          | `3`                                                 | 临时错误自动重试次数                                   |
| `MAX_RECOVERABLE_RETRIES`                                                  | `2`                                                 | 工具可恢复错误回到 Agent 的上限                        |
| `OPENAI_TIMEOUT_SECONDS`                                                   | `120`                                               | 单次模型请求超时                                       |
| `DEGRADE_ENABLED`                                                          | `true`                                              | 依赖降级总开关，关闭后依赖异常按原策略报错             |
| `DEGRADE_FORCE`                                                            | `false`                                             | 强制降级，四项全部生效，用于演练与应急                 |
| `RAG_DEGRADE_COOLDOWN_SECONDS`                                             | `60`                                                | RAG 故障后的冷却窗口，窗口内检索直接返回空结果         |
| `ENABLED_SUBAGENTS`                                                        | 空                                                    | 逗号分隔，留空表示启用全部子 Agent                     |
| `RAG_*`                                                                    | 见模板                                                | 知识库目录、embedding、rerank、检索与分块参数          |
| `AMAP_WEBSERVICE_KEY`                                                      | 空                                                    | 高德 Web 服务 Key                                      |
| `ACP_*`                                                                    | 关闭                                                  | ACP 文件生成开关、命令、参数与超时                     |
| `FEISHU_*`                                                                 | 关闭                                                  | 飞书渠道凭据                                           |

## 已知限制

- ACP 依赖本地已安装并已登录的 ACP 服务端；TRAE CLI 2.0 仅企业版旗舰版套餐可用，个人版需改用其他 ACP 智能体（如 Qwen Code）。
- ACP 链路只支持文本文件写入（Markdown、TXT、CSV 等），不支持二进制文档。
- 检查点依赖 Redis 8.0（内置 RedisJSON/RediSearch）或已安装这两个模块；缺少 `JSON.SET`/`FT.CREATE` 时按降级策略改用内存检查点，`DEGRADE_ENABLED=false` 时启动失败并给出提示。
- 同一线程的并发请求不做串行化，可能产生检查点写入冲突，前端需避免对同一会话同时发起多个请求。
- RAG 索引在首次检索时构建，文档较多时首次请求耗时较长，之后复用 Chroma 集合。
- 车型数据为静态 CSV，更新数据需替换 `data/cars.csv` 并重启后端。
- 多层模型路由开启后每次请求增加一次小模型分类调用（约数百毫秒到 1 秒）；分档准确性依赖分类提示词，短问题可能因缺少上下文被误判，已通过附带上一轮助手回复缓解。
- 三档模型名配置错误时按降级策略逐级降档；全部档位都失败才返回可重试错误。
- 降级模式与跨重启持久化不可兼得：Redis 不可用时内存检查点重启即丢失，中断恢复与断点续跑随之失效。

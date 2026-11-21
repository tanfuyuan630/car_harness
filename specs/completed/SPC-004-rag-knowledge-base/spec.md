# SPC-004 RAG 知识库模块 Spec

## Why
当前 Agent 只能回答车型参数类结构化问题，无法回答销售制度、采购合同、售后服务条款等非结构化文档内容。`data/docs` 下已有相关业务文档，需要引入 RAG 能力，把文档转化为可检索知识，供 Agent 引用作答。

## What Changes
- 新增 `backend/app/rag/` 模块：文档加载与格式归一化、分块、向量化、Chroma 持久化、检索与重排
- 使用 LlamaIndex 完成加载、分块、向量化
- 向量数据库使用 Chroma，本地持久化
- 文档来源为 `data/docs`（`.doc` / `.docx`）
- embedding 模型使用 `qwen3.7-text-embedding-flash`，rerank 模型使用 `qwen3.7-text-rerank`
- 重排由独立开关 `RAG_RERANK_ENABLED` 控制，默认开启，关闭时跳过重排直接返回召回/融合结果
- 新增 Agent 工具 `search_knowledge_base` 并注册到 Harness
- 可选 BM25 混合检索（向量 + BM25，RRF 融合），开关 `RAG_HYBRID_ENABLED`，默认关闭
- 可选查询改写（LLM 生成多个查询变体并融合），开关 `RAG_QUERY_REWRITE_ENABLED`，默认关闭
- 更新系统提示，引导 Agent 对制度、合同、售后条款类问题使用知识库
- `requirements.txt` 增加 Chroma、LlamaIndex 嵌入/重排/向量库集成等依赖

## Impact
- Affected specs: SPC-001（工具注册与可插拔扩展）、SPC-004
- Affected code:
  - 新增 `backend/app/rag/`（文档加载、embedding、rerank、服务）
  - 新增 `backend/app/agent/tools/rag_tools.py`
  - 修改 `backend/app/core/config.py`、`backend/app/agent/registry.py`
  - 修改 `backend/app/agent/prompts/system_prompt.md`
  - 修改 `backend/requirements.txt`、`backend/.env.example`

## ADDED Requirements

### Requirement: 文档加载与格式归一化
系统 SHALL 从 `DATA_DIR/docs` 读取全部 `.doc` / `.docx` 文档，并交给 LlamaIndex 解析。

- 按文件头魔数识别真实格式（项目中存在后缀为 `.doc`、实际为 docx（ZIP）的文件）
- 旧版二进制 `.doc`（OLE2）通过 Word COM 转换为 `.docx` 并缓存，源文件更新时间变化时重新转换
- 使用 LlamaIndex `SimpleDirectoryReader` + `DocxReader` 加载
- 每个 Document 的 metadata 保留原始文件名与原始路径

#### Scenario: 加载混合格式文档
- **WHEN** 执行索引构建
- **THEN** `data/docs` 下 5 个文档全部解析为 Document，metadata 中的文件名与原始文件名一致

#### Scenario: 源文档更新后重建
- **WHEN** 源 `.doc` 修改后调用重建索引
- **THEN** 缓存转换结果因 mtime 变化被刷新，索引包含新内容

### Requirement: 分块与向量化
系统 SHALL 使用 LlamaIndex `SentenceSplitter` 分块，并将分块结果向量化后写入 Chroma。

- 采用中文标点感知断句：按 `。！？；` 与换行切分句子，再按配置的 `chunk_size` 合并、保留 `chunk_overlap` 上下文
- 分块大小与重叠长度通过配置项指定（默认 512 token / 64 overlap）
- embedding 通过 OpenAI 兼容 `/embeddings` 端点调用，模型为 `qwen3.7-text-embedding-flash`，输出 1024 维向量
- Chroma 使用本地持久化目录与配置化集合名，向量维度 1024，距离度量使用 cosine

#### Scenario: 中文条款文档分块
- **WHEN** 对以"第X条"与中文标点组织的制度文档分块
- **THEN** 每个分块在句子边界处结束，不出现句子中间被截断的情况

#### Scenario: 首次构建索引
- **WHEN** Chroma 集合为空且首次发生检索或显式重建
- **THEN** 自动完成加载、分块、向量化并写入 Chroma

#### Scenario: 重复启动
- **WHEN** 集合已存在且非空时再次启动或查询
- **THEN** 不重复构建索引，直接复用已有向量

### Requirement: 检索与重排
系统 SHALL 先召回候选片段（默认向量召回），再使用 `qwen3.7-text-rerank` 重排后返回。

- 召回数量与重排保留数量均可配置
- 返回内容包含片段文本、来源文件名、相关性分数
- 重排由 `RAG_RERANK_ENABLED` 开关控制，默认开启；关闭时直接返回召回或融合结果

#### Scenario: 制度类问题检索
- **WHEN** 查询"4S店销售顾问的接待流程要求"
- **THEN** 返回来自销售管理制度文档的相关片段，重排后首条相关性最高

#### Scenario: 关闭重排
- **WHEN** 配置 `RAG_RERANK_ENABLED=false`
- **THEN** 直接返回向量召回结果，不调用重排模型

### Requirement: 可选混合检索与查询改写
系统 SHALL 通过独立开关提供 BM25 混合检索与查询改写能力，两个开关默认关闭。

- `RAG_HYBRID_ENABLED=true` 时，同时使用向量检索器与 BM25 检索器，通过 LlamaIndex `QueryFusionRetriever` 以 RRF（reciprocal rank）融合
- BM25 基于索引节点构建，中文采用字符级切分，避免中文长串被当作单一词元
- `RAG_QUERY_REWRITE_ENABLED=true` 时，使用与对话模型相同的 OpenAI 兼容端点生成查询变体，并把原查询与变体一起参与融合
- 两个开关均关闭时，走纯向量检索，不产生额外 LLM 调用
- 融合结果再经过重排（若重排开启）

#### Scenario: 开启 BM25 混合检索
- **WHEN** 配置 `RAG_HYBRID_ENABLED=true` 并查询含精确术语的问题
- **THEN** 向量与 BM25 结果经 RRF 融合后返回，精确术语命中的片段不会因向量相似度低而丢失

#### Scenario: 开启查询改写
- **WHEN** 配置 `RAG_QUERY_REWRITE_ENABLED=true` 且用户查询较口语化
- **THEN** 系统生成与原查询等价的书面化查询变体，并融合各变体的检索结果

#### Scenario: 默认关闭
- **WHEN** 两个开关均保持默认值 false
- **THEN** 检索只走向量召回，不构建 BM25 索引、不调用查询改写

### Requirement: Agent 工具集成
系统 SHALL 提供 Agent 工具 `search_knowledge_base`，使 Agent 能检索业务文档。

- 工具入参：`query`，可选 `top_k`
- 工具输出：JSON 片段列表（content / source / score）
- 工具注册到 Harness 工具注册中心；`RAG_ENABLED=false` 时不注册
- 系统提示增加知识库使用指引

#### Scenario: Agent 回答制度/合同问题
- **WHEN** 用户询问采购合同、售后条款或销售制度
- **THEN** Agent 调用 `search_knowledge_base`，并基于返回片段作答，不臆造条款

## Assumptions
- embedding 复用现有 `OPENAI_API_BASE`（DashScope 兼容模式）的 `/embeddings` 端点与 `OPENAI_API_KEY`（已实测可用）
- rerank 走 DashScope 原生 text-rerank 接口，同样复用 `OPENAI_API_KEY`（已实测可用）
- 查询改写的 LLM 复用同一 OpenAI 兼容端点与模型配置，仅在开关开启时调用
- 运行环境为 Windows 且安装了 Microsoft Word，用于旧版 `.doc` 转换（当前环境 Word 16.0 可用）
- 文档规模为 5 个 KB 级文件，启动后按需构建即可，不引入任务队列

## Non-Goals
- 不新增 RAG HTTP 接口，仅通过 Agent 工具使用
- 不做图片、扫描件 OCR
- 不做文档级增量更新（重建即全量）
- 不做查询改写结果的缓存与持久化

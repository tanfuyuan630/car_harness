# SPC-004 RAG 知识库模块 - 实施计划

## Task 1: 配置与依赖
- [x] 完成 RAG 配置项与依赖声明
  - Status: completed
  - Priority: high
  - Depends On: None
  - Description:
    - `backend/app/core/config.py` 增加配置：`RAG_ENABLED`、`RAG_DOCS_DIR`、`RAG_CHROMA_DIR`、`RAG_COLLECTION`、`RAG_EMBEDDING_MODEL`、`RAG_RERANK_MODEL`、`RAG_RERANK_ENABLED`（默认 true）、`RAG_RETRIEVE_TOP_K`、`RAG_RERANK_TOP_N`、`RAG_CHUNK_SIZE`、`RAG_CHUNK_OVERLAP`、`RAG_CACHE_DIR`、`RAG_HYBRID_ENABLED`（默认 false）、`RAG_QUERY_REWRITE_ENABLED`（默认 false）、`RAG_REWRITE_NUM_QUERIES`
    - 增加路径属性：文档目录、Chroma 持久化目录、doc 转换缓存目录（目录按需创建）
    - `backend/requirements.txt` 增加：`chromadb`、`llama-index-vector-stores-chroma`、`llama-index-embeddings-openai-like`、`llama-index-postprocessor-dashscope-rerank`、`llama-index-retrievers-bm25`、`llama-index-llms-openai`、`pywin32`（Windows）
    - `backend/.env.example` 补充 RAG 配置项与默认值说明
  - Acceptance Criteria Addressed: spec 中"分块与向量化""检索与重排"的配置化要求
  - Test Requirements:
    - `rule` TR-1.1: 配置项均有合理默认值，导入 `settings` 不报错
    - `rule` TR-1.2: 路径属性返回绝对路径且父目录可自动创建

## Task 2: 文档加载与格式归一化
- [x] 实现 `backend/app/rag/doc_loader.py`
  - Status: completed
  - Priority: high
  - Depends On: Task 1
  - Description:
    - 按魔数识别文件真实格式：`D0CF11E0` 为旧版 doc（OLE2），`504B0304` 为 docx（ZIP）
    - 旧版 `.doc` 使用 Word COM 转换为 `.docx`，写入配置的缓存目录；缓存文件 mtime 不早于源文件时复用
    - 统一产出 `.docx` 文件，交给 LlamaIndex `SimpleDirectoryReader` + `DocxReader` 加载
    - 加载后把 metadata 中的文件名/来源还原为原始文件名与原始路径
  - Acceptance Criteria Addressed: spec 中"文档加载与格式归一化"全部场景
  - Test Requirements:
    - `rule` TR-2.1: `data/docs` 下 5 个文件均可解析出非空文本
    - `rule` TR-2.2: 后缀为 `.doc` 但实为 docx 的文件无需 Word 转换即可解析
    - `rule` TR-2.3: 源文件更新后再次加载会刷新缓存

## Task 3: Embedding 与 Rerank 组件
- [x] 实现 `backend/app/rag/embeddings.py` 与 `backend/app/rag/reranker.py`
  - Status: completed
  - Priority: high
  - Depends On: Task 1
  - Description:
    - `embeddings.py`：使用 LlamaIndex `OpenAILikeEmbedding`，`model_name=settings.RAG_EMBEDDING_MODEL`，`api_base=OPENAI_API_BASE`，`api_key=OPENAI_API_KEY`
    - `reranker.py`：使用 `DashScopeRerank`，`model=settings.RAG_RERANK_MODEL`，`top_n=settings.RAG_RERANK_TOP_N`，api_key 复用 `OPENAI_API_KEY`
    - 两个工厂函数均做单例缓存，避免重复创建客户端
  - Acceptance Criteria Addressed: spec 中"分块与向量化""检索与重排"的模型要求
  - Test Requirements:
    - `rule` TR-3.1: 调用 embedding 返回 1024 维向量
    - `rule` TR-3.2: 调用 reranker 能按 relevance_score 重排并截断到 top_n

## Task 4: RAG 服务（索引构建、Chroma 持久化、检索）
- [x] 实现 `backend/app/rag/service.py`
  - Status: completed
  - Priority: high
  - Depends On: Task 2, Task 3
  - Description:
    - 使用 LlamaIndex `IngestionPipeline` + `SentenceSplitter` 分块；`chunking_tokenizer_fn` 采用中文标点断句（按 `。！？；` 与换行切句），再按 `chunk_size` 合并、保留 `chunk_overlap`
    - `ChromaVectorStore` 指向配置的持久化目录与集合名，集合使用 cosine 距离
    - `ensure_index()`：集合为空时构建，非空时复用；用锁保证并发安全
    - `rebuild()`：清空集合后全量重建，返回文档数与分块数
    - 缓存索引节点（构建产物或从 Chroma 恢复），供 BM25 与检索复用
    - `retrieve(query, top_k)`：按开关组合向量检索器、BM25 检索器与查询改写，融合结果经 reranker 重排后返回片段（content/source/score）
  - Acceptance Criteria Addressed: spec 中"分块与向量化""检索与重排"及两个 Scenario
  - Test Requirements:
    - `rule` TR-4.1: 首次调用后 Chroma 目录生成且集合计数大于 0
    - `rule` TR-4.2: 第二次调用不重新写入向量
    - `rule` TR-4.3: 检索结果包含来源文件名，重排开启时片段数不超过 `RAG_RERANK_TOP_N`

## Task 5: 可选混合检索与查询改写
- [x] 在 `backend/app/rag/service.py` 中实现混合检索与查询改写
  - Status: completed
  - Priority: high
  - Depends On: Task 4
  - Description:
    - `RAG_HYBRID_ENABLED=true`：用索引节点构建 `BM25Retriever`（中文使用字符级 token_pattern、跳过词干），与向量检索器一起交给 `QueryFusionRetriever`，融合模式为 `reciprocal_rerank`
    - `RAG_QUERY_REWRITE_ENABLED=true`：用 `llama_index.llms.openai.OpenAI` 调用现有模型配置，按中文 prompt 生成 `RAG_REWRITE_NUM_QUERIES - 1` 个查询变体；`QueryFusionRetriever` 的 `num_queries` 相应设置
    - 两个开关均关闭时不构建 BM25、不调用 LLM，保持纯向量检索
    - 融合结果在开启重排时继续走 `qwen3.7-text-rerank`
  - Acceptance Criteria Addressed: spec 中"可选混合检索与查询改写"全部 Scenario
  - Test Requirements:
    - `rule` TR-5.1: 默认关闭时 `retrieve` 不创建 BM25 检索器、不调用改写 LLM
    - `rule` TR-5.2: 开启混合检索后，精确术语查询可返回 BM25 命中的片段
    - `rule` TR-5.3: 开启查询改写后，融合结果包含查询变体召回的片段

## Task 6: Agent 工具与提示词集成
- [x] 新增 `backend/app/agent/tools/rag_tools.py` 并接入注册中心
  - Status: completed
  - Priority: high
  - Depends On: Task 5
  - Description:
    - 定义 `search_knowledge_base` 工具：入参 `query`、`top_k`，返回 JSON 字符串（content/source/score）
    - `registry.tools` 在 `RAG_ENABLED=true` 时追加该工具
    - `backend/app/agent/prompts/system_prompt.md` 增加知识库使用指引（制度/合同/售后条款类问题必须先检索）
  - Acceptance Criteria Addressed: spec 中"Agent 工具集成"及其 Scenario
  - Test Requirements:
    - `rule` TR-6.1: `RAG_ENABLED=true` 时工具出现在 Agent 工具列表中
    - `rule` TR-6.2: `RAG_ENABLED=false` 时工具不注册

## Task 7: 端到端验证
- [x] 完成索引构建、检索与 Agent 工具验证
  - Status: completed
  - Priority: high
  - Depends On: Task 6
  - Description:
    - 构建索引并核对 5 个文档、分块数、向量数
    - 用制度类、合同类、售后条款类问题各检索一次，核对来源与内容相关性
    - 分别开启混合检索、查询改写各验证一次，确认开关生效且可关闭
    - 验证重复启动不重复构建、重建索引可全量刷新
    - 启动后端，通过 Agent 对话验证 `search_knowledge_base` 被调用
  - Acceptance Criteria Addressed: spec 全部 Scenario
  - Test Requirements:
    - `rule` TR-7.1: 索引统计与文档内容一致
    - `rule` TR-7.2: 三类问题的 Top 片段来源正确
    - `rule` TR-7.3: 混合检索与查询改写开关行为符合预期
    - `rule` TR-7.4: Agent 工具链路可用

# Task Dependencies
- Task 2、Task 3 依赖 Task 1
- Task 4 依赖 Task 2、Task 3
- Task 5 依赖 Task 4
- Task 6 依赖 Task 5
- Task 7 依赖 Task 6

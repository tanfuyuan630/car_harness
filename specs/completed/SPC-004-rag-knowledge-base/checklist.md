# SPC-004 RAG 知识库模块 - 验收清单

- [x] `config.py` 新增全部 RAG 配置项，`.env.example` 同步，导入 `settings` 正常
- [x] `requirements.txt` 包含 chromadb、llama-index-vector-stores-chroma、llama-index-embeddings-openai-like、llama-index-postprocessor-dashscope-rerank、llama-index-retrievers-bm25、llama-index-llms-openai、pywin32
- [x] `data/docs` 下 `.doc` 与 `.docx` 均能被解析，后缀为 `.doc` 实为 docx 的文件被正确识别
- [x] 旧版 `.doc` 经 Word COM 转换后解析，源文件更新会刷新缓存
- [x] 分块使用 LlamaIndex `SentenceSplitter` + 中文标点断句函数，句子边界不被截断，参数来自配置
- [x] 向量化使用 `qwen3.7-text-embedding-flash`，输出 1024 维向量，写入配置的 Chroma 持久化目录
- [x] 检索先召回，再使用 `qwen3.7-text-rerank` 重排；`RAG_RERANK_ENABLED` 默认开启，关闭时跳过重排
- [x] `RAG_HYBRID_ENABLED` 默认 false；开启后向量与 BM25 结果经 RRF 融合，中文 BM25 使用字符级切分
- [x] `RAG_QUERY_REWRITE_ENABLED` 默认 false；开启后由 LLM 生成查询变体并融合，关闭时不调用 LLM
- [x] 两个开关均关闭时走纯向量检索，无额外 BM25 构建与改写调用
- [x] 重复启动或重复查询不重复构建索引
- [x] `search_knowledge_base` 工具已注册，`RAG_ENABLED=false` 时不注册
- [x] 系统提示包含知识库使用指引
- [x] 制度、合同、售后条款三类问题的检索结果来源正确
- [x] 代码注释为中文 UTF-8，无 emoji，未引入无关依赖

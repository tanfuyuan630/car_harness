# Tasks

- [x] Task 1: 领域定义与配置
  - [x] SubTask 1.1: 新增 `backend/app/rag/domains.py`，集中定义领域常量与中文名、目录到领域的映射（`docs/sales`、`docs/after_sales`、`docs/repair`、`docs/accessories`、`insurance/policy`、`insurance/claims`）、`docs` 根目录文件名到领域的映射（5 个 `doc`/`docx`）
  - [x] SubTask 1.2: `backend/app/core/config.py` 新增 `RAG_KNOWLEDGE_DIRS`（默认 `docs,insurance`），移除 `RAG_DOCS_DIR`；`RAG_COLLECTION` 默认改为 `car_knowledge`；提供解析后的知识库根目录列表属性
  - [x] SubTask 1.3: `backend/.env.example` 同步知识库目录与集合名配置说明

- [x] Task 2: 知识库文档加载改造
  - [x] SubTask 2.1: `backend/app/rag/doc_loader.py` 改为按 `RAG_KNOWLEDGE_DIRS` 递归扫描 `.md`、`.doc`、`.docx`
  - [x] SubTask 2.2: 按 `domains.py` 规则判定每篇文档的领域；未命中映射的文件跳过并记录日志
  - [x] SubTask 2.3: 旧版 `.doc` 转换缓存路径按领域分目录（`{cache_dir}/{domain}/{stem}.docx`），避免不同目录同名文件互相覆盖
  - [x] SubTask 2.4: `Document.metadata` 写入 `domain`、`file_name`、`source`、`file_type`；`.md` 直接读取文本构造单个 Document，转换缓存的 `docx` 使用 `DocxReader`

- [x] Task 3: 按领域隔离检索
  - [x] SubTask 3.1: `backend/app/rag/service.py` 的 `retrieve` 增加可选 `domain` 参数，非空时对向量召回施加 Chroma metadata 过滤
  - [x] SubTask 3.2: 开启混合检索时，按 `domain` 惰性构建并缓存独立 `BM25Retriever`，领域内无分块时返回空结果
  - [x] SubTask 3.3: 确认索引构建时每个分块携带 `domain` 元数据；`rebuild()` 同步清理按域 BM25 缓存

- [x] Task 4: 领域检索工具工厂
  - [x] SubTask 4.1: `backend/app/agent/tools/rag_tools.py` 增加 `build_domain_knowledge_tool(domain)`，用 `StructuredTool.from_function` 构造固定领域的检索工具，描述包含领域中文名，不暴露 `domain` 参数
  - [x] SubTask 4.2: 移除全局 `search_knowledge_base` 工具与 `get_rag_tools()`，改由子 Agent 注册时按领域构造

- [x] Task 5: 子 Agent 提示词
  - [x] SubTask 5.1: 新增 `insurance_underwriting_agent.md`、`insurance_claims_agent.md`、`vehicle_sales_agent.md`、`after_sales_agent.md`、`repair_beauty_agent.md`、`car_accessories_agent.md`，统一包含领域职责、先检索后回答、引用来源文件名、超出本域即说明；承保与理赔提示词互相写明边界排除项
  - [x] SubTask 5.2: 新增 `car_model_agent.md`，合并原对比与推荐职责并覆盖参数查询；删除 `compare_agent.md`、`recommend_agent.md`

- [x] Task 6: 子 Agent 注册
  - [x] SubTask 6.1: `backend/app/agent/registry.py` 用声明式领域表注册 `insurance_underwriting_expert`、`insurance_claims_expert`、`vehicle_sales_expert`、`after_sales_expert`、`repair_beauty_expert`、`car_accessories_expert`，每个绑定本域检索工具；`description` 写入领域名称、典型业务关键词与边界排除项，作为 `task` 工具的路由清单
  - [x] SubTask 6.2: 注册 `car_model_expert`，工具为 `search_cars`、`get_car_detail`、`list_brands`、`list_series`、`compare_cars`、`recommend_cars`；移除 `compare_expert`、`recommend_expert`
  - [x] SubTask 6.3: 沿用 `ENABLED_SUBAGENTS` 名称过滤；`RAG_ENABLED=false` 时跳过 6 个领域子 Agent，仅注册车型专家

- [x] Task 7: 主 Agent 调度化
  - [x] SubTask 7.1: 重写 `backend/app/agent/prompts/system_prompt.md`：定义七类领域的委派规则、跨领域拆分顺序、同一轮多次 `task` 并行委派、车型问题一律委派 `car_model_expert`、汇总与资料缺失要求、寒暄直答、禁止自行回答领域问题
  - [x] SubTask 7.2: 主 Agent 工具通过 `registry.tools` 收敛为文件系统工具，`harness.py` 继续追加 `final_recommendation_tool` 并保留 `interrupt_on` 审批配置；车型工具与知识库工具已从主 Agent 移除

- [x] Task 8: 联调验证
  - [x] SubTask 8.1: 重建索引成功，加载 13 个文档、332 个分块；领域分布 sales 3、after_sales 3、underwriting 3、repair 2、claims 1、accessories 1，未映射文件跳过且无报错
  - [x] SubTask 8.2: 六类领域典型问题路由全部命中对应子 Agent（承保、理赔、销售、售后、维修美容、用品交易），检索来源文件名均限于本域
  - [x] SubTask 8.3: "新车投保后出事故如何理赔"正确拆分并委派承保与理赔两个子 Agent 后汇总；车型参数、对比与推荐均委派 `car_model_expert`，推荐前触发 `final_recommendation_tool` 审批中断
  - [x] SubTask 8.4: `RAG_ENABLED=false` 时只注册 `car_model_expert`；`ENABLED_SUBAGENTS=vehicle_sales_expert,car_model_expert` 时只注册两个指定子 Agent
  - [x] SubTask 8.5: 以 8123 端口启动后端实测流式接口，收到 229 个 token 事件、done 正常、无 error，对话 Markdown 记录正常生成；验证后已清理测试用户与对话文件

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 2
- Task 4 depends on Task 3
- Task 6 depends on Task 4, Task 5
- Task 7 depends on Task 6
- Task 8 depends on Task 1, Task 2, Task 3, Task 4, Task 5, Task 6, Task 7

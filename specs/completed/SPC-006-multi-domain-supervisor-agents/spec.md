# SPC-006 多领域主管-专家 Agent 改造 Spec

## Why
`data/docs` 与 `data/insurance` 下已补充保险承保、保险理赔、汽车销售、汽车售后、汽车维修美容、汽车用品交易六类业务文档，但当前 Agent 仍是"单主 Agent 承担全部问答"的结构：知识库只有一个统一集合、一个检索工具，不同领域文档混在一起，检索会跨域召回；主提示词同时承担销售顾问、条款检索、车型推荐等多种职责，领域边界不清。需要改造成"主 Agent 负责分发、领域子 Agent 负责执行"的主管-专家结构，让每个业务域有独立的职责、提示词与知识检索范围。

## What Changes
- 主 Agent 改为调度者：只做意图识别、任务拆分、委派与结果汇总，不再直接持有车型工具和知识库检索工具
- 新增 6 个领域子 Agent：保险承保、保险理赔、汽车销售、汽车售后、汽车维修美容、汽车用品交易
- 新增 1 个车型专家子 Agent `car_model_expert`，聚合车型查询、参数详情、对比、推荐能力；移除原 `compare_expert`、`recommend_expert`
- RAG 改造：文档加载支持递归目录与 `.md`；每篇文档写入 `domain` 元数据；检索支持按 `domain` 过滤
- 每个领域子 Agent 绑定一个只召回本域文档的检索工具，工具不暴露 `domain` 参数，避免越域
- 新增 7 个子 Agent 提示词文件，删除原对比/推荐提示词文件
- Chroma 集合名改为 `car_knowledge`，首次构建时全量写入领域元数据
- 新增配置 `RAG_KNOWLEDGE_DIRS`，替代原 `RAG_DOCS_DIR`
- 无新增第三方依赖，无 HTTP 接口变更，前端无需改动

## 知识域与文档映射

| 领域 | domain | 子 Agent | 文档来源 |
|------|--------|----------|----------|
| 保险承保 | `underwriting` | `insurance_underwriting_expert` | `data/insurance/policy/` 下全部 `.md` |
| 保险理赔 | `claims` | `insurance_claims_expert` | `data/insurance/claims/` 下全部 `.md` |
| 汽车销售 | `sales` | `vehicle_sales_expert` | `data/docs/sales/` 下全部 `.md`，以及 `data/docs/` 根目录的 `完整-汽车4S店销售管理制度.doc`、`汽车4S店销售部制度(执行版)-2.doc` |
| 汽车售后 | `after_sales` | `after_sales_expert` | `data/docs/after_sales/` 下全部 `.md`，以及 `data/docs/` 根目录的 `汽车采购售后服务方案.doc`、`车辆采购质量保证及售后服务条款.doc` |
| 汽车维修美容 | `repair` | `repair_beauty_expert` | `data/docs/repair/` 下全部 `.md`，以及 `data/docs/` 根目录的 `汽车定点维修服务采购合同.docx` |
| 汽车用品交易 | `accessories` | `car_accessories_expert` | `data/docs/accessories/` 下全部 `.md` |
| 车型数据 | 无（不接知识库） | `car_model_expert` | `data/cars.csv`，通过现有车型工具访问 |

### 文档现状

- 六类文档均已就位，目录与领域一一对应：
  - `data/insurance/policy/`：车险承保资料汇编、车险报价与出单操作手册、车险责任与条款速查
  - `data/insurance/claims/`：车险理赔操作手册与条款
  - `data/docs/sales/`：汽车销售操作手册
  - `data/docs/after_sales/`：汽车售后服务操作手册
  - `data/docs/repair/`：汽车维修美容服务操作手册
  - `data/docs/accessories/`：汽车用品交易操作手册
- `data/docs` 根目录 5 个 `.doc`/`.docx` 按文件名显式映射到销售、售后、维修三个领域
- 代码只按目录/文件名归属领域，不对文档内容做判别或兜底；新增文档放入对应目录后重建索引即可生效

## Impact
- Affected specs: SPC-001（Agent Harness 编排与子智能体注册）、SPC-004（RAG 知识库）
- Affected code:
  - 新增 `backend/app/rag/domains.py`（领域定义、目录与文件映射）
  - 修改 `backend/app/rag/doc_loader.py`（递归扫描、`.md` 支持、领域元数据、按域缓存）
  - 修改 `backend/app/rag/service.py`（领域过滤检索、按域 BM25 索引）
  - 修改 `backend/app/agent/tools/rag_tools.py`（领域检索工具工厂）
  - 修改 `backend/app/agent/registry.py`（声明式注册 7 个子 Agent）
  - 修改 `backend/app/agent/prompts/system_prompt.md`（改为调度规则）
  - 新增 7 个领域/车型子 Agent 提示词，删除 `compare_agent.md`、`recommend_agent.md`
  - 修改 `backend/app/core/config.py`、`backend/.env.example`
- 不改动：`backend/app/main.py`、`backend/app/channels/handler.py`、前端代码

## ADDED Requirements

### Requirement: 主管 Agent 调度
主 Agent SHALL 只承担意图识别、任务拆分、委派与汇总，不直接回答业务领域问题。

- 主 Agent 不再持有车型工具与知识库检索工具
- 主 Agent 保留通用能力：文件系统工具 `list_files` / `read_file` / `write_file`、最终推荐审批工具 `final_recommendation_tool`（用于人机协同中断），以及 deepagents 内置的 `task` 委派能力
- 领域判定规则写入主提示词，覆盖承保、理赔、销售、售后、维修美容、用品交易、车型数据七类
- 单一领域问题委派给对应子 Agent；跨领域问题拆分为多个子任务，分别委派后按业务顺序汇总
- 汇总时保留子 Agent 给出的文档来源与真实数据，不二次改写；子 Agent 无检索结果时如实说明资料缺失，不臆造条款
- 与业务无关的寒暄、能力询问由主 Agent 直接回复，不委派

#### Scenario: 单一领域问题
- **WHEN** 用户询问"车损险的赔偿范围包括哪些"
- **THEN** 主 Agent 委派 `insurance_underwriting_expert`，并汇总其基于承保条款文档的回答

#### Scenario: 跨领域复合问题
- **WHEN** 用户询问"新车投保后出事故，理赔要准备哪些材料"
- **THEN** 主 Agent 拆分为承保与理赔两个子任务，分别委派后汇总，回答中区分承保规则与理赔材料

#### Scenario: 会话寒暄
- **WHEN** 用户发送"你好，你能做什么"
- **THEN** 主 Agent 直接介绍可提供的业务领域，不调用任何子 Agent

#### Scenario: 资料缺失
- **WHEN** 用户咨询汽车用品交易，但对应领域文档检索无结果
- **THEN** 子 Agent 与主 Agent 均如实说明暂无相关资料，不编造内容

### Requirement: 意图识别与路由机制
系统 SHALL 使用 deepagents 原生 `task` 工具完成意图识别与子 Agent 选择，不引入独立分类模型、关键词规则或正则分流。

- 路由载体：主 Agent 通过 function calling 调用 `task(subagent_type, description)`，`subagent_type` 的候选值来自已注册子 Agent 列表，`description` 为主 Agent 写给子 Agent 的子任务说明
- 候选集即路由清单：每个子 Agent 的 `description` 同时作为 `task` 工具描述中的可选项，必须写明领域名称、典型业务关键词、边界排除项（例如承保写明"不含理赔报案与定损"、理赔写明"不含投保报价与核保"）
- 子任务说明要求：主 Agent 传入的 `description` 需包含用户原始问题、必要的上下文信息与期望输出，不做过度概括
- 主提示词定义判定规则：领域判定优先级、跨领域拆分顺序、同一轮内多次 `task` 调用并行委派、车型类问题一律委派 `car_model_expert`、寒暄与能力询问直接回复
- 强制约束：主 Agent 不持有车型工具与知识库工具，无法绕过 `task` 直接作答；`subagent_type` 不在注册表时 deepagents 返回允许列表，主 Agent 必须重新选择
- 可观测性：`task` 入参与子 Agent 执行链完整出现在 LangSmith trace 中，可按问题集核对实际路由结果
- 验收方式：用覆盖六类领域与车型数据的固定问题集检查 `subagent_type` 命中；未命中时通过完善子 Agent `description` 与主提示词修正，不新增规则分流
- 本期不引入独立的意图分类节点与确定性地编排（会多一次 LLM 调用并绕开 deepagents 原生机制），如后续路由命中率不达标再单独立项

#### Scenario: 口语化问题路由
- **WHEN** 用户发送"车被人刮了，怎么走保险"
- **THEN** 主 Agent 选择 `insurance_claims_expert`，而不是承保或维修美容子 Agent

#### Scenario: 多领域并行委派
- **WHEN** 用户询问"新车投保和上牌分别要准备什么"
- **THEN** 主 Agent 在同一轮调用两次 `task`，分别委派承保与销售子 Agent，再汇总

#### Scenario: 路由结果可追溯
- **WHEN** 打开该轮对话的 LangSmith trace
- **THEN** 能看到 `task` 的 `subagent_type` 与 `description`，以及对应子 Agent 的检索调用

### Requirement: 六个业务领域子 Agent
系统 SHALL 为主营业务域各提供一个独立子 Agent，每个子 Agent 只检索本领域文档。

- `insurance_underwriting_expert`：承保规则、交强险与商业险条款责任、费率与报价、出单与核保
- `insurance_claims_expert`：报案受理、查勘立案、定损、人伤审核、理算核赔、拒赔争议
- `vehicle_sales_expert`：客户接待、需求分析、试驾、报价签约、金融分期、交付上牌、二手车置换
- `after_sales_expert`：预约与接待、故障诊断、维修保养作业、备件管理、三包与保修索赔、汽车召回、售后投诉与回访
- `repair_beauty_expert`：洗车服务、漆面护理、内饰护理、贴膜施工、施工安全防护、耗材与化工品管理
- `car_accessories_expert`：汽车用品分类与选购、交易渠道、采购与进货查验、质量认证、销售交易、退换货、价格合同与库存管理
- 每个子 Agent 只持有本域知识检索工具，以及完成回答所需的通用能力；不持有 `task` 工具，不能再向下分发
- 每个子 Agent 的系统提示词包含：领域职责、必须检索后再回答、引用来源文件名、超出本域时明确说明
- 子 Agent 的 `description` 必须互斥且包含典型业务关键词，供主 Agent 与 deepagents `task` 工具路由

#### Scenario: 承保问题路由
- **WHEN** 用户询问"新能源车险的自主定价系数怎么用"
- **THEN** 路由到 `insurance_underwriting_expert`，回答来源限定为 `data/insurance/policy/` 文档

#### Scenario: 理赔问题路由
- **WHEN** 用户询问"事故后多久内必须报案，定损流程是什么"
- **THEN** 路由到 `insurance_claims_expert`，回答来源限定为 `data/insurance/claims/` 文档

#### Scenario: 领域边界
- **WHEN** 用户向销售子 Agent 询问维修保养价格
- **THEN** 销售子 Agent 说明该问题不属于销售域，由主 Agent 重新委派给售后子 Agent

### Requirement: 车型专家子 Agent
系统 SHALL 用单个 `car_model_expert` 承接全部车型数据类问题。

- 工具集：`search_cars`、`get_car_detail`、`list_brands`、`list_series`、`compare_cars`、`recommend_cars`
- 提示词合并原对比与推荐职责，并覆盖车型参数查询
- 原 `compare_expert`、`recommend_expert` 子 Agent 及对应提示词文件删除，能力由 `car_model_expert` 承接
- 车型参数必须来自工具返回的真实数据，对比只呈现客观差异，推荐需说明基于真实数据的理由

#### Scenario: 车型参数查询
- **WHEN** 用户询问"比亚迪宋PLUS DM-i 的轴距和后备厢容积"
- **THEN** 主 Agent 委派 `car_model_expert`，其调用车型工具后回答

#### Scenario: 车型对比与推荐
- **WHEN** 用户询问"预算 20 万，家用 SUV 有什么推荐，顺便对比一下热门两款"
- **THEN** `car_model_expert` 先推荐候选再对比参数，结论均基于工具数据

### Requirement: 知识库文档加载与领域元数据
RAG 文档加载 SHALL 支持多根目录递归扫描并为每篇文档写入领域元数据。

- 扫描根目录由 `RAG_KNOWLEDGE_DIRS` 配置，默认 `docs,insurance`，相对 `DATA_DIR`
- 支持 `.md`、`.doc`、`.docx`；旧版二进制 `.doc` 继续通过 Word COM 转 `.docx` 缓存，缓存路径按领域分目录，避免不同目录同名文件互相覆盖
- 领域判定规则：先按相对目录映射（`docs/sales`、`docs/after_sales`、`docs/repair`、`docs/accessories`、`insurance/policy`、`insurance/claims`），再按 `docs` 根目录文件名显式映射
- 未命中任何映射的文件跳过并记录日志，不参与索引，不交由 LLM 猜测归属
- 每个 Document 的 metadata 至少包含 `file_name`、`source`、`file_type`、`domain`

#### Scenario: 递归加载六类文档
- **WHEN** 执行索引构建
- **THEN** `data/insurance` 与 `data/docs` 下命中文档全部加载，每个分块的 `domain` 为其所属领域

#### Scenario: 未映射文件
- **WHEN** `data/docs` 根目录出现不在映射表中的临时文件
- **THEN** 该文件被跳过并记录一条日志，索引不包含其内容

### Requirement: 按领域隔离检索
系统 SHALL 支持在指定领域内检索，领域外的文档不参与召回。

- 检索接口接受可选 `domain`，为空时保持全库检索（仅供内部诊断使用）
- 指定 `domain` 时，向量召回通过 Chroma metadata 过滤，只返回该领域分块
- 开启 BM25 混合检索时，按 `domain` 惰性构建并缓存独立 BM25 索引，避免跨域词元干扰
- 重排在领域过滤后的候选集上执行，返回内容包含片段文本、来源文件名、相关性分数
- 领域检索工具不暴露 `domain` 参数，领域由工具工厂绑定的固定值决定

#### Scenario: 承保域检索隔离
- **WHEN** `insurance_underwriting_expert` 检索"免责条款"
- **THEN** 只返回 `underwriting` 域片段，不出现理赔或销售域文档

#### Scenario: 领域内无结果
- **WHEN** `accessories` 域没有可用文档内容
- **THEN** 检索返回空列表，不自动扩展到其他领域

### Requirement: 子 Agent 注册与配置
子 Agent SHALL 由声明式领域表统一注册，并沿用现有开关机制。

- 领域表集中定义 `name`、`description`、`prompt`、`domain`、`tools`，新增领域只需增加一条定义与一个提示词文件
- `ENABLED_SUBAGENTS` 非空时按名称过滤子 Agent；为空时注册全部
- `RAG_ENABLED=false` 时不注册 6 个领域子 Agent（缺少知识工具无法履职），`car_model_expert` 正常注册
- 全部子 Agent 使用 `registry.llm` 当前配置的基座模型

#### Scenario: 按开关裁剪子 Agent
- **WHEN** `ENABLED_SUBAGENTS=vehicle_sales_expert,car_model_expert`
- **THEN** 只注册销售与车型两个子 Agent，主 Agent 对其他领域的委派不再存在

#### Scenario: 关闭 RAG
- **WHEN** `RAG_ENABLED=false`
- **THEN** 只注册 `car_model_expert`，主 Agent 不持有知识库工具

### Requirement: 现有入口兼容
改造 SHALL 不改变现有调用入口与持久化行为。

- `/api/chat`、`/api/chat/stream`、`/api/threads/{thread_id}/resume` 与飞书渠道处理逻辑不变
- 流式接口继续只推送主 Agent 的 token 与主图工具事件，子 Agent 中间事件保持过滤
- LangSmith 追踪标签继续传递到子 Agent 调用链
- 对话持久化与摘要记忆逻辑不变

#### Scenario: Web 流式对话
- **WHEN** 用户通过前端流式提问
- **THEN** 前端收到主 Agent 汇总后的连续 token，不出现子 Agent 未汇总的中间文本

#### Scenario: 飞书渠道
- **WHEN** 飞书用户提问业务问题
- **THEN** IM 处理管线调用同一主 Agent，返回汇总后的回复并正常持久化

## Assumptions
- deepagents 的 `subagents` 支持 `name`、`description`、`system_prompt`、`tools` 字典定义，现有实现已在使用
- Chroma 持久化集合支持 metadata 过滤，现有 `llama-index-vector-stores-chroma` 已具备该能力
- 各领域文档规模为 KB 级，按领域过滤后的检索性能足够，不需要额外索引服务
- 旧集合 `car_docs` 不含 `domain` 元数据，本次改用新集合名 `car_knowledge`，不对旧集合做数据迁移
- 六类文档已按目录就位，索引重建后各领域均可检索

## Non-Goals
- 不做前端子 Agent 切换过程的可视化展示
- 不为不同子 Agent 配置不同模型
- 不新增 HTTP 接口或数据库表
- 不修改、纠正或生成业务文档内容
- 不做文档级增量索引，仍以重建方式更新
- 不保留旧的 `compare_expert` / `recommend_expert` 名称兼容

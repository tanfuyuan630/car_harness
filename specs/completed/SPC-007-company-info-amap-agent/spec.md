# Spec: 公司信息 Agent 与高德地图导航集成

## 1. Problem

当前汽车销售助手系统缺少两项能力：

1. **公司信息查询缺失**：用户询问公司基本情况、联系方式、发展历程、入驻品牌等问题时，系统没有对应的知识域和子 Agent 来回答。
2. **到店导航能力缺失**：用户询问"如何到公司""怎么去汽车城""到店路线"等问题时，系统无法提供基于真实地图的路径规划信息。

## 2. Users

- 到店咨询的潜在客户：想了解公司背景、经营品牌、到店路线
- 已购车客户：需要到店办理售后、保养等业务，需要导航信息
- 内部员工：快速检索公司制度、联系方式等信息

## 3. Goals

1. 新增公司信息子 Agent，基于 `data/docs/company_info/company.md` 检索回答公司相关问题。
2. 集成高德地图 Web 服务 API，当用户询问如何到公司时，生成路径规划信息返回给用户。

## 4. Non-Goals

- 不修改现有保险、销售、售后、维修美容、用品、车型等子 Agent 的逻辑。
- 不增加前端地图可视化组件，导航信息以文本形式返回。
- 不实现实时交通路况、ETA 预估等高级功能。
- 不修改 company.md 的内容（文档内容由用户维护）。

## 5. Functional Requirements

### FR-1: 公司信息知识域

- 在 `domains.py` 中新增 `company_info` 知识域，映射目录 `docs/company_info`。
- 该知识域下的所有文档（当前为 `company.md`）纳入 RAG 索引。

### FR-2: 公司信息子 Agent

- 在 `registry.py` 的 `_DOMAIN_SUBAGENTS` 中新增 `company_info_expert` 子 Agent。
- 绑定 `company_info` 领域的知识库检索工具。
- 职责范围：公司基本信息、联系方式、发展历程、入驻品牌、经营数据、企业荣誉等。
- 边界：不涉及具体车型参数（由车型专家负责）、不涉及购车流程（由销售专家负责）。

### FR-3: 公司信息 Agent Prompt

- 新建 `prompts/company_info_agent.md`，定义公司信息专家的角色、职责、工作方式和边界。
- 要求回答前必须检索知识库，不得凭记忆编造。

### FR-4: 主 Agent 路由规则

- 更新 `system_prompt.md`，增加公司信息领域的路由规则：
  - 公司介绍、联系方式、发展历程、入驻品牌、到店路线 → `company_info_expert`

### FR-5: 高德地图工具集

- 新建 `tools/amap_tools.py`，封装高德地图 Web 服务 API 为 LangChain Tools：
  - `amap_geocode`：地址转经纬度（地理编码）
  - `amap_direction_driving`：驾车路径规划
  - `amap_direction_transit`：公交路径规划
  - `amap_direction_walking`：步行路径规划
- 高德 API Key 从环境变量 `AMAP_WEBSERVICE_KEY` 读取。
- 工具调用失败时返回结构化错误信息，不抛出未捕获异常。

### FR-6: 高德工具注册

- 将高德工具注册到 `company_info_expert` 子 Agent 的工具列表中。
- 子 Agent 可根据用户问题选择合适的出行方式进行路径规划。

### FR-7: 配置项

- 在 `config.py` 中新增 `AMAP_API_KEY` 配置项，默认从环境变量 `AMAP_WEBSERVICE_KEY` 读取。
- 在 `.env.example` 中新增高德 API Key 示例配置。

## 6. Non-Functional Requirements

- **可配置性**：高德 API Key 通过环境变量注入，不硬编码到代码中。
- **健壮性**：高德 API 调用失败时返回友好错误提示，不影响对话流程。
- **一致性**：新增子 Agent 的注册方式、工具封装风格与现有代码保持一致。
- **简洁性**：路径规划结果以简洁文本格式返回，包含距离、预计时间、关键路线步骤。

## 7. Constraints & Dependencies

- 高德 Web 服务 API Key 已配置在系统环境变量 `AMAP_WEBSERVICE_KEY` 中。
- 项目已有 RAG 基础设施（Chroma + LlamaIndex），新增知识域复用现有加载与检索流程。
- 项目已有子 Agent 注册机制（`registry.py`），新增子 Agent 复用现有声明式注册方式。
- 高德 REST API 基础地址：`https://restapi.amap.com/v3/`。
- 公司地址：广东省深圳市光明区马田街道光明国际汽车城企业服务中心。

## 8. Assumptions

- `company.md` 中包含准确的公司地址信息，可用于地理编码。
- 高德 API Key 具备地理编码和路径规划接口的调用权限。
- 用户询问到店路线时，会提供出发地（城市/地标/地址）；若未提供，Agent 应主动询问。

## 9. Open Questions

- 无（核心方案已与用户确认：API Key 从环境变量注入）。

## 10. Acceptance Criteria

### AC-1 (rule): 公司信息知识域已注册

`domains.py` 中存在 `company_info` 域定义，其 `directories` 包含 `docs/company_info`。

### AC-2 (rule): 公司信息子 Agent 已注册

`registry.py` 的 `_DOMAIN_SUBAGENTS` 中存在 `company_info_expert` 条目，绑定 `company_info` 域的检索工具，且关联 prompt 文件 `company_info_agent`。

### AC-3 (rule): 公司信息 Agent Prompt 已创建

`prompts/company_info_agent.md` 文件存在，且包含角色定义、职责范围、工作方式（必须检索知识库）、边界说明。

### AC-4 (rule): 主 Agent 路由规则已更新

`system_prompt.md` 中包含将公司介绍、联系方式、到店路线等问题路由到 `company_info_expert` 的规则。

### AC-5 (rule): 高德地图工具已实现

`tools/amap_tools.py` 存在，至少包含 `amap_geocode` 和 `amap_direction_driving` 两个工具，且 API Key 从 `settings.AMAP_API_KEY` 读取，不硬编码。

### AC-6 (rule): 高德工具已注册到公司信息子 Agent

`company_info_expert` 子 Agent 的工具列表中包含高德地图工具。

### AC-7 (rule): 配置项已添加

`config.py` 中存在 `AMAP_API_KEY` 配置项，默认值为空字符串，从环境变量读取。

### AC-8 (rule): company.md 可被 RAG 系统加载

启动 RAG 索引构建后，`company.md` 被加载并标记为 `company_info` 域（可通过日志或检索验证）。

### AC-9 (rubric): 路径规划结果可读性

维度：导航信息的文本表达清晰度
- 2分：包含距离、预计时间、关键转向/换乘步骤，格式清晰易读
- 1分：包含距离和时间，但路线步骤不完整或格式混乱
- 0分：仅返回原始 API 数据，无格式化处理
通过阈值：>= 1 分

### AC-10 (rubric): 公司信息回答准确性

维度：基于知识库回答公司问题的准确程度
- 2分：回答内容与 company.md 一致，标注来源文件，无编造
- 1分：回答基本正确，但有少量遗漏或未标注来源
- 0分：回答包含编造信息或与文档不符
通过阈值：>= 1 分

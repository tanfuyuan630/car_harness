# 公司信息 Agent 与高德地图导航集成 - Implementation Plan

## Task 1: 新增 company_info 知识域定义
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 在 `backend/app/rag/domains.py` 的 `DOMAIN_SPECS` 中新增 `company_info` 域
  - key 为 `company_info`，title 为"公司信息"，directories 为 `("docs/company_info",)`
- **Acceptance Criteria Addressed**: AC-1
- **Test Requirements**:
  - `rule` TR-1.1: `domains.py` 中存在 `company_info` 域定义，其 `directories` 包含 `docs/company_info`；证据：代码文件内容
- **Completion Evidence**:
  - `domains.py` 第 66-70 行新增 `company_info` 域定义，directories 为 `("docs/company_info",)`
  - 运行验证：`resolve_domain('docs/company_info/company.md')` 返回 `company_info`

## Task 2: 新增公司信息子 Agent 注册
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1, Task 3
- **Description**:
  - 在 `backend/app/agent/registry.py` 的 `_DOMAIN_SUBAGENTS` 中新增 `company_info_expert` 条目
  - 绑定 `company_info` 域的知识库检索工具，关联 prompt 文件 `company_info_agent`
  - 描述需写明领域、关键词与边界
- **Acceptance Criteria Addressed**: AC-2
- **Test Requirements**:
  - `rule` TR-2.1: `_DOMAIN_SUBAGENTS` 中存在 `company_info_expert` 条目，domain 为 `company_info`，prompt_name 为 `company_info_agent`；证据：代码文件内容
- **Completion Evidence**:
  - `registry.py` 第 61-66 行新增 `company_info_expert` 条目，domain=`company_info`，prompt_name=`company_info_agent`
  - 运行验证：子 Agent 列表中包含 `company_info_expert`，工具数为 5

## Task 3: 创建公司信息 Agent Prompt
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 新建 `backend/app/agent/prompts/company_info_agent.md`
  - 定义公司信息专家的角色、职责范围、工作方式（回答前必须检索知识库）、边界说明
- **Acceptance Criteria Addressed**: AC-3
- **Test Requirements**:
  - `rule` TR-3.1: `prompts/company_info_agent.md` 文件存在；证据：文件存在
  - `rule` TR-3.2: prompt 包含角色定义、职责范围、工作方式（含"必须检索知识库"）、边界说明；证据：文件内容
- **Completion Evidence**:
  - `prompts/company_info_agent.md` 已创建，包含角色定义、职责范围、工作方式（必须调用 search_knowledge_base）、边界说明

## Task 4: 更新主 Agent 路由规则
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: None
- **Description**:
  - 更新 `backend/app/agent/prompts/system_prompt.md`
  - 增加将公司介绍、联系方式、发展历程、入驻品牌、到店路线等问题路由到 `company_info_expert` 的规则
- **Acceptance Criteria Addressed**: AC-4
- **Test Requirements**:
  - `rule` TR-4.1: `system_prompt.md` 中包含 `company_info_expert` 路由规则；证据：文件内容
- **Completion Evidence**:
  - `system_prompt.md` 第 12 行新增路由规则：公司介绍、联系方式、发展历程、入驻品牌、到店路线与导航 → company_info_expert

## Task 5: 实现高德地图工具集
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 7
- **Description**:
  - 新建 `backend/app/agent/tools/amap_tools.py`
  - 封装高德地图 Web 服务 REST API 为 LangChain Tools：
    - `amap_geocode`：地址转经纬度（地理编码）
    - `amap_direction_driving`：驾车路径规划
    - `amap_direction_transit`：公交路径规划
    - `amap_direction_walking`：步行路径规划
  - API Key 从 `settings.AMAP_API_KEY` 读取
  - 调用失败时返回结构化错误信息，不抛出未捕获异常
  - 路径规划结果格式化为简洁文本（距离、预计时间、关键步骤）
- **Acceptance Criteria Addressed**: AC-5, AC-9
- **Test Requirements**:
  - `rule` TR-5.1: `tools/amap_tools.py` 存在，包含 `amap_geocode` 和 `amap_direction_driving` 工具；证据：代码文件内容
  - `rule` TR-5.2: API Key 从 `settings.AMAP_API_KEY` 读取，无硬编码；证据：代码搜索无 API Key 字面量
  - `rubric` TR-5.3: 路径规划结果文本表达清晰度；scale 0-2；anchors 0=仅原始数据, 1=含距离时间但步骤不完整, 2=含距离时间和关键步骤格式清晰；threshold >= 1；evidence：调用工具返回的格式化文本
- **Completion Evidence**:
  - `tools/amap_tools.py` 已创建，包含 4 个工具
  - API Key 通过 `settings.AMAP_API_KEY` 读取，无硬编码
  - 驾车路径规划返回："驾车路线：全程约 26.0公里，预计 36分钟。" + 19 步详细路线
  - TR-5.3 评分：2 分（包含距离、预计时间、关键转向步骤，格式清晰易读）

## Task 6: 将高德工具注册到公司信息子 Agent
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2, Task 5
- **Description**:
  - 修改 `registry.py` 中 `company_info_expert` 子 Agent 的构建逻辑
  - 在其工具列表中追加高德地图工具（`get_amap_tools()`）
- **Acceptance Criteria Addressed**: AC-6
- **Test Requirements**:
  - `rule` TR-6.1: `company_info_expert` 子 Agent 的工具列表包含高德工具；证据：代码文件内容
- **Completion Evidence**:
  - `registry.py` 第 136-140 行：`company_info_expert` 的 tools 列表追加 `get_amap_tools()`
  - 运行验证：`company_info_expert` 工具数为 5（1 知识库 + 4 高德）

## Task 7: 添加高德 API Key 配置项
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 在 `backend/app/core/config.py` 中新增 `AMAP_API_KEY` 配置项
  - 在 `backend/.env.example` 中新增高德 API Key 示例配置
- **Acceptance Criteria Addressed**: AC-7
- **Test Requirements**:
  - `rule` TR-7.1: `config.py` 中存在 `AMAP_API_KEY` 配置项，默认值为空字符串；证据：代码文件内容
  - `rule` TR-7.2: `.env.example` 中存在高德 API Key 配置行；证据：文件内容
- **Completion Evidence**:
  - `config.py` 第 85-86 行：`AMAP_API_KEY: str = Field(default="", alias="AMAP_WEBSERVICE_KEY")`
  - `.env.example` 第 49-51 行：新增 `AMAP_WEBSERVICE_KEY=` 配置
  - 环境变量 `AMAP_WEBSERVICE_KEY` 已配置，工具调用成功

## Task 8: 验证 RAG 索引加载与端到端功能
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 1, Task 2, Task 3, Task 4, Task 5, Task 6, Task 7
- **Description**:
  - 验证 `company.md` 被 RAG 系统加载并标记为 `company_info` 域
  - 验证高德地理编码工具能正确解析公司地址
  - 验证路径规划工具能返回格式化的导航信息
- **Acceptance Criteria Addressed**: AC-8, AC-9, AC-10
- **Test Requirements**:
  - `rule` TR-8.1: 运行 RAG 索引构建后，`company.md` 被加载且 domain 为 `company_info`；证据：RAG 日志或检索结果
  - `rule` TR-8.2: `amap_geocode` 调用公司地址返回有效经纬度；证据：工具调用输出
  - `rule` TR-8.3: `amap_direction_driving` 调用返回包含距离和时间的文本；证据：工具调用输出
- **Completion Evidence**:
  - TR-8.1: RAG 索引重建后共 14 篇文档，领域分布包含 `company_info: 1`，`company.md` 被正确加载
  - TR-8.2: `amap_geocode` 调用返回 "经纬度：113.892797,22.738990"
  - TR-8.3: `amap_direction_driving` 返回 "全程约 26.0公里，预计 36分钟"
  - RAG 检索 "公司地址在哪里" 返回 3 条 company.md 片段，最高分数 0.8773

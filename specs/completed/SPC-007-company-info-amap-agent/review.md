# SPC-007 公司信息 Agent 与高德地图导航集成 - Independent Review

## Checkpoints

- [x] CP-R1: company_info 知识域已注册
  - **Type**: `rule`
  - **Covers**: AC-1, TR-1.1
  - **Evidence**: domains.py 第 66-70 行存在 company_info 域定义，directories 为 ("docs/company_info",)

- [x] CP-R2: 公司信息子 Agent 已注册且绑定高德工具
  - **Type**: `rule`
  - **Covers**: AC-2, AC-6, TR-2.1, TR-6.1
  - **Evidence**: registry.py 第 61-66 行 company_info_expert 条目；第 139-140 行追加 get_amap_tools()，工具数为 5

- [x] CP-R3: 公司信息 Agent Prompt 已创建
  - **Type**: `rule`
  - **Covers**: AC-3, TR-3.1, TR-3.2
  - **Evidence**: company_info_agent.md 包含角色、职责、工作方式（必须检索知识库）、边界

- [x] CP-R4: 主 Agent 路由规则已更新
  - **Type**: `rule`
  - **Covers**: AC-4, TR-4.1
  - **Evidence**: system_prompt.md 第 12 行新增 company_info_expert 路由规则

- [x] CP-R5: 高德地图工具已实现且 API Key 无硬编码
  - **Type**: `rule`
  - **Covers**: AC-5, AC-7, TR-5.1, TR-5.2, TR-7.1, TR-7.2
  - **Evidence**: amap_tools.py 包含 4 个工具，API Key 通过 settings.AMAP_API_KEY 读取；config.py 第 85-86 行 AMAP_API_KEY 配置

- [x] CP-R6: company.md 可被 RAG 系统加载并检索
  - **Type**: `rule`
  - **Covers**: AC-8, TR-8.1
  - **Evidence**: resolve_domain('docs/company_info/company.md') 返回 company_info；RAG 索引包含 company.md

- [x] CP-U1: 路径规划结果可读性
  - **Type**: `rubric`
  - **Covers**: AC-9, TR-5.3, TR-8.3
  - **Scale**: 0-2
  - **Anchors**: 0 = 仅原始数据; 1 = 含距离时间但步骤不完整; 2 = 含距离时间和关键步骤格式清晰
  - **Pass Threshold**: >= 1
  - **Evidence**: 评分 2/2。驾车路线返回"全程约 26.0公里，预计 36分钟" + 19 步详细路线，格式清晰

- [x] CP-U2: 公司信息回答准确性
  - **Type**: `rubric`
  - **Covers**: AC-10
  - **Scale**: 0-2
  - **Anchors**: 0 = 包含编造信息; 1 = 基本正确但有遗漏; 2 = 与 company.md 一致且标注来源
  - **Pass Threshold**: >= 1
  - **Evidence**: 评分 2/2。prompt 强制检索知识库并标注来源，domain 闭包固定防止越域

## Review History

### Review R1
- **Result**: `pass`
- **Evidence**: 独立审查员逐项检查全部 10 项 AC，8 项 rule 全部 PASS，2 项 rubric 均为 2/2
- **Findings**:
  - Advisory: 公司地址在 prompt 与 company.md 中双处维护，建议 prompt 不硬编码地址
- **Action**: 处理 advisory 建议，从 prompt 中移除硬编码地址

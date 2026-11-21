# 汽车销售助手 Agent Harness - 产品需求文档

## Overview
- **Summary**: 基于 LangGraph 运行时与 deepagents（LangChain 官方 Agent Harness，构建于 LangGraph 之上）构建的汽车销售智能助手，具备完整的 Agent Harness 能力：规划工具、工具调用、子智能体、虚拟文件系统、人机协同、流式输出与对话持久化。后端使用 FastAPI 暴露接口，前端使用 Vue3 提供聊天与车型浏览交互界面。
- **Purpose**: 为购车用户提供自然语言交互的车型查询、参数对比、智能推荐服务，通过 Agent Harness 的规划与工具编排能力处理复杂多步购车咨询任务。
- **Target Users**: 有购车意向、需要查询和对比汽车配置的普通消费者。

## Goals
- 提供基于自然语言的汽车配置问答、车型对比、智能推荐能力
- 实现完整的 Agent Harness 功能（规划、子智能体、文件系统、人机协同、流式输出、持久化）
- 提供可视化的前端聊天界面与车型浏览/对比页面
- 复用已有的 `data/cars.csv`（4005 车型）、`data/brand_tree.json` 与 `data/raw/series_*.json` 数据

## Non-Goals
- 不实现真实下单、支付、库存管理等交易环节
- 不接入实时汽车行情/报价 API（仅使用本地静态数据）
- 不实现用户账户体系与多租户权限（单会话线程隔离即可）
- 不做移动端原生 App（仅 Web 前端）

## Background & Context
- 工作区已有从太平洋汽车抓取的结构化数据：`data/cars.csv`（4005 行 × 439 列，覆盖 50 品牌、716 车系）、`data/brand_tree.json`（424 品牌、5661 车系映射）、`data/raw/series_*.json`（792 个车系的原始 JSON 缓存）
- 数据字段涵盖品牌、车系、指导价、级别、能源类型、发动机、变速箱、车身尺寸、安全配置、智能驾驶、舒适配置等数百项参数
- 用户具备 LangGraph 使用经验，偏好清晰方案、不做过度优化与兜底兼容

## Functional Requirements

### Agent Harness 核心能力
- **FR-1（规划）**: Agent 收到复杂请求时，先调用规划工具拆解为有序子任务，再逐步执行
- **FR-2（工具调用）**: Agent 可调用汽车领域工具（搜索、详情、对比、推荐、品牌树浏览）
- **FR-3（子智能体）**: Agent 可将对比、推荐等专业任务委托给专门的子智能体处理
- **FR-4（虚拟文件系统）**: Agent 可通过文件工具保存对比报告、用户偏好等到虚拟工作区
- **FR-5（人机协同）**: 对"给出最终推荐"等高影响动作，触发人机协同审批，用户可批准/拒绝/修改
- **FR-6（流式输出）**: 聊天接口支持 SSE 流式返回 Agent 思考过程与最终回复
- **FR-7（对话持久化）**: 基于 LangGraph Checkpointer 持久化对话状态，支持历史回溯与恢复

### Harness 模块化与可插拔
- **FR-M1（可插拔 LLM）**: LLM 客户端通过统一接口封装，可切换不同模型提供商（OpenAI 兼容、Anthropic 等），仅需修改配置
- **FR-M2（可插拔工具）**: 工具以独立模块注册到 Harness，新增/移除工具不修改核心编排逻辑
- **FR-M3（可插拔子智能体）**: 子智能体通过配置列表注册，可动态增减，每个子智能体持有独立工具集与 prompt
- **FR-M4（可插拔文件系统后端）**: 虚拟文件系统支持切换后端（本地磁盘/内存），通过配置指定
- **FR-M5（可插拔持久化后端）**: Checkpointer 支持切换（MemorySaver/SqliteSaver 等），通过配置指定
- **FR-M6（可插拔 Prompt）**: system prompt 与各子智能体 prompt 独立存放于配置文件，无需改代码即可调整人设

### 汽车领域工具
- **FR-8（车型搜索）**: 按品牌、车系、价格区间、级别、能源类型等条件筛选车型
- **FR-9（车型详情）**: 查询指定车型的完整参数（价格、尺寸、动力、配置等）
- **FR-10（车型对比）**: 对比 2~5 款车型的关键参数，输出结构化对比结果
- **FR-11（智能推荐）**: 根据预算、用途、偏好（SUV/轿车、新能源/燃油等）推荐车型
- **FR-12（品牌树浏览）**: 浏览品牌-车系层级结构

### 后端 API
- **FR-13**: 提供非流式聊天接口 `POST /api/chat`
- **FR-14**: 提供流式聊天接口 `POST /api/chat/stream`（SSE）
- **FR-15**: 提供会话线程管理接口（创建、获取历史）
- **FR-16**: 提供人机协同审批接口
- **FR-17**: 提供汽车数据查询接口（品牌树、车型搜索、详情）

### 前端
- **FR-18**: 聊天页面，支持流式消息展示、工具调用过程可视化
- **FR-19**: 车型浏览页面，按品牌-车系-车型层级浏览
- **FR-20**: 车型对比页面，多车型参数表格对比
- **FR-21**: 人机协同审批界面，展示待审批动作并支持批准/拒绝

## Non-Functional Requirements
- **NFR-1（技术栈）**: 使用 `deepagents`（LangChain 官方 Agent Harness，构建于 LangGraph 运行时之上，自带规划、子智能体、虚拟文件系统、人机协同、流式、持久化能力）；后端 FastAPI；前端 Vue3 + Vite
- **NFR-2（LLM）**: 通过 OpenAI 兼容接口调用大模型，模型与 API Key 通过环境变量配置
- **NFR-3（数据）**: 启动时将 `cars.csv` 加载到内存索引，查询走内存，不引入数据库
- **NFR-4（流式）**: 流式接口使用 Server-Sent Events，前端逐 token 渲染
- **NFR-5（持久化）**: 使用 LangGraph MemorySaver 作为 Checkpointer（单进程内存持久化，无需外部存储）
- **NFR-6（模块化）**: LLM、工具、子智能体、文件系统后端、Checkpointer、Prompt 均通过配置注册，新增组件无需修改核心编排代码

## Constraints
- **Technical**: Python 3.13；deepagents 构建于 LangGraph 1.x 之上；前端 Vue3 生态
- **Business**: 仅使用本地静态汽车数据，不保证实时性
- **Dependencies**: deepagents、langgraph、langchain-openai、langchain-core、fastapi、uvicorn、pandas、pydantic、sse-starlette；前端 vue、vite、pinia、vue-router、axios

## Assumptions
- LLM 使用 OpenAI 兼容端点（默认指向 DashScope 通义千问兼容模式），通过 `OPENAI_API_BASE` 与 `OPENAI_API_KEY` 环境变量配置
- 数据量级（4005 车型）适合全量加载到内存，无需数据库
- 人机协同的审批粒度为"最终推荐动作"，非每次工具调用

## Acceptance Criteria

### AC-1: Agent Harness 规划能力
- **Type**: `rule`
- **Given**: 用户提出一个需要多步处理的请求（如"30 万以内适合家用的 SUV 推荐"）
- **When**: 请求发送到聊天接口
- **Then**: Agent 首先输出规划步骤，然后按步骤调用工具并给出最终回复
- **Pass Condition**: 流式输出中可见规划工具的调用与执行步骤
- **Evidence**: 接口流式响应中包含 planning 相关的事件或消息

### AC-2: 工具调用与车型搜索
- **Type**: `rule`
- **Given**: 用户输入"推荐 20 万左右的合资中型轿车"
- **When**: Agent 处理请求
- **Then**: Agent 调用车型搜索工具，返回符合条件的车型列表
- **Pass Condition**: 工具调用参数正确，返回结果包含至少 1 款符合价格与级别条件的车型
- **Evidence**: 搜索工具返回的车型指导价在 15~25 万区间且级别为中型车

### AC-3: 车型对比
- **Type**: `rule`
- **Given**: 用户输入"对比奥迪 A4L 和宝马 3 系"
- **When**: Agent 处理请求
- **Then**: Agent 调用对比工具，输出两款车型的关键参数对比
- **Pass Condition**: 对比结果包含两款车型的价格、级别、动力等核心参数
- **Evidence**: 对比工具返回结构化数据，前端以表格展示

### AC-4: 子智能体委托
- **Type**: `rule`
- **Given**: 用户输入"帮我对比 5 款 25 万 SUV 并推荐一款"
- **When**: Agent 处理请求
- **Then**: Agent 将对比与推荐任务委托给子智能体
- **Pass Condition**: 执行日志中可见子智能体被调用并返回结果
- **Evidence**: 流式事件中包含 subagent 调用记录

### AC-5: 虚拟文件系统
- **Type**: `rule`
- **Given**: Agent 完成车型对比后
- **When**: 用户要求"把对比结果保存下来"
- **Then**: Agent 调用文件写入工具将对比报告保存到虚拟文件系统
- **Pass Condition**: 文件系统中存在该报告文件且内容正确
- **Evidence**: 调用文件列表工具可看到已保存的报告

### AC-6: 人机协同审批
- **Type**: `rule`
- **Given**: Agent 准备给出最终购车推荐
- **When**: 触发高影响动作
- **Then**: 前端弹出审批界面，用户可批准或拒绝
- **Pass Condition**: 未经用户批准，Agent 不输出最终推荐；批准后继续执行
- **Evidence**: HITL 接口可查询待审批动作，批准后 Agent 继续执行

### AC-7: 流式输出
- **Type**: `rule`
- **Given**: 用户发送任意消息
- **When**: 调用流式聊天接口
- **Then**: 接口以 SSE 方式逐段返回内容
- **Pass Condition**: 前端可逐 token 渲染回复内容
- **Evidence**: SSE 响应包含多个 data 事件

### AC-8: 对话持久化
- **Type**: `rule`
- **Given**: 用户在一个会话中发送多条消息
- **When**: 重新获取该会话历史
- **Then**: 历史消息完整可恢复
- **Pass Condition**: 会话历史接口返回之前所有消息
- **Evidence**: `GET /api/thread/{id}/history` 返回完整消息列表

### AC-9: 前端聊天界面
- **Type**: `rule`
- **Given**: 前端服务已启动
- **When**: 用户打开聊天页面并发送消息
- **Then**: 页面展示用户消息与 Agent 流式回复，工具调用过程可见
- **Pass Condition**: 消息列表正确渲染，流式内容逐步出现
- **Evidence**: 浏览器中可观察到流式消息渲染

### AC-10: 前端车型浏览与对比
- **Type**: `rule`
- **Given**: 前端服务已启动
- **When**: 用户进入车型浏览页选择品牌-车系-车型，并发起对比
- **Then**: 页面展示车型列表与对比表格
- **Pass Condition**: 品牌树可展开，车型详情可查看，对比表格正确渲染
- **Evidence**: 浏览器中可浏览车型并生成对比表格

### AC-11: 架构与依赖正确性
- **Type**: `rubric`
- **Dimension**: 技术架构契合度
- **Scale**: 1-5
- **Anchors**: 1 = 未使用指定技术栈；3 = 使用了指定技术栈但 Harness 功能不完整；5 = 完整使用 deepagents(LangGraph)/FastAPI/Vue3 且 Harness 六大能力齐全
- **Pass Threshold**: >= 4
- **Evidence**: 代码结构与依赖清单

### AC-12: 端到端可用性
- **Type**: `rubric`
- **Dimension**: 端到端购车咨询体验
- **Scale**: 1-5
- **Anchors**: 1 = 无法完成一次完整咨询；3 = 可完成简单问答但对比/推荐有缺陷；5 = 可流畅完成搜索、对比、推荐、保存全流程
- **Pass Threshold**: >= 4
- **Evidence**: 手动端到端测试记录

### AC-13: Harness 模块化与可插拔
- **Type**: `rubric`
- **Dimension**: 组件可插拔程度
- **Scale**: 1-5
- **Anchors**: 1 = 组件硬编码，无法替换；3 = 部分组件可配置（如 LLM），但工具/子智能体仍需改代码；5 = LLM、工具、子智能体、文件系统后端、Checkpointer、Prompt 均通过配置注册，新增组件无需修改核心编排代码
- **Pass Threshold**: >= 4
- **Evidence**: 代码结构（配置驱动注册）与组件切换验证记录

## Open Questions
- [ ] LLM 提供商与具体模型是否默认使用通义千问（DashScope 兼容模式）？

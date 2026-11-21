"""Agent Harness 模块化注册中心：统一管理 LLM、工具、子智能体、文件系统后端、Checkpointer、Prompt 的配置化注册。

主 Agent 只持有通用工具（文件系统、最终推荐审批），业务执行全部交给领域子 Agent；
子 Agent 由声明式领域表统一注册，每个领域子 Agent 只绑定本域知识检索工具。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.llm import create_tiered_llm
from app.agent.tools.car_tools import get_car_tools
from app.agent.tools.filesystem_tools import get_filesystem_tools
from app.agent.tools.recoverable import recoverable_tool
from app.core.config import settings
from app.services.checkpoint_store import get_checkpointer

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# 领域子 Agent 声明：子 Agent 名称、知识域、路由描述、提示词文件名。
# 描述同时作为 deepagents task 工具的路由清单，需写明领域、关键词与边界。
_DOMAIN_SUBAGENTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "insurance_underwriting_expert",
        "underwriting",
        "保险承保专家。负责车险投保、报价、核保、出单、交强险与商业险条款责任、费率与无赔款优待、新能源车险承保。涉及投保方案、保费构成、核保规则、保单批改时使用；不含事故报案、查勘定损与理赔。",
        "insurance_underwriting_agent",
    ),
    (
        "insurance_claims_expert",
        "claims",
        "保险理赔专家。负责报案受理、查勘立案、定损核价、人伤审核、理算核赔、赔付结案、拒赔与争议处理、理赔时效与理赔条款。涉及事故后怎么报案、定损、索赔材料、赔款计算时使用；不含投保报价与核保出单。",
        "insurance_claims_agent",
    ),
    (
        "vehicle_sales_expert",
        "sales",
        "汽车销售专家。负责客户接待、需求分析、试驾、报价与异议处理、合同定金、金融分期、车辆交付、上牌抵押、二手车置换、销售合规。涉及购车流程、签约交付、贷款分期、置换业务时使用；不含保险理赔、维修保养与美容施工。",
        "vehicle_sales_agent",
    ),
    (
        "after_sales_expert",
        "after_sales",
        "汽车售后专家。负责预约接待、故障诊断、维修保养作业、备件管理、质量控制与交车、三包与保修索赔、汽车召回、售后投诉与回访。涉及保养流程、三包条件、保修索赔、召回与售后投诉时使用；不含洗车贴膜等美容施工、整车销售与保险理赔。",
        "after_sales_agent",
    ),
    (
        "repair_beauty_expert",
        "repair",
        "汽车维修美容专家。负责洗车、漆面护理、内饰护理、贴膜施工、施工安全防护、耗材与化工品管理、美容项目质量交付。涉及洗车打蜡、抛光镀晶、内饰清洁、贴膜工艺与施工注意事项时使用；不含维修保养流程、三包索赔与保险定损。",
        "repair_beauty_agent",
    ),
    (
        "car_accessories_expert",
        "accessories",
        "汽车用品交易专家。负责汽车用品分类、交易渠道、采购与进货查验、质量认证、销售交易流程、退换货、价格合同、仓储库存、消费者权益。涉及用品选购、进货查验、用品退换与库存管理时使用；不含整车销售、保险、维修保养与美容施工。",
        "car_accessories_agent",
    ),
    (
        "company_info_expert",
        "company_info",
        "公司信息专家。负责公司基本信息、联系方式、发展历程、入驻品牌、经营数据、企业荣誉，以及到店导航与路线规划。涉及公司介绍、地址电话、怎么到公司、驾车/公交/步行路线时使用；不含具体车型参数、购车流程、保险与维修。",
        "company_info_agent",
    ),
)


class AgentRegistry:
    """组件注册中心。"""

    def __init__(self) -> None:
        self._llm = None
        self._tools: list[BaseTool] = []
        self._subagents: list[dict[str, Any]] = []

    # ---------------- LLM ----------------

    @property
    def llm(self):
        # 主 Agent 使用按请求入口档位选模型的实例
        if self._llm is None:
            self._llm = create_tiered_llm("main")
        return self._llm

    # ---------------- Prompt ----------------

    def get_prompt(self, name: str) -> str:
        """读取 prompts 目录下的 prompt 文件内容。"""
        path = _PROMPTS_DIR / f"{name}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    @property
    def system_prompt(self) -> str:
        return self.get_prompt("system_prompt")

    # ---------------- 主 Agent 工具 ----------------

    @property
    def tools(self) -> list[BaseTool]:
        """主 Agent 只持有通用工具，业务能力全部通过子 Agent 委派。"""
        if not self._tools:
            self._tools = [recoverable_tool(t) for t in get_filesystem_tools()]
            # ACP 文件生成工具按开关注册，子 Agent 不持有
            if settings.ACP_ENABLED:
                from app.agent.tools.acp_file_tools import get_acp_file_tools
                self._tools = self._tools + [recoverable_tool(t) for t in get_acp_file_tools()]
        return self._tools

    def get_tool(self, name: str) -> BaseTool | None:
        for t in self.tools:
            if t.name == name:
                return t
        return None

    # ---------------- 子智能体 ----------------

    def _build_subagents(self) -> list[dict[str, Any]]:
        """按声明式领域表构建子 Agent 列表，RAG 关闭时跳过领域子 Agent。"""
        # 子 Agent 共用同一分档模型实例，分类结果按委派任务描述缓存
        subagent_model = create_tiered_llm("subagent")
        subagents: list[dict[str, Any]] = [
            {
                "name": "car_model_expert",
                "description": (
                    "车型数据专家。负责车型参数查询、多车型对比与购车推荐。"
                    "涉及具体车型配置、价格、尺寸动力、车型差异对比、按预算和偏好推荐车型时使用。"
                    "不涉及保险、销售流程、售后维修与用品交易。"
                ),
                "model": subagent_model,
                "tools": [recoverable_tool(t) for t in get_car_tools()],
                "system_prompt": self.get_prompt("car_model_agent"),
            }
        ]

        if settings.RAG_ENABLED:
            from app.agent.tools.rag_tools import build_domain_knowledge_tool
            from app.agent.tools.amap_tools import get_amap_tools

            for name, domain, description, prompt_name in _DOMAIN_SUBAGENTS:
                tools = [recoverable_tool(build_domain_knowledge_tool(domain))]
                # 公司信息子 Agent 额外绑定高德地图工具，用于到店导航
                if name == "company_info_expert":
                    tools.extend([recoverable_tool(t) for t in get_amap_tools()])
                subagents.append(
                    {
                        "name": name,
                        "description": description,
                        "model": subagent_model,
                        "tools": tools,
                        "system_prompt": self.get_prompt(prompt_name),
                    }
                )

        enabled = settings.enabled_subagents_list
        if enabled:
            return [s for s in subagents if s["name"] in enabled]
        return subagents

    @property
    def subagents(self) -> list[dict[str, Any]]:
        if not self._subagents:
            self._subagents = self._build_subagents()
        return self._subagents

    # ---------------- Checkpointer ----------------

    @property
    def checkpointer(self) -> BaseCheckpointSaver:
        """返回已初始化的 Checkpointer（启动阶段完成初始化）。"""
        return get_checkpointer()

    # ---------------- 文件系统后端 ----------------

    @property
    def filesystem_backend(self):
        """返回 deepagents 文件系统后端实例。"""
        if settings.FILESYSTEM_BACKEND == "memory":
            from deepagents.backends.state import StateBackend
            return StateBackend()
        from deepagents.backends.filesystem import FilesystemBackend
        return FilesystemBackend(root_dir=str(settings.workspace_dir_path))


# 全局单例
registry = AgentRegistry()

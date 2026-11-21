"""知识域定义：业务领域标识、中文名与文档来源映射。

领域与文档目录一一对应，供文档加载、领域检索与子 Agent 注册共同使用。
映射未命中时返回 None，由调用方跳过并记录日志，不做内容猜测。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class DomainSpec:
    """一个业务知识域的定义。

    directories: 相对 DATA_DIR 的目录，目录下全部文档归属该领域
    files: 相对 DATA_DIR 的单个文件，用于根目录下无法按目录归类的文档
    """

    key: str
    title: str
    directories: tuple[str, ...] = ()
    files: tuple[str, ...] = ()


DOMAIN_SPECS: tuple[DomainSpec, ...] = (
    DomainSpec(
        key="underwriting",
        title="保险承保",
        directories=("insurance/policy",),
    ),
    DomainSpec(
        key="claims",
        title="保险理赔",
        directories=("insurance/claims",),
    ),
    DomainSpec(
        key="sales",
        title="汽车销售",
        directories=("docs/sales",),
        files=(
            "docs/完整-汽车4S店销售管理制度.doc",
            "docs/汽车4S店销售部制度(执行版)-2.doc",
        ),
    ),
    DomainSpec(
        key="after_sales",
        title="汽车售后",
        directories=("docs/after_sales",),
        files=(
            "docs/汽车采购售后服务方案.doc",
            "docs/车辆采购质量保证及售后服务条款.doc",
        ),
    ),
    DomainSpec(
        key="repair",
        title="汽车维修美容",
        directories=("docs/repair",),
        files=("docs/汽车定点维修服务采购合同.docx",),
    ),
    DomainSpec(
        key="accessories",
        title="汽车用品交易",
        directories=("docs/accessories",),
    ),
    DomainSpec(
        key="company_info",
        title="公司信息",
        directories=("docs/company_info",),
    ),
)

# 领域标识 -> 领域定义
DOMAIN_BY_KEY: dict[str, DomainSpec] = {spec.key: spec for spec in DOMAIN_SPECS}


def resolve_domain(relative_path: str | PurePosixPath) -> str | None:
    """按相对 DATA_DIR 的路径判定知识域，未命中返回 None。"""
    path = PurePosixPath(relative_path).as_posix()
    for spec in DOMAIN_SPECS:
        if path in spec.files:
            return spec.key
        for directory in spec.directories:
            if path.startswith(f"{directory}/"):
                return spec.key
    return None

"""知识域解析特性测试：目录与单文件映射。"""
from __future__ import annotations

from app.rag.domains import resolve_domain


def test_resolve_by_directory():
    """目录前缀命中对应领域。"""
    assert resolve_domain("docs/sales/制度.md") == "sales"
    assert resolve_domain("insurance/claims/案例.docx") == "claims"
    assert resolve_domain("insurance/policy/条款.md") == "underwriting"
    assert resolve_domain("docs/company_info/company.md") == "company_info"


def test_resolve_by_single_file():
    """根目录下的指定文件按完整路径命中。"""
    assert resolve_domain("docs/完整-汽车4S店销售管理制度.doc") == "sales"
    assert resolve_domain("docs/汽车定点维修服务采购合同.docx") == "repair"


def test_unknown_path_returns_none():
    """未命中的路径返回 None，不做猜测。"""
    assert resolve_domain("docs/other/说明.md") is None
    assert resolve_domain("unknown.md") is None

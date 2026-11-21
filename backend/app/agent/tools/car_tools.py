"""汽车领域工具集：将数据服务封装为 LangChain Tool，供 Agent 调用。"""
from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import tool

from app.services.car_data import car_data_service


@tool
def search_cars_tool(
    brand: Optional[str] = None,
    series: Optional[str] = None,
    level: Optional[str] = None,
    energy_type: Optional[str] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    keyword: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """按条件搜索车型。参数均可选：品牌、车系、级别(如紧凑型车/中型车/SUV)、能源类型(汽油/纯电/插电混动)、价格区间(万元)、关键词。返回车型列表。"""
    return car_data_service.search_cars(
        brand=brand, series=series, level=level, energy_type=energy_type,
        price_min=price_min, price_max=price_max, keyword=keyword, limit=limit,
    )


@tool
def get_car_detail_tool(model_id: str) -> dict[str, Any]:
    """根据车型ID查询该车型的完整配置参数（价格、尺寸、动力、安全、舒适、智能驾驶等全部字段）。"""
    detail = car_data_service.get_car_detail(model_id)
    if detail is None:
        return {"error": f"未找到车型ID为 {model_id} 的车型"}
    return detail


@tool
def compare_cars_tool(model_ids: list[str]) -> dict[str, Any]:
    """对比多款车型的关键参数。传入车型ID列表，返回各车型在核心字段上的对比结果。"""
    return car_data_service.compare_cars(model_ids)


@tool
def recommend_cars_tool(
    budget_min: Optional[float] = None,
    budget_max: Optional[float] = None,
    body_type: Optional[str] = None,
    energy: Optional[str] = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """根据预算与偏好推荐车型。参数：预算区间(万元)、车身类型(如SUV/轿车)、能源类型(汽油/纯电/混动)。"""
    return car_data_service.recommend_cars(
        budget_min=budget_min, budget_max=budget_max,
        body_type=body_type, energy=energy, limit=limit,
    )


@tool
def list_brands_tool() -> list[dict[str, Any]]:
    """获取所有汽车品牌列表及各品牌的车系数目。"""
    return car_data_service.list_brands()


@tool
def list_series_tool(brand: Optional[str] = None) -> list[dict[str, Any]]:
    """获取车系列表，可指定品牌过滤。返回品牌、车系ID、车系名称。"""
    return car_data_service.list_series(brand=brand)


# 工具注册表：名称 -> Tool 实例
CAR_TOOLS = {
    "search_cars": search_cars_tool,
    "get_car_detail": get_car_detail_tool,
    "compare_cars": compare_cars_tool,
    "recommend_cars": recommend_cars_tool,
    "list_brands": list_brands_tool,
    "list_series": list_series_tool,
}


def get_car_tools(enabled: list[str] | None = None) -> list:
    """根据启用列表返回工具实例；enabled 为空则返回全部。"""
    if not enabled:
        return list(CAR_TOOLS.values())
    return [t for name, t in CAR_TOOLS.items() if name in enabled]

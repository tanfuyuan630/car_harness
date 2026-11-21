"""车型数据服务特性测试：价格解析、搜索、详情、对比与推荐。"""
from __future__ import annotations

import json

import pytest

from app.services.car_data import CarDataService, parse_price

CSV_HEADER = (
    "品牌,车系,车型款,指导价,车系ID,车型ID,级别,能源类型,上市时间,发动机,变速箱,"
    "车身类型,长×宽×高(mm),轴距(mm),驱动方式,座位数(个),整车质保"
)
CSV_ROWS = [
    "星途,星途A,2025款 1.5T 舒适版,12.59万,s1,101,紧凑型SUV,汽油,2025-01,1.5T,7挡双离合,SUV,4500×1850×1650,2700,前驱,5,三年或10万公里",
    "星途,星途A,2025款 2.0T 豪华版,14.99万,s1,102,紧凑型SUV,汽油,2025-03,2.0T,8挡自动,SUV,4550×1860×1660,2720,前驱,5,三年或10万公里",
    "远航,远航C,2025款 纯电 长续航,25.99万,s2,201,中型轿车,纯电动,2025-05,,单速,轿车,4900×1900×1500,2900,后驱,5,四年或12万公里",
]
BRAND_TREE = [
    {"brand": "星途", "series": [{"id": "s1", "name": "星途A"}]},
    {"brand": "远航", "series": [{"id": "s2", "name": "远航C"}]},
]


@pytest.fixture
def service(isolated_data):
    """用临时车型数据构造服务实例。"""
    (isolated_data / "cars.csv").write_text(
        "\n".join([CSV_HEADER, *CSV_ROWS]) + "\n", encoding="utf-8-sig"
    )
    (isolated_data / "brand_tree.json").write_text(
        json.dumps(BRAND_TREE, ensure_ascii=False), encoding="utf-8"
    )
    return CarDataService()


def test_parse_price():
    """指导价字符串解析为万元数值，无法解析时返回 None。"""
    assert parse_price("12.59万") == 12.59
    assert parse_price("25.99 万") == 25.99
    assert parse_price("") is None
    assert parse_price(None) is None
    assert parse_price("暂无报价") is None


def test_list_brands(service):
    """品牌列表包含车系数。"""
    assert service.list_brands() == [
        {"brand": "星途", "series_count": 1},
        {"brand": "远航", "series_count": 1},
    ]


def test_list_series_filter_by_brand(service):
    """车系列表可按品牌过滤。"""
    assert service.list_series("星途") == [
        {"brand": "星途", "series_id": "s1", "series_name": "星途A"}
    ]
    assert len(service.list_series()) == 2


def test_search_by_brand_and_price(service):
    """品牌与价格区间筛选同时生效。"""
    assert len(service.search_cars(brand="星途")) == 2
    result = service.search_cars(brand="星途", price_min=10, price_max=13)
    assert [item["车型ID"] for item in result] == ["101"]


def test_search_by_keyword_and_limit(service):
    """关键词匹配车型款，limit 截断结果。"""
    assert [item["车型ID"] for item in service.search_cars(keyword="豪华")] == ["102"]
    assert len(service.search_cars(limit=1)) == 1


def test_get_car_detail(service):
    """详情返回完整参数，移除内部字段并把空值转为 None。"""
    detail = service.get_car_detail(101)
    assert detail["品牌"] == "星途"
    assert detail["发动机"] == "1.5T"
    assert "_price_num" not in detail
    assert "_车型ID_num" not in detail
    assert service.get_car_detail(201)["发动机"] is None
    assert service.get_car_detail(999) is None


def test_compare_cars(service):
    """对比只包含存在的车型，字段缺失时不输出该列。"""
    result = service.compare_cars([101, 102, 999])
    assert len(result["models"]) == 2
    assert "品牌" in result["fields"]
    assert "油箱容积(L)" not in result["fields"]


def test_recommend_cars_order_by_budget_midpoint(service):
    """预算区间内按价格接近中位数排序。"""
    result = service.recommend_cars(budget_min=10, budget_max=20)
    assert [item["车型ID"] for item in result] == ["102", "101"]
    assert [item["车型ID"] for item in service.recommend_cars(energy="纯电")] == ["201"]

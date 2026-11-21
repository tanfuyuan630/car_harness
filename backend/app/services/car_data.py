"""汽车数据服务：加载 cars.csv 到内存，提供搜索、详情、对比、推荐、品牌树浏览能力。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import settings

# 指导价解析正则：提取 "16.59万" 中的数字
_PRICE_PATTERN = re.compile(r"([\d.]+)")


def parse_price(price_str: str) -> float | None:
    """将 '16.59万' 解析为以万元为单位的浮点数。"""
    if not price_str or pd.isna(price_str):
        return None
    m = _PRICE_PATTERN.search(str(price_str))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


class CarDataService:
    """汽车数据内存服务。"""

    def __init__(self) -> None:
        self._df: pd.DataFrame | None = None
        self._brand_tree: list[dict] = []
        self._load()

    def _load(self) -> None:
        data_dir = settings.data_dir_path
        csv_path = data_dir / "cars.csv"
        tree_path = data_dir / "brand_tree.json"

        df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
        # 预解析指导价数值列，便于区间筛选
        df["_price_num"] = df["指导价"].apply(parse_price)
        df["_车型ID_num"] = pd.to_numeric(df["车型ID"], errors="coerce")
        self._df = df

        if tree_path.exists():
            with open(tree_path, "r", encoding="utf-8") as f:
                self._brand_tree = json.load(f)

    @property
    def df(self) -> pd.DataFrame:
        assert self._df is not None, "数据未加载"
        return self._df

    # ---------------- 品牌树 ----------------

    def list_brands(self) -> list[dict[str, Any]]:
        """返回品牌列表（含车系数）。"""
        result = []
        for item in self._brand_tree:
            result.append({"brand": item["brand"], "series_count": len(item.get("series", []))})
        return result

    def list_series(self, brand: str | None = None) -> list[dict[str, Any]]:
        """返回车系列表，可按品牌过滤。"""
        result = []
        for item in self._brand_tree:
            if brand and brand != item["brand"]:
                continue
            for s in item.get("series", []):
                result.append({"brand": item["brand"], "series_id": s["id"], "series_name": s["name"]})
        return result

    # ---------------- 车型搜索 ----------------

    def search_cars(
        self,
        brand: str | None = None,
        series: str | None = None,
        level: str | None = None,
        energy_type: str | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        keyword: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """按条件筛选车型，返回精简字段列表。"""
        df = self.df
        if brand:
            df = df[df["品牌"].str.contains(brand, na=False)]
        if series:
            df = df[df["车系"].str.contains(series, na=False)]
        if level:
            df = df[df["级别"].str.contains(level, na=False)]
        if energy_type:
            df = df[df["能源类型"].str.contains(energy_type, na=False)]
        if price_min is not None:
            df = df[df["_price_num"] >= price_min]
        if price_max is not None:
            df = df[df["_price_num"] <= price_max]
        if keyword:
            mask = (
                df["车型款"].str.contains(keyword, na=False)
                | df["车系"].str.contains(keyword, na=False)
                | df["品牌"].str.contains(keyword, na=False)
            )
            df = df[mask]

        cols = ["品牌", "车系", "车型款", "指导价", "车系ID", "车型ID", "级别", "能源类型", "上市时间"]
        available = [c for c in cols if c in df.columns]
        result = df[available].head(limit).to_dict(orient="records")
        return result

    # ---------------- 车型详情 ----------------

    def get_car_detail(self, model_id: int | str) -> dict[str, Any] | None:
        """按车型ID返回完整参数字典。"""
        mid = int(model_id)
        row = self.df[self.df["_车型ID_num"] == mid]
        if row.empty:
            return None
        record = row.iloc[0].to_dict()
        # 去除内部辅助字段
        record.pop("_price_num", None)
        record.pop("_车型ID_num", None)
        # 将 NaN 转为 None
        clean = {}
        for k, v in record.items():
            if pd.isna(v):
                clean[k] = None
            else:
                clean[k] = v
        return clean

    # ---------------- 车型对比 ----------------

    def compare_cars(self, model_ids: list[int | str]) -> dict[str, Any]:
        """对比多款车型的关键参数。"""
        key_fields = [
            "品牌", "车系", "车型款", "指导价", "级别", "能源类型", "上市时间",
            "发动机", "变速箱", "车身类型", "长×宽×高(mm)", "轴距(mm)",
            "发动机最大马力(Ps)", "发动机最大功率(kW)", "发动机最大扭矩(N·m)",
            "WLTC综合油耗(L/100km)", "驱动方式", "座位数(个)", "油箱容积(L)",
            "整车质保",
        ]
        cars = []
        for mid in model_ids:
            detail = self.get_car_detail(mid)
            if detail:
                cars.append({k: detail.get(k) for k in key_fields if k in detail})
        return {"models": cars, "fields": [f for f in key_fields if any(c.get(f) for c in cars)]}

    # ---------------- 智能推荐 ----------------

    def recommend_cars(
        self,
        budget_min: float | None = None,
        budget_max: float | None = None,
        usage: str | None = None,
        body_type: str | None = None,
        energy: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """基于预算与偏好推荐车型。"""
        df = self.df
        if budget_min is not None:
            df = df[df["_price_num"] >= budget_min]
        if budget_max is not None:
            df = df[df["_price_num"] <= budget_max]
        if energy:
            df = df[df["能源类型"].str.contains(energy, na=False)]
        if body_type:
            df = df[df["级别"].str.contains(body_type, na=False)]

        # 简单评分：价格越接近预算中位数越好，能源匹配加分
        scored = df.copy()
        if budget_min is not None and budget_max is not None:
            mid_price = (budget_min + budget_max) / 2
            scored["_score"] = -abs(scored["_price_num"] - mid_price)
        else:
            scored["_score"] = 0
        scored = scored.sort_values("_score", ascending=False)

        cols = ["品牌", "车系", "车型款", "指导价", "车系ID", "车型ID", "级别", "能源类型"]
        available = [c for c in cols if c in scored.columns]
        return scored[available].head(limit).to_dict(orient="records")


# 全局单例
car_data_service = CarDataService()

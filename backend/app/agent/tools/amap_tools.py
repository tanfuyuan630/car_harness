"""高德地图工具集：封装地理编码与路径规划 API，供公司信息子 Agent 调用。"""
from __future__ import annotations

import logging
from typing import Optional

import requests
from langchain_core.tools import tool

from app.core.config import settings

logger = logging.getLogger(__name__)

# 高德地图 Web 服务 API 基础地址
_AMAP_BASE = "https://restapi.amap.com/v3"
# 地理编码接口
_GEOCODE_URL = f"{_AMAP_BASE}/geocode/geo"
# 驾车路径规划接口
_DRIVING_URL = f"{_AMAP_BASE}/direction/driving"
# 公交路径规划接口
_TRANSIT_URL = f"{_AMAP_BASE}/direction/transit/integrated"
# 步行路径规划接口
_WALKING_URL = f"{_AMAP_BASE}/direction/walking"
# 请求超时时间（秒）
_TIMEOUT = 10


def _api_key() -> str:
    """返回高德 API Key，未配置时返回空字符串。"""
    return settings.AMAP_API_KEY.strip()


def _format_distance(meters: str) -> str:
    """将米数格式化为人类可读的距离字符串。"""
    try:
        m = float(meters)
    except (TypeError, ValueError):
        return meters
    if m >= 1000:
        return f"{m / 1000:.1f}公里"
    return f"{int(m)}米"


def _format_duration(seconds: str) -> str:
    """将秒数格式化为人类可读的时长字符串。"""
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return seconds
    minutes = s // 60
    if minutes >= 60:
        hours = minutes // 60
        mins = minutes % 60
        if mins:
            return f"{hours}小时{mins}分钟"
        return f"{hours}小时"
    return f"{minutes}分钟"


def _request_amap(url: str, params: dict) -> dict:
    """调用高德 API，返回解析后的 JSON。失败时返回错误信息字典。"""
    params = {**params, "key": _api_key()}
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.warning("高德 API 请求失败：%s", e)
        return {"status": "0", "info": f"网络请求失败：{e}"}


@tool
def amap_geocode(address: str, city: Optional[str] = None) -> str:
    """将结构化地址转换为经纬度坐标。传入地址（可选城市），返回格式化地址与经纬度。"""
    if not _api_key():
        return "高德地图 API Key 未配置，无法进行地理编码。"

    params: dict = {"address": address}
    if city:
        params["city"] = city

    data = _request_amap(_GEOCODE_URL, params)
    if data.get("status") != "1":
        return f"地理编码失败：{data.get('info', '未知错误')}"

    geocodes = data.get("geocodes") or []
    if not geocodes:
        return f"未找到地址「{address}」的坐标信息。"

    geo = geocodes[0]
    location = geo.get("location", "")
    formatted = geo.get("formatted_address", address)
    return f"地址：{formatted}\n经纬度：{location}"


@tool
def amap_direction_driving(origin: str, destination: str) -> str:
    """驾车路径规划。origin 与 destination 为经纬度（格式：经度,纬度），返回距离、预计时间与关键路线步骤。"""
    if not _api_key():
        return "高德地图 API Key 未配置，无法进行路径规划。"

    data = _request_amap(_DRIVING_URL, {"origin": origin, "destination": destination})
    if data.get("status") != "1":
        return f"驾车路径规划失败：{data.get('info', '未知错误')}"

    route = data.get("route", {})
    paths = route.get("paths") or []
    if not paths:
        return "未获取到驾车路线信息。"

    path = paths[0]
    distance = _format_distance(path.get("distance", "0"))
    duration = _format_duration(path.get("duration", "0"))
    steps = path.get("steps") or []

    lines = [f"驾车路线：全程约 {distance}，预计 {duration}。", ""]
    lines.append("路线步骤：")
    for i, step in enumerate(steps, 1):
        instruction = step.get("instruction", "").strip()
        road = step.get("road", "")
        seg_dist = _format_distance(step.get("distance", "0"))
        if road and road not in instruction:
            lines.append(f"{i}. 沿{road}，{instruction}（{seg_dist}）")
        else:
            lines.append(f"{i}. {instruction}（{seg_dist}）")
    return "\n".join(lines)


@tool
def amap_direction_transit(origin: str, destination: str, city: str = "深圳") -> str:
    """公交路径规划。origin 与 destination 为经纬度，city 为城市名，返回距离、预计时间与换乘方案。"""
    if not _api_key():
        return "高德地图 API Key 未配置，无法进行路径规划。"

    data = _request_amap(
        _TRANSIT_URL,
        {"origin": origin, "destination": destination, "city": city},
    )
    if data.get("status") != "1":
        return f"公交路径规划失败：{data.get('info', '未知错误')}"

    route = data.get("route", {})
    transits = route.get("transits") or []
    if not transits:
        return "未获取到公交路线信息。"

    transit = transits[0]
    distance = _format_distance(transit.get("distance", "0"))
    duration = _format_duration(transit.get("duration", "0"))

    lines = [f"公交路线：全程约 {distance}，预计 {duration}。", ""]
    lines.append("换乘方案：")
    segments = transit.get("segments") or []
    for i, seg in enumerate(segments, 1):
        # 步行段
        walking = seg.get("walking", {})
        if walking and walking.get("steps"):
            walk_dist = _format_distance(walking.get("distance", "0"))
            lines.append(f"{i}. 步行约 {walk_dist}")
        # 公交段
        bus = seg.get("bus", {})
        buslines = bus.get("buslines") or []
        for bl in buslines:
            name = bl.get("name", "公交")
            # 提取公交站名
            dep_stop = ""
            arr_stop = ""
            if bl.get("departure_stop"):
                dep_stop = bl["departure_stop"].get("name", "")
            if bl.get("arrival_stop"):
                arr_stop = bl["arrival_stop"].get("name", "")
            if dep_stop and arr_stop:
                lines.append(f"   乘坐 {name}，从 {dep_stop} 到 {arr_stop}")
            else:
                lines.append(f"   乘坐 {name}")
    return "\n".join(lines)


@tool
def amap_direction_walking(origin: str, destination: str) -> str:
    """步行路径规划。origin 与 destination 为经纬度，返回距离、预计时间与步行步骤。"""
    if not _api_key():
        return "高德地图 API Key 未配置，无法进行路径规划。"

    data = _request_amap(_WALKING_URL, {"origin": origin, "destination": destination})
    if data.get("status") != "1":
        return f"步行路径规划失败：{data.get('info', '未知错误')}"

    route = data.get("route", {})
    paths = route.get("paths") or []
    if not paths:
        return "未获取到步行路线信息。"

    path = paths[0]
    distance = _format_distance(path.get("distance", "0"))
    duration = _format_duration(path.get("duration", "0"))
    steps = path.get("steps") or []

    lines = [f"步行路线：全程约 {distance}，预计 {duration}。", ""]
    lines.append("路线步骤：")
    for i, step in enumerate(steps, 1):
        instruction = step.get("instruction", "").strip()
        seg_dist = _format_distance(step.get("distance", "0"))
        lines.append(f"{i}. {instruction}（{seg_dist}）")
    return "\n".join(lines)


# 工具注册表
AMAP_TOOLS = {
    "amap_geocode": amap_geocode,
    "amap_direction_driving": amap_direction_driving,
    "amap_direction_transit": amap_direction_transit,
    "amap_direction_walking": amap_direction_walking,
}


def get_amap_tools(enabled: list[str] | None = None) -> list:
    """根据启用列表返回工具实例；enabled 为空则返回全部。"""
    if not enabled:
        return list(AMAP_TOOLS.values())
    return [t for name, t in AMAP_TOOLS.items() if name in enabled]

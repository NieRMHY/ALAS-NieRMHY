"""活动计算器数据服务：从 Wiki 同步活动数据并解析价格与关卡点数。"""
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List

import requests

from module.logger import logger


WIKI_RAW_URL = (
    "https://wiki.biligame.com/blhx/"
    "%E6%B4%BB%E5%8A%A8%E8%AE%A1%E7%AE%97%E5%99%A8?action=raw"
)
CACHE_FILE = "./cache/wiki_event_calculator.json"
CACHE_VERSION = 2

EVENT_SHOP_FILTER_MAP = [
    ("深潜许可", "URpt"),
    ("建造券", "GachaTicket"),
    ("魔方", "Cube"),
    ("心智单元II", "Chip"),
    ("心智单元", "Array"),
    ("外观装备箱", "SkinBox"),
    ("META", "Meta"),
    ("定向蓝图·八期", "PRS8"),
    ("高级定向蓝图·八期", "DRS8"),
    ("定向蓝图", "PR"),
    ("高级定向蓝图", "DR"),
    ("特殊兵装核心", "AugmentCoreT3"),
    ("兵装强化石T2", "AugmentEnhanceT2"),
    ("兵装重构核心T2", "AugmentChangeT2"),
    ("兵装重构核心T1", "AugmentChangeT1"),
    ("喵箱SSR", "CatT3"),
    ("喵箱SR", "CatT2"),
    ("喵箱R", "CatT1"),
    ("科技箱T4", "BoxT4"),
    ("通用部件T3", "PlateGeneralT3"),
    ("主炮部件T3", "PlateGunT3"),
    ("鱼雷部件T3", "PlateTorpedoT3"),
    ("防空炮部件T3", "PlateAntiairT3"),
    ("舰载机部件T3", "PlatePlaneT3"),
    ("物资", "Coin"),
    ("石油", "Oil"),
    ("酸素可乐", "FoodT1"),
]


def _clean_wikitext(raw: str) -> str:
    return re.sub(r"<!--.*?-->", "", raw, flags=re.S)


def _extract_table(raw: str, table_id: str) -> str:
    match = re.search(rf'\{{\|[^\n]*id="{re.escape(table_id)}"[^\n]*\n', raw)
    if match is None:
        return ""
    start = match.end()
    end_candidates = []
    for marker in ("\n{|", "\n|}", "\n=="):
        pos = raw.find(marker, start)
        if pos >= 0:
            end_candidates.append(pos)
    end = min(end_candidates) if end_candidates else len(raw)
    return raw[start:end]


def _strip_cell_attr(cell: str) -> str:
    if re.match(r'^[A-Za-z0-9_:-]+="[^"]*"\|', cell):
        return cell.split("|", 1)[1]
    return cell


def _parse_table_rows(table: str) -> List[List[str]]:
    rows: List[List[str]] = []
    for block in re.split(r"\n\|-\s*\n", table):
        cells: List[str] = []
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("!") or line.startswith("|}"):
                continue
            if line.startswith("|-"):
                continue
            if line.startswith("||"):
                cell_line = line[2:]
            elif line.startswith("|"):
                cell_line = line[1:]
            else:
                continue
            cell_line = _strip_cell_attr(cell_line.strip())
            cells.extend(part.strip() for part in cell_line.split("||"))
        if cells:
            rows.append(cells)
    return rows


def _clean_name(text: str) -> str:
    text = re.sub(r"\[\[文件:[^\]]+\]\]", "", text)
    text = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\{\{[^{}|]+\|([^{}]+?)\}\}", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("'''", "").replace("''", "")
    return text.strip()


def _to_int(value: str, default: int = 0) -> int:
    match = re.search(r"-?\d+", str(value).replace(",", ""))
    if match is None:
        return default
    return int(match.group(0))


def match_event_shop_filter(name: str, price: int, quantity: int) -> str:
    for pattern, filter_name in EVENT_SHOP_FILTER_MAP:
        if pattern in name:
            return filter_name
    if price == 8000 and quantity <= 2:
        return "ShipSSR"
    if price == 2000 and quantity == 1:
        return "EquipSSR"
    if price == 10000:
        return "EquipUR"
    return ""


def _parse_shop(rows: List[List[str]]) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        if len(row) < 3:
            continue
        price = _to_int(row[1])
        quantity = _to_int(row[2])
        if price <= 0 or quantity < 0:
            continue
        out.append(
            {
                "name": _clean_name(row[0]) or "未命名项目",
                "price": price,
                "quantity": quantity,
                "filter": match_event_shop_filter(_clean_name(row[0]), price, quantity),
            }
        )
    return out


def _extract_vardefine(raw: str, variable_name: str) -> str:
    """提取 Wiki ``#vardefine`` 变量的完整内容，保留嵌套模板。"""
    match = re.search(
        rf"\{{\{{#vardefine:\s*{re.escape(variable_name)}\s*\|", raw
    )
    if match is None:
        return ""

    start = match.end()
    depth = 1
    position = start
    while position < len(raw):
        opening = raw.find("{{", position)
        closing = raw.find("}}", position)
        if closing < 0:
            return ""
        if 0 <= opening < closing:
            depth += 1
            position = opening + 2
            continue

        depth -= 1
        if depth == 0:
            return raw[start:closing]
        position = closing + 2
    return ""


def _parse_shop_vardefine(raw: str) -> List[Dict[str, Any]]:
    """解析 Wiki 动态商店表使用的 ``_shop_items`` 变量。"""
    content = _extract_vardefine(raw, "_shop_items")
    rows = []
    for line in content.splitlines():
        row = line.rsplit(",", 2)
        if len(row) != 3:
            continue
        rows.append([cell.strip() for cell in row])
    return _parse_shop(rows)


def _parse_points(rows: List[List[str]], key_name: str) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        if len(row) < 2:
            continue
        points = _to_int(row[1])
        if points <= 0:
            continue
        out.append({"name": _clean_name(row[0]), key_name: points})
    return out


def _parse_event_name(raw: str) -> str:
    match = re.search(r"当前活动：\[\[[^\]|]+(?:\|([^\]]+))?\]\]", raw)
    if match is None:
        return ""
    return _clean_name(match.group(1) or match.group(0))


def parse_event_calculator(raw: str) -> Dict[str, Any]:
    """解析 Wiki 活动计算器页面原文。"""
    cleaned = _clean_wikitext(raw)
    time_rows = _parse_table_rows(_extract_table(cleaned, "ECALCTime"))
    end_date = time_rows[0][0] if time_rows and time_rows[0] else ""
    shop_items = _parse_shop(_parse_table_rows(_extract_table(cleaned, "ECALCPt")))
    if not shop_items:
        shop_items = _parse_shop_vardefine(cleaned)

    data = {
        "event_name": _parse_event_name(cleaned),
        "end_date": end_date.replace("/", "-"),
        "shop_items": shop_items,
        "daily": _parse_points(
            _parse_table_rows(_extract_table(cleaned, "ECALCDaily")), "points"
        ),
        "extra": _parse_points(
            _parse_table_rows(_extract_table(cleaned, "ECALCExtra")), "points"
        ),
        "stages": _parse_points(
            _parse_table_rows(_extract_table(cleaned, "ECALC")), "points"
        ),
        "source_url": WIKI_RAW_URL,
        "updated_at": datetime.now().replace(microsecond=0).isoformat(sep=" "),
    }
    data["shop_total"] = sum(
        item["price"] * item["quantity"] for item in data["shop_items"]
    )
    return data


def _read_cache() -> Dict[str, Any]:
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning(f"[WebUI-计算器] 读取Wiki活动计算器缓存失败: {e}")
        return {}


def _write_cache(data: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        data["cache_version"] = CACHE_VERSION
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[WebUI-计算器] 写入Wiki活动计算器缓存失败: {e}")


def load_event_calculator(force_refresh: bool = False) -> Dict[str, Any]:
    """读取 Wiki 活动计算器数据，失败时回退到缓存。"""
    cache = _read_cache()
    cache_valid = cache.get("cache_version") == CACHE_VERSION
    if cache and cache_valid and not force_refresh:
        return {**cache, "from_cache": True}

    try:
        response = requests.get(WIKI_RAW_URL, timeout=10)
        response.raise_for_status()
        data = parse_event_calculator(response.text)
        if not data["shop_items"] or not data["stages"]:
            raise ValueError("Wiki event calculator table is incomplete")
        _write_cache(data)
        return {**data, "from_cache": False}
    except Exception as e:
        logger.warning(f"[WebUI-计算器] 获取Wiki活动计算器失败: {e}")
        if cache:
            return {**cache, "from_cache": True, "error": str(e)}
        return {"error": str(e), "from_cache": False}

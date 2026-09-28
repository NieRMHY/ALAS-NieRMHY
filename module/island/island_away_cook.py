"""岛屿「常驻餐品」自动轮换（Add by MHY）。

背景：ALAS 的店铺生产只做「货架补货」，补完之后剩下的空闲岗位交给
「常驻餐品」（Island<店>NextTask.AwayCook）填充；没配置就地空转。
真机日志：一天出现 20 次「有空闲岗位」，其中 14 次是「未设置特殊餐品
或常驻餐品，保持空闲」——纯浪费产能。

本模块按**赛季开发计划的缺口**挑常驻餐品：谁差得多就先产谁，攒够自动
换下一个。产能口径按 WorkerJuu（wiki 基础工时），与方案生成器一致。

纯逻辑部分可离线单测；写配置由调用方（经营端库存校验）在读到仓库库存后触发。
"""
from module.island.island_economy import ECONOMY_PRODUCTS
from module.island.island_season_plan_data import SEASON_PLAN_TASKS

# 店铺类型 -> 常驻餐品配置键
# 路径格式 <Task>.<Group>.<Arg>，与 config/template.json 一致
AWAY_COOK_KEYS = {
    'restaurant': 'IslandRestaurant.IslandRestaurantNextTask.AwayCook',
    'teahouse': 'IslandTeahouse.IslandTeahouseNextTask.AwayCook',
    'juu_eatery': 'IslandJuuEatery.IslandJuuEateryNextTask.AwayCook',
    'grill': 'IslandGrill.IslandGrillNextTask.AwayCook',
    'juu_coffee': 'IslandJuuCoffee.IslandJuuCoffeeNextTask.AwayCook',
}


def season_items_for_shop(shop, season):
    """
    该店在赛季任务里要交的物品。

    Args:
        shop: 店铺类型标识
        season: 赛季

    Returns:
        list[(物品, 需要数量, 单件工时)]
    """
    result = []
    for _, item, need in SEASON_PLAN_TASKS.get(season, []):
        info = ECONOMY_PRODUCTS.get(item)
        if info and info['shop'] == shop:
            result.append((item, need, info['time_min']))
    return result


def pick_away_cook(shop, season, counts, producible=None, exclude=None):
    """
    挑该店的常驻餐品：赛季缺口最大的物品优先。

    缺口按「还差多少件」算，同缺口时取单件工时短的（更快补上一个任务）。

    Args:
        shop: 店铺类型标识
        season: 赛季
        counts: {物品: 仓库库存}
        producible: 可生产集合；None 不限制
        exclude: 排除集合（未解锁商品等）

    Returns:
        str: 物品英文名；没有缺口或没有可生产的返回 'None'
    """
    exclude = set(exclude or ())
    best, best_key = None, None
    for item, need, time_min in season_items_for_shop(shop, season):
        if producible is not None and item not in producible:
            continue
        if item in exclude:
            continue
        gap = need - int(counts.get(item, 0))
        if gap <= 0:
            continue
        key = (-gap, time_min)
        if best_key is None or key < best_key:
            best, best_key = item, key
    return best or 'None'


def rotation_key(shop):
    """该店常驻餐品对应的配置键。"""
    return AWAY_COOK_KEYS.get(shop)


DEFAULT_FILE = 'config/island_away_cook_default.json'


def load_defaults(path=DEFAULT_FILE):
    """读取用户原本的常驻餐品设置（轮换前的值）。"""
    import json
    import os
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_defaults(defaults, path=DEFAULT_FILE):
    """记录用户原本的常驻餐品设置，赛季物品攒够后好还原。"""
    import json
    import os
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(defaults, f, ensure_ascii=False, indent=2, sort_keys=True)


def resolve_away_cook(shop, season, counts, current, defaults=None, producible=None,
                      exclude=None):
    """
    决定该店常驻餐品该写什么，并维护「用户原值」备份。

    规则：
      - 有赛季缺口 -> 写缺口最大的赛季物品，同时把用户原值记进 defaults
      - 没有缺口   -> 还原用户原值（例如餐馆的豆腐），避免赛季物品攒够后
                      岗位又空转

    Args:
        shop: 店铺类型标识
        season: 赛季
        counts: {物品: 仓库库存}
        current: 当前配置值
        defaults: {店铺: 用户原值}
        producible: 可生产集合
        exclude: 排除集合

    Returns:
        tuple: (要写入的值, 更新后的 defaults)
    """
    defaults = dict(defaults or {})
    target = pick_away_cook(shop, season, counts,
                            producible=producible, exclude=exclude)
    if target != 'None':
        if shop not in defaults:
            defaults[shop] = current
        return target, defaults
    if shop in defaults:
        original = defaults.pop(shop)
        return original, defaults
    return current, defaults

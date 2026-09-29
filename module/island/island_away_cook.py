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


NOTIFIED_FILE = 'config/island_season_notified.json'


def load_notified(path=NOTIFIED_FILE):
    """读取「已通知过攒够」的赛季物品记录：{赛季: {物品: True}}。"""
    import json
    import os
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_notified(notified, path=NOTIFIED_FILE):
    """保存通知记录，避免同一件物品反复发邮件。"""
    import json
    import os
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(notified, f, ensure_ascii=False, indent=2, sort_keys=True)


def collect_finished(shop, season, counts, notified):
    """
    找出「刚攒够、还没通知过」的赛季物品；用户提交后数量掉下来则重置记录。

    Args:
        shop: 店铺类型标识
        season: 赛季
        counts: {物品: 仓库库存}
        notified: load_notified() 的结果（会被就地修改）

    Returns:
        list[(物品, 需要数量, 当前库存)]: 需要发通知的物品
    """
    season_state = notified.setdefault(season, {})
    finished = []
    for item, need, _ in season_items_for_shop(shop, season):
        have = int(counts.get(item, 0))
        if have >= need:
            if not season_state.get(item):
                season_state[item] = True
                finished.append((item, need, have))
        elif season_state.pop(item, None):
            # 用户提交后数量下降，重新计数，下次攒够再提醒
            pass
    return finished


def notify_finished(config, shop, season, counts):
    """
    赛季任务物品攒够时推送通知（走 Error_OnePushConfig，配 smtp 即邮件）。

    调用点有两处：经营端库存校验（4-6 小时一次）与店铺仓库读取
    （店铺任务 20-40 分钟一次），后者让提醒更及时。

    Args:
        config: AzurLaneConfig 实例
        shop: 店铺类型标识
        season: 赛季
        counts: {物品: 仓库库存}

    Returns:
        list[str]: 本次通知的物品
    """
    from module.island.island_season_plan_data import cn_name, task_of_item
    from module.logger import logger
    from module.notify.notify import handle_notify

    if not season:
        return []
    notified = load_notified()
    finished = collect_finished(shop, season, counts, notified)
    if not finished:
        return []
    save_notified(notified)
    for item, need, have in finished:
        task, _ = task_of_item(item, season)
        logger.info(f"[岛屿-赛季任务] {cn_name(item)} 已攒够 {have}/{need}，推送提醒")
        handle_notify(
            config.Error_OnePushConfig,
            title='岛屿赛季任务物品已攒够',
            content=f"<{config.config_name}> 赛季任务「{task or item}」"
                    f"需要的 {cn_name(item)} 已攒够：{have}/{need}，"
                    f"可以去岛屿「开发季」提交了",
        )
    return [item for item, _, _ in finished]


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

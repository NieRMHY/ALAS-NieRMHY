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
from module.island.island_state import state_file

# 店铺类型 -> 常驻餐品配置键
# 路径格式 <Task>.<Group>.<Arg>，与 config/template.json 一致
AWAY_COOK_KEYS = {
    'restaurant': 'IslandRestaurant.IslandRestaurantNextTask.AwayCook',
    'teahouse': 'IslandTeahouse.IslandTeahouseNextTask.AwayCook',
    'juu_eatery': 'IslandJuuEatery.IslandJuuEateryNextTask.AwayCook',
    'grill': 'IslandGrill.IslandGrillNextTask.AwayCook',
    'juu_coffee': 'IslandJuuCoffee.IslandJuuCoffeeNextTask.AwayCook',
}


def season_items_for_shop(shop, season, slots=None):
    """
    该店在赛季任务里要交的物品。

    Modify by MHY, 清单来自配置槽位（IslandSeasonPlan.Item/Need/Done）：已标记完成或
    需求为 0 的槽位不在其中，所以不会再被轮换成常驻餐品。没传 slots 时退回代码里的
    赛季表（离线测试与新赛季预置用）。

    Args:
        shop: 店铺类型标识
        season: 赛季
        slots: island_season_progress.read_slots() 的结果；None 用赛季表

    Returns:
        list[(物品, 需要数量, 单件工时)]
    """
    if slots is not None:
        pairs = [(s['item'], s['need']) for s in slots if not s['done'] and s['need'] > 0]
    else:
        pairs = [(item, need) for _, item, need in SEASON_PLAN_TASKS.get(season, [])]
    result = []
    for item, need in pairs:
        info = ECONOMY_PRODUCTS.get(item)
        if info and info['shop'] == shop:
            result.append((item, need, info['time_min']))
    return result


def pick_away_cook(shop, season, counts, producible=None, exclude=None, skip=None, slots=None):
    """
    挑该店的常驻餐品：赛季缺口最大的物品优先。

    缺口按「还差多少件」算，同缺口时取单件工时短的（更快补上一个任务）。
    已确认提交完成的任务物品会被跳过，不再重复生产。

    Args:
        shop: 店铺类型标识
        season: 赛季
        counts: {物品: 仓库库存}
        producible: 可生产集合；None 不限制
        exclude: 排除集合（未解锁商品等）
        skip: 已完成的物品集合（本季不再生产）
        slots: 配置槽位；已完成的槽位不参与

    Returns:
        str: 物品英文名；没有缺口或没有可生产的返回 'None'
    """
    exclude = set(exclude or ()) | set(skip or ())
    best, best_key = None, None
    for item, need, time_min in season_items_for_shop(shop, season, slots):
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


DEFAULT_FILE = state_file('island_away_cook_default.json')


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


NOTIFIED_FILE = state_file('island_season_notified.json')


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


def _state_entry(state, item):
    """
    取物品的提醒状态，兼容早期版本写的 {物品: True} 格式。

    Args:
        state: {物品: 状态} 字典（就地更新）
        item: 物品英文名

    Returns:
        dict: {'notified': bool}
    """
    value = state.get(item)
    if value is True:
        entry = {'notified': True}
    elif isinstance(value, dict):
        entry = {'notified': bool(value.get('notified'))}
    else:
        entry = {'notified': False}
    state[item] = entry
    return entry


def is_shop_product(item):
    """
    是否是店铺生产的餐品（相对农田/牧场的材料而言）。

    材料类任务（小麦/牧草/大豆/大米/玉米/胡萝卜/牛奶/洋葱）在农田牧场长期溢出，
    用户明确说这部分不需要规划；对它们提醒「可以提交」只会刷屏（真机踩过：
    一次运行发了 8 封，其中 7 封是材料）。

    Args:
        item: 物品键

    Returns:
        bool: 有对应店铺的餐品返回 True
    """
    from module.island.island_economy import ECONOMY_PRODUCTS
    return bool(item) and item in ECONOMY_PRODUCTS


def notify_ready_from_progress(config, season, progress):
    """
    赛季进度达标时推送提醒（每项只提醒一次，进度回落后复位）。

    Modify by MHY, 进度来自仓库读数（见 island_season_progress），不再依赖赛季页 OCR。
    提醒的是「仓库里已经攒够了」，具体是否已提交以你为准：提交任务后仓库数量
    掉下去，物品自然回到缺口，复位 notified，下次攒够会再提醒。

    Args:
        config: AzurLaneConfig 实例
        season: 赛季
        progress: {物品: [当前数量, 需求数量]}

    Returns:
        list[str]: 本次提醒的物品
    """
    from module.island.island_season_plan_data import cn_name, task_of_item
    from module.logger import logger
    from module.notify.notify import handle_notify, notify_title

    if not season or not progress:
        return []
    # 总开关：关闭后完全不发邮件（提交过的任务仓库数量仍可能高于需求，会反复打扰）
    if not config.cross_get('IslandSeasonPlan.IslandSeasonPlan.NotifyEnable', default=True):
        return []
    notified = load_notified()
    state = notified.setdefault(season, {})
    dirty = False
    ready = []
    for item, (have, need) in sorted(progress.items()):
        entry = _state_entry(state, item)
        if not need or have < need:
            # 进度回落（提交后掉下去、或需求被调高）：复位，下次攒够再提醒
            if entry['notified']:
                entry['notified'] = False
                dirty = True
            continue
        if entry['notified'] or not is_shop_product(item):
            continue
        entry['notified'] = True
        dirty = True
        ready.append((item, have, need))
    if dirty:
        save_notified(notified)
    if not ready:
        return []
    lines = []
    for item, have, need in ready:
        task, _ = task_of_item(item, season)
        lines.append(f"{task or cn_name(item)}（{cn_name(item)} {have}/{need}）")
    logger.info(f"[岛屿-赛季任务] {len(ready)} 项已达标，推送提醒: {'、'.join(lines)}")
    content = (f"<{config.config_name}> 赛季任务已达标："
               + '\n' + '\n'.join(lines)
               + '\n可以去岛屿「开发季」提交了')
    handle_notify(
        config.Error_OnePushConfig,
        title=notify_title(config.config_name, '岛屿', f'{len(ready)} 项赛季任务可以提交'),
        content=content,
    )
    return [item for item, _, _ in ready]


def resolve_away_cook(shop, season, counts, current, defaults=None, producible=None,
                      exclude=None, skip=None, slots=None):
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
                            producible=producible, exclude=exclude, skip=skip, slots=slots)
    if target != 'None':
        if shop not in defaults:
            defaults[shop] = current
        return target, defaults
    if shop in defaults:
        original = defaults.pop(shop)
        return original, defaults
    return current, defaults

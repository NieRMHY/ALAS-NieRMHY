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


def pick_away_cook(shop, season, counts, producible=None, exclude=None, skip=None):
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

    Returns:
        str: 物品英文名；没有缺口或没有可生产的返回 'None'
    """
    exclude = set(exclude or ()) | set(skip or ())
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


SUBMIT_RATIO = 0.9  # 单次扣减达到需求量的 90% 即认定为「已提交任务」
# 连续漏读多少次才取消 done（Add by MHY）：徽章漏读远多于误读，一次漏读不该打掉状态
CLAIM_MISS_LIMIT = 2


def _state_entry(state, item):
    """
    取物品状态，兼容早期版本写的 {物品: True} 格式。

    Args:
        state: {物品: 状态} 字典（就地更新）
        item: 物品英文名

    Returns:
        dict: {'notified': bool, 'last': int, 'done': bool, 'miss': int}
    """
    value = state.get(item)
    if value is True:
        entry = {'notified': True, 'last': 0, 'done': False}
    elif isinstance(value, dict):
        entry = {'notified': bool(value.get('notified')),
                 'last': int(value.get('last', 0)),
                 'done': bool(value.get('done'))}
    else:
        entry = {'notified': False, 'last': 0, 'done': False}
    # 连续漏读计数（Add by MHY），见 mark_claimed
    entry['miss'] = int(value.get('miss', 0)) if isinstance(value, dict) else 0
    state[item] = entry
    return entry


def is_done(season, item, notified):
    """
    该赛季任务物品是否已确认提交完成（本季不再生产）。

    Args:
        season: 赛季
        item: 物品英文名
        notified: 状态字典

    Returns:
        bool
    """
    entry = (notified.get(season) or {}).get(item)
    if isinstance(entry, dict):
        return bool(entry.get('done'))
    return False


def done_items(season, notified):
    """该赛季已完成的物品集合（轮换时跳过）。"""
    state = notified.get(season) or {}
    return {item for item in state if is_done(season, item, notified)}


def mark_claimed(season, page_result, notified):
    """
    用页面读取结果同步「已完成」状态。

    页面是真相来源：带「已领取」标记的物品即任务已提交，本季不再生产；
    页面可见但未领取的物品要取消 done（避免旧的库存掉幅误判一直生效）。

    Args:
        season: 赛季
        page_result: {任务名: {'item', 'have', 'need', 'claimed'}}
        notified: load_notified() 的结果（会被就地修改）

    Returns:
        dict: {物品: '已领取'/'取消'} 本次发生变化的项
    """
    state = notified.setdefault(season, {})
    changed = {}
    for info in page_result.values():
        item = info.get('item')
        if not item:
            continue
        entry = _state_entry(state, item)
        if info.get('claimed') is None:
            # 徽章被屏幕下沿裁掉，状态未知：既不能记已领取，也不能抵消 done
            continue
        claimed = bool(info.get('claimed'))
        if claimed:
            entry['miss'] = 0
            if not entry['done']:
                entry['done'] = True
                entry['notified'] = False
                changed[item] = '已领取'
        elif entry['done']:
            # Add by MHY, 单次漏读不取消 done：「已领取」徽章漏读远多于误读（真机
            # 32 次读里 28 次漏读）。一次漏读就把 done 打掉，会让已提交的物品重新
            # 投入生产，同时让 notified 的抑制失效、重复发「可以提交」邮件。
            entry['miss'] = entry.get('miss', 0) + 1
            if entry['miss'] >= CLAIM_MISS_LIMIT:
                entry['done'] = False
                entry['miss'] = 0
                changed[item] = '取消'
    return changed


def collect_finished(shop, season, counts, notified):
    """
    找出「刚攒够、还没通知过」的赛季物品，并识别「已提交」。

    提交任务会一次性扣掉正好 need 个物品（例如 100 个蔬菜沙拉），而货运/订单
    的零星消耗是渐变的，所以用相邻两次读数判断：上次已攒够、这次掉到需求以下、
    且单次掉幅达到需求量的 90%，即认定任务已提交，本季不再生产。

    Args:
        shop: 店铺类型标识
        season: 赛季
        counts: {物品: 仓库库存}
        notified: load_notified() 的结果（会被就地修改）

    Returns:
        list[(物品, 需要数量, 当前库存)]: 需要发通知的物品
    """
    from module.logger import logger

    season_state = notified.setdefault(season, {})
    finished = []
    for item, need, _ in season_items_for_shop(shop, season):
        have = int(counts.get(item, 0))
        entry = _state_entry(season_state, item)
        if entry['done']:
            continue
        if have >= need:
            if not entry['notified']:
                entry['notified'] = True
                finished.append((item, need, have))
        elif entry['notified'] and entry['last'] - have >= need * SUBMIT_RATIO:
            entry['done'] = True
            entry['notified'] = False
            logger.info(f"[岛屿-赛季任务] {item} 数量 {entry['last']} -> {have}，"
                        f"判定为已提交任务，本季不再生产")
        else:
            # 数量掉到需求以下（被消耗），重新攒够再提醒
            entry['notified'] = False
        entry['last'] = have
    return finished


def ready_to_submit(season, page_result):
    """
    从页面结果里挑出「已达标但还没领取」的任务（可以去提交了）。

    Args:
        season: 赛季
        page_result: {任务名: {'item', 'have', 'need', 'claimed'}}

    Returns:
        list[(任务名, 物品, 当前数量, 需要数量)]
    """
    ready = []
    for task, info in sorted(page_result.items()):
        # Add by MHY, 只有「确定未领取」（claimed is False）才算可提交：
        # claimed 为 None 表示徽章被屏幕下沿裁掉、状态未知，不能据此判定
        if info.get('claimed') is not False:
            continue
        need = int(info.get('need') or 0)
        have = int(info.get('have') or 0)
        if need and have >= need:
            ready.append((task, info.get('item'), have, need))
    return ready


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


def notify_ready_from_page(config, season, page_result):
    """
    页面显示任务已达标但未领取时推送提醒（每项只提醒一次）。

    页面是真相来源：仓库读数可能被每日订单/货运消耗影响，而页面显示的是
    任务本身的进度。

    Args:
        config: AzurLaneConfig 实例
        season: 赛季
        page_result: 页面读取结果

    Returns:
        list[str]: 本次提醒的任务名
    """
    from module.island.island_season_plan_data import cn_name
    from module.logger import logger
    from module.notify.notify import handle_notify, notify_title

    if not season:
        return []
    notified = load_notified()
    state = notified.setdefault(season, {})
    # Add by MHY, 页面读数没达标的物品要复位 notified：10-10 拿铁真实 82/100 被误读成
    # 282/100，错发了一次达标邮件并把 notified 留成 True，之后真攒够 100 时提醒会被
    # 吞掉。只复位页面上确定未领取（claimed is False）且读数不足的项；
    # 必须在「没有达标项就提前返回」之前做，否则恰好没有达标项时永远复位不了。
    reset = False
    for info in page_result.values():
        item = info.get('item')
        if not item or info.get('claimed') is not False:
            continue
        need = int(info.get('need') or 0)
        if need and int(info.get('have') or 0) < need:
            entry = state.get(item)
            if isinstance(entry, dict) and entry.get('notified'):
                entry['notified'] = False
                reset = True
    ready = ready_to_submit(season, page_result)
    if not ready:
        if reset:
            save_notified(notified)
        return []
    fired = []
    lines = []
    for task, item, have, need in ready:
        # 材料类不提醒：农田牧场长期溢出，提醒只会刷屏（真机一次发了 8 封）
        if not is_shop_product(item):
            continue
        entry = _state_entry(state, item)
        if entry['notified']:
            continue
        entry['notified'] = True
        entry['last'] = have
        fired.append(task)
        lines.append(f"{task}（{cn_name(item)} {have}/{need}）")
    if fired:
        # 合并成一封：一项一封会把收件箱刷爆（真机一次 8 封）
        logger.info(f"[岛屿-赛季任务] {len(fired)} 项已达标，推送提醒: {'、'.join(fired)}")
        content = (f"<{config.config_name}> 赛季任务已达标："
                   + '\n' + '\n'.join(lines)
                   + '\n可以去岛屿「开发季」提交了')
        handle_notify(
            config.Error_OnePushConfig,
            title=notify_title(config.config_name, '岛屿',
                               f'{len(fired)} 项赛季任务可以提交'),
            content=content,
        )
        save_notified(notified)
    return fired



def resolve_away_cook(shop, season, counts, current, defaults=None, producible=None,
                      exclude=None, skip=None):
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
                            producible=producible, exclude=exclude, skip=skip)
    if target != 'None':
        if shop not in defaults:
            defaults[shop] = current
        return target, defaults
    if shop in defaults:
        original = defaults.pop(shop)
        return original, defaults
    return current, defaults

"""赛季任务进度：仓库读数 + 配置槽位（Add by MHY）。

为什么不再 OCR 赛季页：开发计划页的进度文字会被误读（拿铁 82 读成 282），而邮件、
方案刷新、常驻餐品轮换都依赖这个数。店铺每次收取生产、核对销售前都会进仓库读准确库存，
所以「当前数量」直接取仓库读数（读数不进配置，只存在内存/日志里，见 island_season_state）。

配置是 10 个槽位，每个槽位三项：
    Item{n}   选哪件餐品（下拉）
    Need{n}   任务要交多少（输入）
    Done{n}   已完成（开关）。勾选后该项不再排产、不再发邮件，空闲产能自动转去做下一个缺口最大的

槽位全空时按当前赛季表预置（秋季 8 项）；你改过任一槽位就不再覆盖。换赛季时清空槽位
（物品选「无」）即可重新预置，代码里的赛季表（SEASON_PLAN_TASKS）是新赛季的初始建议值。
"""
import json
import os

from module.island.island_season_plan_data import SEASON_PLAN_TASKS
from module.island.island_state import state_file
from module.logger import logger

# 物品 -> 最近一次仓库读数。读数不进配置（不让你编辑、也不触发配置保存），落在状态文件里，
# 因为每个店铺任务只读自己那几件物品，进程又会反复启停。
HAVE_FILE = state_file('island_season_have.json')
SLOT_COUNT = 10
GROUP = 'IslandSeasonPlan.IslandSeasonPlan'
NOTIFY_KEY = f'{GROUP}.NotifyEnable'


def slot_keys(n):
    """第 n 个槽位的三个配置键。"""
    return f'{GROUP}.Item{n}', f'{GROUP}.Need{n}', f'{GROUP}.Done{n}'


def default_slots(season, shop_items):
    """
    赛季表里店铺餐品类任务，作为槽位初始建议值。

    Args:
        season: 赛季
        shop_items: 店铺餐品物品集合（材料类交给农田牧场，不进槽位）

    Returns:
        list[(物品, 需求数量)]
    """
    return [(item, need) for _, item, need in SEASON_PLAN_TASKS.get(season, [])
            if item in shop_items][:SLOT_COUNT]


def read_slots(config):
    """
    读取配置里的槽位。

    Returns:
        list[dict]: [{'n': 槽位号, 'item': 物品, 'need': 需求, 'done': 是否完成}]，
            只含已选择物品的槽位
    """
    slots = []
    for n in range(1, SLOT_COUNT + 1):
        k_item, k_need, k_done = slot_keys(n)
        item = config.cross_get(k_item, default='None')
        if not item or item == 'None':
            continue
        try:
            need = max(int(config.cross_get(k_need, default=0) or 0), 0)
        except (TypeError, ValueError):
            need = 0
        slots.append({'n': n, 'item': item, 'need': need,
                      'done': bool(config.cross_get(k_done, default=False))})
    return slots


def ensure_slots(config, season, shop_items):
    """
    槽位全空时按赛季表预置，返回最新槽位。

    只在「一个槽位都没选」时预置：你改过任一槽位就不会被覆盖。预置通过
    cross_set_many 走配置自己的保存事务，不直接改文件。

    Args:
        config: AzurLaneConfig 实例
        season: 赛季
        shop_items: 店铺餐品物品集合

    Returns:
        list[dict]: read_slots() 的结果
    """
    slots = read_slots(config)
    if slots:
        return slots
    defaults = default_slots(season, shop_items)
    if not defaults:
        return []
    values = {}
    for n, (item, need) in enumerate(defaults, start=1):
        k_item, k_need, k_done = slot_keys(n)
        values.update({k_item: item, k_need: need, k_done: False})
    config.cross_set_many(values)
    try:
        config.update()
    except Exception:
        logger.exception('[岛屿-赛季进度] 槽位预置保存失败')
    logger.info(f'[岛屿-赛季进度] 槽位为空，已按 {season} 赛季表预置 {len(defaults)} 项')
    return read_slots(config)


def active_slots(slots):
    """未标记完成、且需求大于 0 的槽位（参与排产与提醒）。"""
    return [s for s in slots if not s['done'] and s['need'] > 0]


def build_progress(slots, have):
    """
    槽位 + 当前数量 -> 进度字典，供排产/提醒使用。

    已完成的槽位整体排除；这样已完成项即便仓库数量掉下去也不会被重新排产。

    Args:
        slots: read_slots() 的结果
        have: {物品: 当前数量}（仓库读数）

    Returns:
        dict: {物品: [当前数量, 需求数量]}
    """
    progress = {}
    for slot in active_slots(slots):
        progress[slot['item']] = [int(have.get(slot['item'], 0)), slot['need']]
    return progress


def ready_items(progress):
    """已达标（当前 >= 需求）的物品：[(物品, 当前, 需求)]。"""
    return [(item, h, n) for item, (h, n) in sorted(progress.items()) if n and h >= n]


def gaps(progress):
    """未达标项：{物品: (当前, 需求)}。"""
    return {item: (h, n) for item, (h, n) in progress.items() if n and h < n}


def load_have(path=None):
    """读取各物品最近一次仓库读数：{物品: 数量}。"""
    path = path or HAVE_FILE
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: int(v) for k, v in data.items() if isinstance(v, (int, float))}


def record_readings(readings, path=None):
    """
    记录本次仓库读数（直接覆盖，不累加、不封顶），返回变化项。

    只记真实读数：-1 表示库存未知（没有仓库模板），不能当成 0 覆盖。

    Args:
        readings: {物品: 仓库读数}

    Returns:
        dict: {物品: (旧, 新)}
    """
    path = path or HAVE_FILE
    have = load_have(path)
    changed = {}
    for item, count in (readings or {}).items():
        if count is None or count < 0:
            continue
        count = int(count)
        if have.get(item) != count:
            changed[item] = (have.get(item), count)
            have[item] = count
    if not changed:
        return {}
    try:
        directory = os.path.dirname(path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(have, f, ensure_ascii=False, indent=2, sort_keys=True)
    except OSError:
        logger.warning('[岛屿-赛季进度] 仓库读数落盘失败')
    return changed

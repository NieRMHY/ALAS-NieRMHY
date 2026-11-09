"""赛季任务进度：赛季表（代码）+ 配置（需求/已完成）+ 仓库读数（Add by MHY）。

为什么不再 OCR 赛季页：开发计划页的进度文字会被误读（拿铁 82 读成 282），而邮件、
方案刷新、常驻餐品轮换都依赖这个数。店铺每次收取生产、核对销售前都会进仓库读准确库存，
所以「当前数量」直接取仓库读数（不进配置，见 HAVE_FILE）。

三类数据各管各的：
    餐品清单    代码里的赛季表 SEASON_PLAN_TASKS（新赛季上线时由代码更新，用户不选）
    需求数量    配置 Need_<物品>，默认取赛季表，可改
    已完成      配置 Done_<物品>，勾选后该项不再排产、不再发邮件，空闲产能转去做下一个

换赛季时只需在赛季表里换餐品并在 argument.yaml 为新餐品追加 Need_/Done_ 两项；
配置里没有对应键的餐品（旧赛季遗留）读不到配置，按赛季表默认值、未完成处理。
"""
import json
import os

from module.island.island_season_plan_data import SEASON_PLAN_TASKS
from module.island.island_state import state_file
from module.logger import logger

# 物品 -> 最近一次仓库读数。读数不进配置（不让你编辑、也不触发配置保存），落在状态文件里，
# 因为每个店铺任务只读自己那几件物品，进程又会反复启停。
HAVE_FILE = state_file('island_season_have.json')
GROUP = 'IslandSeasonPlan.IslandSeasonPlan'
NOTIFY_KEY = f'{GROUP}.NotifyEnable'


def need_key(item):
    """物品的需求数量配置键。"""
    return f'{GROUP}.Need_{item}'


def done_key(item):
    """物品的已完成配置键。"""
    return f'{GROUP}.Done_{item}'


def season_dishes(season, shop_items):
    """
    当前赛季表里的店铺餐品：[(物品, 默认需求数量)]。

    材料类（小麦、牛奶等）没有对应店铺，交给农田牧场，不在其中。

    Args:
        season: 赛季
        shop_items: 店铺餐品物品集合（经济库）
    """
    return [(item, need) for _, item, need in SEASON_PLAN_TASKS.get(season, [])
            if item in shop_items]


def read_slots(config, season, shop_items):
    """
    读取当前赛季每个餐品的需求数量与已完成状态。

    Args:
        config: AzurLaneConfig 实例
        season: 赛季
        shop_items: 店铺餐品物品集合

    Returns:
        list[dict]: [{'item', 'need', 'done'}]，顺序同赛季表；配置读不到时用赛季表默认值
    """
    slots = []
    for item, default_need in season_dishes(season, shop_items):
        raw = config.cross_get(need_key(item), default=default_need)
        try:
            need = max(int(raw if raw is not None else default_need), 0)
        except (TypeError, ValueError):
            need = default_need
        slots.append({'item': item, 'need': need,
                      'done': bool(config.cross_get(done_key(item), default=False))})
    return slots


def active_slots(slots):
    """未标记完成、且需求大于 0 的餐品（参与排产与提醒）。"""
    return [s for s in slots if not s['done'] and s['need'] > 0]


def build_progress(slots, have):
    """
    餐品清单 + 当前数量 -> 进度字典，供排产/提醒使用。

    已完成的餐品整体排除；这样已完成项即便仓库数量掉下去也不会被重新排产。

    Args:
        slots: read_slots() 的结果
        have: {物品: 当前数量}（仓库读数）

    Returns:
        dict: {物品: [当前数量, 需求数量]}
    """
    return {s['item']: [int(have.get(s['item'], 0)), s['need']] for s in active_slots(slots)}


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

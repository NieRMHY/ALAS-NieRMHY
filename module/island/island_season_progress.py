"""赛季任务进度：赛季表（代码）+ 配置（需求/已完成）+ 仓库读数（Add by MHY）。

为什么不再 OCR 赛季页：开发计划页的进度文字会被误读（拿铁 82 读成 282），而邮件、
方案刷新、常驻餐品轮换都依赖这个数。店铺每次收取生产、核对销售前都会进仓库读准确库存，
所以「当前数量」直接取仓库读数（不进配置，见 HAVE_FILE）。

三类数据各管各的：
    餐品清单    代码里的赛季表 SEASON_PLAN_TASKS（新赛季上线时由代码更新，用户不选）
    需求数量    配置 Need_<物品>，默认取赛季表，可改
    已完成      配置 Done_<物品>，勾选后该项不再排产、不再发邮件，空闲产能转去做下一个

换赛季时更新赛季表与 argument.yaml 的餐品 Need_/Done_，同时移除过季配置；
配置里没有对应键的餐品（旧赛季遗留）读不到配置，按赛季表默认值、未完成处理。

冬季餐品另受 IslandSeasonPlan.WinterTaskEnabled 控制（read_slots 关闭时返回空列表）。
自然资源由 island_winter_resources 持续维持库存，无完成标记，不进入本模块的餐品提醒。
仓库读数缺失、None、负数、非数字与非有限值（NaN/inf）都是「未知」：不当 0、不算达标，
也不触发缺口刷新；需要区分「未知」与「0」的调用方用 build_progress(..., with_known=True)
或 progress_values。
"""
import json
import math
import os
from datetime import datetime

# Modify by MHY, 统一解析数量与完成标记，避免 "200.0" 回退默认值、"false" 误判完成。
from module.island.island_season_plan_data import (
    CONFIG_GROUP,
    SEASON_PLAN_TASKS,
    _as_bool,
    configured_need,
    winter_task_enabled,
)
from module.island.island_state import state_file
from module.logger import logger

# 物品 -> 最近一次仓库读数。读数不进配置（不让你编辑、也不触发配置保存），落在状态文件里，
# 因为每个店铺任务只读自己那几件物品，进程又会反复启停。
HAVE_FILE = state_file('island_season_have.json')
# Modify by MHY, 与 configured_need 共用同一命名空间常量，赛季表分组改名时不会两处漂移。
GROUP = CONFIG_GROUP
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

    Modify by MHY, 冬季另有总开关 WinterTaskEnabled：关掉时返回空列表，
    冬季任务进度、提醒与排产增量随之停止；日常排产继续，货架与闲时生产设置保持原样。

    Args:
        config: AzurLaneConfig 实例
        season: 赛季
        shop_items: 店铺餐品物品集合

    Returns:
        list[dict]: [{'item', 'need', 'done'}]，顺序同赛季表；配置读不到或非法时用赛季表默认值。
            Need_/Done_ 按 island_season_plan_data 的语义转换，"200.0"、"false" 这类字符串同样有效
    """
    if season == 'winter' and not winter_task_enabled(config):
        logger.info('[岛屿-赛季任务] WinterTaskEnabled 已关闭，冬季任务不参与进度与提醒')
        return []
    slots = []
    for item, default_need in season_dishes(season, shop_items):
        slots.append({'item': item,
                      'need': configured_need(config, item, default_need),
                      'done': _as_bool(config.cross_get(done_key(item), default=False),
                                       default=False)})
    return slots


def active_slots(slots):
    """未标记完成、且需求大于 0 的餐品（参与排产与提醒）。"""
    return [s for s in slots if not s['done'] and s['need'] > 0]


def stock_reading(value):
    """
    仓库读数归一化成非负整数；未知返回 None。

    未知包括 None、负数（-1 是「没有仓库模板」的约定，见 island_business_stock）、
    非数字与 NaN、无穷大。未知不等于 0：既不能当成库存已清空，也不能当成已经达标。
    """
    if value is None or isinstance(value, bool):
        return None
    # Modify by MHY, 超大整数转换溢出与非有限读数都按未知处理。
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    # inf 能通过 float()，但 int(inf) 会 OverflowError，未知读数保持 None
    if not math.isfinite(number) or number < 0:
        return None
    return int(number)


def progress_values(entry):
    """
    进度条目 -> (当前数量或 None, 需求数量)。

    兼容旧的两项 [当前, 需求] 与带 known 标志的 [当前, 需求, 是否已知]；
    未知库存返回 None，调用方不能把它当 0，也不能算达标。
    """
    have = entry[0]
    need = entry[1]
    known = entry[2] if len(entry) > 2 else True
    return (stock_reading(have) if known else None), need


def build_progress(slots, have, with_known=False):
    """
    餐品清单 + 当前数量 -> 进度字典，供排产/提醒使用。

    已完成的餐品整体排除；这样已完成项即便仓库数量掉下去也不会被重新排产。
    读数未知（缺失/None/负数）的餐品默认不进进度：未知既不是 0，也不能算达标，
    否则没读过仓库就会显示「0/需求」并触发缺口刷新。需要区分「未知」与「0」的
    调用方传 with_known=True，未达标项仍在键里，条目变成三项并带 known 标志。

    Args:
        slots: read_slots() 的结果
        have: {物品: 当前数量}（仓库读数，未知用 None/-1 表示）
        with_known: 是否保留未知项并附带 known 标志

    Returns:
        dict: {物品: [当前数量, 需求数量]}；
            with_known=True 时为 {物品: [当前数量或 None, 需求数量, 是否已知]}
    """
    progress = {}
    for s in active_slots(slots):
        item = s['item']
        reading = stock_reading(have.get(item))
        if reading is None:
            if with_known:
                progress[item] = [None, s['need'], False]
            continue
        progress[item] = [reading, s['need'], True] if with_known else [reading, s['need']]
    return progress


def ready_items(progress):
    """已达标（已知当前 >= 需求）的物品：[(物品, 当前, 需求)]；未知读数不算达标。"""
    ready = []
    for item, entry in sorted(progress.items()):
        have, need = progress_values(entry)
        if need and have is not None and have >= need:
            ready.append((item, have, need))
    return ready


def gaps(progress):
    """未达标项：{物品: (当前, 需求)}；未知读数不当 0，也不算缺口。"""
    result = {}
    for item, entry in progress.items():
        have, need = progress_values(entry)
        if need and have is not None and have < need:
            result[item] = (have, need)
    return result


def load_have(path=None):
    """
    读取各物品最近一次仓库读数：{物品: 数量}。

    负数（-1 表示库存未知）与非数字按未知处理、不进结果：当 0 会让进度显示
    「0/需求」，也会误发达标邮件。
    """
    path = path or HAVE_FILE
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    have = {}
    for key, value in data.items():
        reading = stock_reading(value)
        if reading is not None:
            have[key] = reading
    return have


def last_reading_time(path=None):
    """
    最近一次仓库读数的记录时间（本地时间 "YYYY-MM-DD HH:MM"）；没有记录返回 None。

    提醒里要写清「基于最近一次库存记录」，这个时间就是那份记录落盘的时间。
    """
    path = path or HAVE_FILE
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M')
    except OSError:
        return None


def record_readings(readings, path=None):
    """
    记录本次仓库读数（直接覆盖，不累加、不封顶），返回变化项。

    只记真实读数：-1 表示库存未知（没有仓库模板），不能当成 0 覆盖；None 与
    非数字同样跳过（见 stock_reading）。

    Args:
        readings: {物品: 仓库读数}

    Returns:
        dict: {物品: (旧, 新)}
    """
    path = path or HAVE_FILE
    have = load_have(path)
    changed = {}
    for item, count in (readings or {}).items():
        count = stock_reading(count)
        if count is None:
            continue
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

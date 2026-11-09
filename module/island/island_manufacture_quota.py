"""冬季制造任务有限配额（纯逻辑，不操作设备）。

Add by MHY, 2026-11-09：冬季开发计划只给任务缺口补有限批次，不改日常 Products 排序。

冬季开发计划的制造类任务、物品 ID、需求数量与中文名直接取
`island_season_plan_data.WINTER_TASKS`（与 island_planner/data.py 的
80001501-80001516 对齐），这里只补执行信息（产线、识别素材能力、前置依赖、
单批上限），不再抄一份同样的数据：

    80001512 香囊供给  3039 香囊      x10
    80001513 餐具整备  3047 刀叉餐具  x10
    80001514 文书配套  3053 墨盒      x10
    80001515 时间管理  3054 钟表      x10
    80001516 电力储备  3055 蓄电池    x10

本模块只回答"这一轮补几件、能不能补"，执行由 island_manufacture 完成：

    gap = max(0, Need - 已知库存 - 已知在制 - 本轮已下单)

库存或在制未知时挂起（未知不等于 0）。单岗位批次有上限，多岗位按剩余缺口
依次分配，不会每个岗位都把整个缺口补一遍。没有识别素材的 SKU 只登记能力
状态，不产生批次。

配置读取（cross_get，缺省值保证配置还没生成时也能运行）：

    IslandSeasonPlan.IslandSeasonPlan.WinterTaskEnabled  默认 True
    IslandSeasonPlan.IslandSeasonPlan.Need_<key>         默认取赛季表的数量
    IslandSeasonPlan.IslandSeasonPlan.Done_<key>         默认 False
"""
from module.island.island_season_plan_data import (
    CONFIG_GROUP,
    ITEM_CN,
    TASK_TYPE_MANUFACTURE,
    WINTER_TASKS as SEASON_WINTER_TASKS,
    configured_need,
    winter_task_enabled,
)

WINTER_SEASON = 'winter'
SEASON_PLAN_GROUP = CONFIG_GROUP
# 配方里查不到 production_limit 时的兜底上限（冬季 5 个任务的实际值都是 5）
DEFAULT_BATCH_LIMIT = 5

CAPABILITY_DISPATCHABLE = 'dispatchable'
CAPABILITY_SELECT_ONLY = 'select_only'
CAPABILITY_NO_ASSETS = 'no_assets'

CAPABILITY_CN = {
    CAPABILITY_DISPATCHABLE: '选择/仓库/岗位素材齐全',
    CAPABILITY_SELECT_ONLY: '只有选择图，仓库与岗位在制图缺失',
    CAPABILITY_NO_ASSETS: '没有任何识别素材',
}

# 冬季任务与执行信息（物品名与赛季表一致）。能力状态来自当前仓库的实际资源：
#   cutlery        SELECT_CUTLERY / TEMPLATE_CUTLERY / POST_CUTLERY 全套
#   ink_cartridge 只有 SELECT_INK_CARTRIDGE，无仓库模板、无岗位「生产中」图
#   sachet/clock/battery 只有普通物品 id，没有任何选择/仓库/岗位素材
#   plum_blossom_sachet 是 4055 梅花香包，不是本任务的 3039 香囊，禁止混用
_EXECUTION = {
    'sachet': {
        'line': None,
        'capability': CAPABILITY_NO_ASSETS,
        'dependencies': (('cloth', 1),),
        'note': '普通香囊 3039；梅花香包 4055 是另一物品，不能替代',
    },
    'cutlery': {
        'line': 'industrial_production',
        'capability': CAPABILITY_DISPATCHABLE,
        'dependencies': (),
        'note': 'SELECT/TEMPLATE/POST 素材齐全，可按缺口有限批次派产',
    },
    'ink_cartridge': {
        'line': 'electronic_processing',
        'capability': CAPABILITY_SELECT_ONLY,
        'dependencies': (),
        'note': '只有 SELECT 图，库存与在制不可确认',
    },
    'clock': {
        'line': None,
        'capability': CAPABILITY_NO_ASSETS,
        'dependencies': (),
        'note': '普通钟表 3054',
    },
    'battery': {
        'line': None,
        'capability': CAPABILITY_NO_ASSETS,
        'dependencies': (('sulfuric_acid', 1),),
        'note': '普通蓄电池 3055；前置硫酸 3045 也未接入',
    },
}

# 制造类任务的前置依赖（同一条制造链上的物品，不是采集物）
DEPENDENCY_ITEMS = {
    'cloth': {
        'item_id': 3035, 'cn': '布料', 'capability': CAPABILITY_SELECT_ONLY,
        'note': '只有 SELECT 图，无仓库/岗位模板',
    },
    'sulfuric_acid': {
        'item_id': 3045, 'cn': '硫酸', 'capability': CAPABILITY_NO_ASSETS,
        'note': '没有任何识别素材',
    },
}


def _recipe_batch_limit(item_id, default=DEFAULT_BATCH_LIMIT):
    """单次派遣上限取配方 production_limit，避免和游戏数值脱节。"""
    from module.island_planner.data import DIC_ISLAND_RECIPE
    for recipe in DIC_ISLAND_RECIPE.values():
        if item_id in recipe.get('commission_product', {}):
            return int(recipe.get('production_limit') or default)
    return default


def _build_winter_tasks():
    """从赛季表挑出制造类任务，补上执行信息。"""
    tasks = []
    for task in SEASON_WINTER_TASKS:
        if task.get('type') != TASK_TYPE_MANUFACTURE:
            continue
        execution = _EXECUTION.get(task['item'], {
            'line': None, 'capability': CAPABILITY_NO_ASSETS,
            'dependencies': (), 'note': '执行器未登记该物品',
        })
        tasks.append({
            'key': task['item'],
            'item': task['item'],
            'cn': ITEM_CN.get(task['item'], task['item']),
            'item_id': task['item_id'],
            'task_id': task['task_id'],
            'default_need': task['need'],
            'line': execution['line'],
            'capability': execution['capability'],
            'batch_limit': _recipe_batch_limit(task['item_id']),
            'dependencies': execution['dependencies'],
            'note': execution['note'],
        })
    return tuple(tasks)


WINTER_TASKS = _build_winter_tasks()


def _cross_get(config, path, default):
    """读取跨任务配置；配置对象不支持 cross_get 时退回默认值。"""
    getter = getattr(config, 'cross_get', None)
    if not callable(getter):
        return default
    try:
        value = getter(path, default)
    except (AttributeError, KeyError, TypeError, ValueError):
        return default
    return default if value is None else value


def _as_bool(value, default=False):
    """配置布尔值归一化，兼容字符串形式的 True/False。"""
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ('true', '1', 'yes', 'on'):
            return True
        if text in ('false', '0', 'no', 'off', 'none', ''):
            return False
        return default
    return bool(value)


def read_winter_task_settings(config):
    """读取冬季任务开关与每个任务的 Need/Done。

    Need_ 缺省时取赛季表里的数量（与 island_season_plan_data 一致），
    Done_ 缺省为未完成。

    Args:
        config: AzurLaneConfig，需支持 cross_get(path, default)。

    Returns:
        tuple[bool, list[dict]]: (WinterTaskEnabled, 带 need/done 的任务副本列表)。
    """
    enabled = bool(winter_task_enabled(config))
    tasks = []
    for spec in WINTER_TASKS:
        task = dict(spec)
        task['need'] = configured_need(config, spec['item'], spec['default_need'])
        task['done'] = _as_bool(_cross_get(
            config, f"{SEASON_PLAN_GROUP}.Done_{spec['item']}", False), False)
        tasks.append(task)
    return enabled, tasks


def season_quota_enabled(season, enabled):
    """冬季任务配额只在冬季且 WinterTaskEnabled 为真时生效。"""
    return str(season or '').lower() == WINTER_SEASON and _as_bool(enabled, False)


def compute_gap(need, stock, wip, ordered=0):
    """任务缺口；库存或在制未知（None）时返回 None，绝不按 0 计算。"""
    if stock is None or wip is None:
        return None
    return max(0, int(need) - int(stock) - int(wip) - int(ordered or 0))


def allocate_batches(gap, posts_available, batch_limit):
    """把缺口拆成有限批次，每个空闲岗位最多一批。

    Args:
        gap (int): 剩余缺口。
        posts_available (int): 本产线空闲岗位数。
        batch_limit (int): 单岗位单次派遣上限。

    Returns:
        list[int]: 各岗位派产数量，合计不超过 gap，长度不超过 posts_available。
    """
    if gap <= 0 or posts_available <= 0 or batch_limit <= 0:
        return []
    batches = []
    remaining = int(gap)
    while remaining > 0 and len(batches) < int(posts_available):
        quantity = min(remaining, int(batch_limit))
        batches.append(quantity)
        remaining -= quantity
    return batches


def _check_dependencies(task, gap, dependency_stock):
    """检查任务前置依赖；返回 (是否可派产, 原因)。

    依赖库存未知时按"暂停"处理，不当 0。当前 5 个任务里香囊依赖布料、
    蓄电池依赖硫酸，两者都没有可确认的库存素材。
    """
    for dependency, per_unit in task.get('dependencies') or ():
        name = DEPENDENCY_ITEMS.get(dependency, {}).get('cn', dependency)
        stock = dependency_stock.get(dependency)
        if stock is None:
            return False, f'dependency_unknown:{name}'
        required = int(gap) * int(per_unit)
        if int(stock) < required:
            return False, f'dependency_short:{name}'
    return True, 'ok'


def plan_winter_quota(tasks, state, posts_by_line=None):
    """计算一轮冬季任务配额。

    Args:
        tasks (list[dict]): read_winter_task_settings 返回的任务列表。
        state (dict): 观测状态，未知一律用 None/缺失表示：
            stock (dict[str, int | None]): 已知库存。
            wip (dict[str, int | None]): 已知在制。
            ordered (dict[str, int]): 本轮已下单，缺省 0。
            post_unknown (bool): 有在产岗位但产品/数量无法确认。
            dependency_stock (dict[str, int | None]): 依赖品已知库存。
        posts_by_line (dict[str, int] | None): 各产线空闲岗位数。

    Returns:
        dict: items（逐项决策）、batches（可派产物品 -> 批次列表）、
            suspended/blocked/waiting（挂起/未接入/等岗位的任务 key）、
            posts_left（分配后各产线剩余岗位）。
    """
    posts_by_line = dict(posts_by_line or {})
    posts_left = dict(posts_by_line)
    stock_map = dict(state.get('stock') or {})
    wip_map = dict(state.get('wip') or {})
    ordered_map = dict(state.get('ordered') or {})
    dependency_stock = dict(state.get('dependency_stock') or {})
    post_unknown = bool(state.get('post_unknown'))

    items = []
    batches = {}
    suspended = []
    blocked = []
    waiting = []

    for task in tasks:
        item = task['item']
        stock = stock_map.get(item)
        wip = wip_map.get(item)
        ordered = ordered_map.get(item, 0)
        decision = {
            'key': task['key'], 'item': item, 'cn': task['cn'],
            'item_id': task['item_id'], 'task_id': task['task_id'],
            'line': task.get('line'), 'capability': task['capability'],
            'note': task.get('note', ''), 'need': task['need'],
            'done': bool(task.get('done')), 'stock': stock, 'wip': wip,
            'ordered': ordered, 'gap': None, 'status': '', 'reason': '',
            'batch_limit': int(task.get('batch_limit') or DEFAULT_BATCH_LIMIT),
            'batches': [],
        }

        if task.get('done'):
            decision.update(status='done', reason='done_flag')
        elif task['capability'] != CAPABILITY_DISPATCHABLE:
            decision.update(status='blocked', reason=task['capability'])
            blocked.append(task['key'])
        elif post_unknown:
            decision.update(status='suspended', reason='unknown_active_post')
            suspended.append(task['key'])
        elif stock is None:
            decision.update(status='suspended', reason='unknown_stock')
            suspended.append(task['key'])
        elif wip is None:
            decision.update(status='suspended', reason='unknown_wip')
            suspended.append(task['key'])
        else:
            gap = compute_gap(task['need'], stock, wip, ordered)
            decision['gap'] = gap
            if gap <= 0:
                decision.update(status='done', reason='gap_zero')
            else:
                ok, dependency_reason = _check_dependencies(task, gap, dependency_stock)
                if not ok:
                    decision.update(status='suspended', reason=dependency_reason)
                    suspended.append(task['key'])
                else:
                    line = task.get('line')
                    available = int(posts_left.get(line, 0))
                    if available <= 0:
                        decision.update(status='no_post', reason='no_idle_post')
                        waiting.append(task['key'])
                    else:
                        limit = int(task.get('batch_limit') or DEFAULT_BATCH_LIMIT)
                        task_batches = allocate_batches(gap, available, limit)
                        posts_left[line] = available - len(task_batches)
                        decision.update(status='dispatch', reason='ok', batches=task_batches)
                        batches[item] = task_batches

        items.append(decision)

    return {
        'items': items,
        'batches': batches,
        'suspended': suspended,
        'blocked': blocked,
        'waiting': waiting,
        'posts_left': posts_left,
    }


def describe_decision(decision):
    """把一条配额决策格式化成中文日志。"""
    name = f"{decision['cn']}({decision['item_id']})"
    status = decision['status']
    reason = decision['reason']

    if status == 'dispatch':
        return (f"[冬季配额] {name}：需求{decision['need']}，库存{decision['stock']}，"
                f"在制{decision['wip']}，本轮已下单{decision['ordered']}，"
                f"缺口{decision['gap']} → 派产 {decision['batches']}")
    if status == 'done':
        if reason == 'done_flag':
            return f"[冬季配额] {name}：Done_{decision['key']} 已完成，不再追加任务生产"
        return (f"[冬季配额] {name}：缺口 0（库存{decision['stock']} + 在制{decision['wip']} + "
                f"已下单{decision['ordered']} ≥ 需求{decision['need']}），不再追加")
    if status == 'blocked':
        capability = CAPABILITY_CN.get(decision['capability'], decision['capability'])
        return f"[冬季配额] {name}：未接入（{capability}；{decision['note']}）"
    if status == 'no_post':
        return f"[冬季配额] {name}：缺口{decision['gap']}，本产线无空闲岗位，等待下一轮"
    if status == 'suspended':
        if reason == 'unknown_active_post':
            detail = '有岗位在产但产品/数量无法确认'
        elif reason == 'unknown_stock':
            detail = '库存未知'
        elif reason == 'unknown_wip':
            detail = '在制数量未知'
        elif reason.startswith('dependency_unknown:'):
            detail = f"依赖 {reason.split(':', 1)[1]} 库存未知"
        elif reason.startswith('dependency_short:'):
            detail = f"依赖 {reason.split(':', 1)[1]} 不足"
        else:
            detail = reason
        return f"[冬季配额] {name}：暂停任务派产（{detail}，未知不当 0）"
    return f"[冬季配额] {name}：{status}（{reason}）"

"""冬季开发计划的自然资源库存下限叠加（Add by MHY）。

冬季开发计划要上交一批自然资源：茶叶、柑橘、芒果、牛油果、淡水/海水鱼肉、银矿、
典雅之木。提交时仓库数量会被吃掉，而农田/果园/苗圃、矿山林场、鱼肉加工各自的日常下限
（`CropTargets`/`MinFarm`/`IslandMine_MinSilver`/`MinFreshwaterFishMeat` 等）
并不知道这件事，不叠加就会出现「任务要 500 茶叶、苗圃下限还是 0，收完就停」的情况。

任务清单、物品 ID、需求默认值与中文名取自 `island_season_plan_data.WINTER_TASKS`
（与赛季表、仓库配置共用一份数据）；本模块只补「哪类产出、哪个执行器产物」的映射，
不再手抄一份物品表。

生效规则（只在冬季、且 `WinterTaskEnabled` 打开时参与）：

    生效下限 = max(原日常下限, 配置库存基准 + TASK_BUFFER)

- `Need_<物品>` > 0 时持续保有库存，达标后消耗会重新补足，无需标记完成。
  旧配置的 `Done_` 不影响下限；需求填 0 才关闭该项叠加，回到日常下限。
- 取 max 而不是覆盖：原日常下限更高时（例如农场 660）不会因为任务需求低而下降。
- 叠加只在运行时计算，绝不写回 `CropTargets`/`Min*` 等阈值配置。仓库读数每天在变，
  写回会让阈值一轮轮往上叠，也会盖掉用户自己的设置。

各处边界：
- 牛油果：「忽略牛油果」只约束日常补种，任务要交的那份仍然补种（见 `protected_crops`）。
- 鱼肉：只能靠「鱼肉加工」把鱼兑换出来，所以只抬兑换目标；各鱼的保留数量（keep）与
  渔场养殖计划都不动，库存读不到（未知）时也不会被当成 0 去兑换。
- 配置里缺 `Need_`/`WinterTaskEnabled` 键（旧配置、新赛季）时用赛季表的
  默认值，不依赖配置生成器先落地。
"""
from module.island import island_season_plan_data as season_data
from module.logger import logger

# 配置路径前缀，与 config/template.json 的 IslandSeasonPlan 组一致
GROUP = season_data.CONFIG_GROUP
WINTER = 'winter'
# 任务需求之外多留的数量：收获/兑换有余量，提交后仓库不会立刻见底
TASK_BUFFER = season_data.WINTER_NATURAL_RESERVE

# 冬季开发计划上交的自然资源的执行映射。
#   area: crop=种植区域产物 / mine、forest=采集产物 / fish_meat=鱼肉加工兑换产物
#   group: 种植区域（farm/orchard/nursery）；product: 执行器里的产物名
#   alias: 执行器/配置里另一种常见写法，读配置时兜底
#   meat_id 取赛季表的 item_id（淡水 2521、海水 2522），不另抄一份 ID
_EXECUTION = {
    'tea': {'area': 'crop', 'group': 'nursery', 'product': 'tea'},
    'citrus': {'area': 'crop', 'group': 'orchard', 'product': 'citrus'},
    'mango': {'area': 'crop', 'group': 'orchard', 'product': 'mango'},
    'avocado': {'area': 'crop', 'group': 'orchard', 'product': 'avocado'},
    'freshwater_fish_meat': {'area': 'fish_meat'},
    'seawater_fish_meat': {'area': 'fish_meat', 'alias': 'saltwater_fish_meat'},
    'silver': {'area': 'mine', 'product': 'Silver'},
    'elegant_wood': {'area': 'forest', 'product': 'Elegant'},
}


def _build_task_items():
    """冬季自然类任务 -> 执行映射（物品、ID、默认需求与中文名来自赛季表）。"""
    items = {}
    for task in season_data.WINTER_TASKS:
        if task.get('type') != season_data.TASK_TYPE_NATURAL:
            continue
        execution = _EXECUTION.get(task['item'])
        if execution is None:
            continue
        info = dict(execution)
        info['item_id'] = task['item_id']
        info['default_need'] = task['need']
        info['cn_name'] = season_data.ITEM_CN.get(task['item'], task['item'])
        if info['area'] == 'fish_meat':
            info['meat_id'] = task['item_id']
        items[task['item']] = info
    return items


WINTER_TASK_ITEMS = _build_task_items()


def _cross_get(config, key, default=None):
    """读配置；配置替身没有 cross_get（离线测试）时按缺键处理。"""
    if config is None:
        return default
    getter = getattr(config, 'cross_get', None)
    if getter is None:
        return default
    return getter(key, default=default)


def current_season(config):
    """当前赛季标识；读不到返回 None（按非冬季处理，保持旧行为）。"""
    return _cross_get(config, 'IslandPlan.IslandPlan.Season', default=None)


def winter_task_enabled(config):
    """冬季任务叠加是否生效：必须处于冬季，且总开关没被关掉。"""
    if current_season(config) != WINTER:
        return False
    return season_data.winter_task_enabled(config)


def _configured(config, item, prefix):
    """读 `<prefix>_<物品>`；主键缺失时再试 alias，仍缺失返回 None。"""
    names = [item]
    alias = WINTER_TASK_ITEMS[item].get('alias')
    if alias:
        names.append(alias)
    for name in names:
        value = _cross_get(config, f'{GROUP}.{prefix}_{name}', default=None)
        if value is not None:
            return value
    return None


def task_need(config, item):
    """某项任务的配置需求数量；键缺失或值非法时用赛季表默认值，显式 0 保持 0。"""
    default = int(WINTER_TASK_ITEMS[item]['default_need'])
    raw = _configured(config, item, 'Need')
    if raw is None or raw == '':
        return default
    try:
        return max(int(float(raw)), 0)
    except (TypeError, ValueError):
        logger.warning(f'[岛屿-冬季任务] {WINTER_TASK_ITEMS[item]["cn_name"]} 需求「{raw}」无法解析，按 {default} 处理')
        return default


def active_task_needs(config):
    """持续库存叠加目标：{物品: 库存基准 + 缓冲}；任务关闭或非冬季时为空。"""
    if not winter_task_enabled(config):
        return {}
    targets = {}
    # Modify by MHY, 自然库存随消耗持续补足，忽略旧配置的完成标记。
    for item in WINTER_TASK_ITEMS:
        need = task_need(config, item)
        if need <= 0:
            continue
        targets[item] = need + TASK_BUFFER
    return targets


def crop_task_targets(config, area):
    """某种植区域的冬季任务作物目标：{作物: 需求 + 缓冲}。"""
    targets = {}
    for item, target in active_task_needs(config).items():
        info = WINTER_TASK_ITEMS[item]
        if info.get('area') == 'crop' and info.get('group') == area:
            targets[info['product']] = target
    return targets


def protected_crops(config, area):
    """该区域里由冬季任务驱动的作物：不受忽略项与当季过滤影响（牛油果即属此列）。"""
    return set(crop_task_targets(config, area))


def ore_task_target(config, product):
    """采集产物（银矿/典雅之木）的冬季任务目标；没有任务返回 0。"""
    for item, target in active_task_needs(config).items():
        info = WINTER_TASK_ITEMS[item]
        if info.get('area') in ('mine', 'forest') and info.get('product') == product:
            return target
    return 0


def ore_threshold(config, product, base):
    """采集产物生效下限：max(日常下限, 冬季任务目标)。"""
    task_target = ore_task_target(config, product)
    base = int(base or 0)
    if not task_target:
        return base
    return max(base, task_target)


def exchange_targets(config, targets):
    """鱼肉兑换目标叠加：键为鱼肉物品 ID，值取 max(原目标, 冬季任务目标)。

    原目标为未知（None 或负数，见 island_business_stock 的 -1 约定）时保持未知：
    未知不等于 0，不能因为任务目标就去兑换。

    Args:
        config: AzurLaneConfig 实例。
        targets (dict[int, int]): {鱼肉ID: 原兑换目标}，见 IslandFishery.run。

    Returns:
        dict[int, int]: 叠加后的兑换目标（新字典，不改入参）。
    """
    merged = dict(targets or {})
    for item, target in active_task_needs(config).items():
        info = WINTER_TASK_ITEMS[item]
        if info.get('area') != 'fish_meat':
            continue
        meat_id = info['meat_id']
        base = merged.get(meat_id)
        if base is None or int(base) < 0:
            continue
        merged[meat_id] = max(int(base), target)
    return merged

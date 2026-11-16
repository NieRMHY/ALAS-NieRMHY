"""岛屿赛季「开发计划」任务数据（来源：碧蓝航线 wiki 岛屿计划）。

每个赛季有一批提交任务：向岛屿仓库提交指定数量的物品，奖励固定为
生活经验指南 T3 x1 + T2 x2 + 星彩券 x1。物品既可能是基础作物/畜牧品，
也可能是店铺商品或制造工坊产品，因此提交前要按仓库实际库存决定优先级。

冬季任务额外带 type（natural/meal/manufacture），排产目标见 planning_need：
自然类固定多备 100，餐品类加 IslandSeasonPlan.MealBuffer，制造类不加缓冲。

数据用于：
  - 判断哪些任务当前可提交（仓库够不够）
  - 反推生产计划（缺的物品要不要排产）

Add by MHY, 2026-11-10：过季任务移到 RETIRED_SEASON_PLAN_TASKS，只供页面读取器识别，
不参与上面两类计算；活动表 SEASON_PLAN_TASKS 里只保留仍在进行的赛季。
"""

# 奖励（所有赛季任务相同）
SEASON_PLAN_REWARD = ('生活经验指南T3x1', '生活经验指南T2x2', '星彩券x1')

# 任务类型（Add by MHY, 2026-11-09）：冬季 16 项按产出方式分类。
# natural 走采集/种植，meal 走店铺后厨，manufacture 走制造工坊。
TASK_TYPE_NATURAL = 'natural'
TASK_TYPE_MEAL = 'meal'
TASK_TYPE_MANUFACTURE = 'manufacture'

# 冬季模式配置（Add by MHY）：开关只在赛季为 winter 时生效；MealBuffer 是餐品类
# 任务的额外缓冲，允许 0。自然类固定多备 WINTER_NATURAL_RESERVE 件，不另设开关。
CONFIG_GROUP = 'IslandSeasonPlan.IslandSeasonPlan'
WINTER_ENABLED_KEY = f'{CONFIG_GROUP}.WinterTaskEnabled'
MEAL_BUFFER_KEY = f'{CONFIG_GROUP}.MealBuffer'
DEFAULT_MEAL_BUFFER = 20
WINTER_NATURAL_RESERVE = 100

# 冬季（第 5 季）16 项赛季任务，顺序、任务 ID、任务名与
# module/island_planner/data.py 的 DIC_ISLAND_TASK 80001501-80001516 一致。
# item 是项目内的 canonical key：
#   - 自然资源：茶/柑橘/芒果/牛油果沿用农田与果园的 key，鱼肉沿用鱼肉加工；
#     银矿/典雅之木用 silver / elegant_wood，由 island_winter_resources 映射到矿山、
#     林场执行器里的 Silver / Elegant 产物名。
#   - 餐品：沿用 economy 的 chicken_potato / rice_mango / strawberry_charlotte。
#   - 制造：刀叉餐具/墨盒沿用 island_manufacture 的 cutlery / ink_cartridge；
#     香囊/钟表/蓄电池没有执行器产品，用 sachet / clock / battery
#     （plum_blossom_sachet 是 4055 梅花香包，不是 3039 香囊）。
WINTER_TASKS = (
    {'task_id': 80001501, 'name': '清茶储备', 'item': 'tea', 'item_id': 2014,
     'need': 500, 'type': TASK_TYPE_NATURAL},
    {'task_id': 80001502, 'name': '柑橘补给', 'item': 'citrus', 'item_id': 2017,
     'need': 500, 'type': TASK_TYPE_NATURAL},
    {'task_id': 80001503, 'name': '金芒入仓', 'item': 'mango', 'item_id': 2019,
     'need': 250, 'type': TASK_TYPE_NATURAL},
    {'task_id': 80001504, 'name': '牛油果香', 'item': 'avocado', 'item_id': 2021,
     'need': 100, 'type': TASK_TYPE_NATURAL},
    {'task_id': 80001505, 'name': '河鲜供应', 'item': 'freshwater_fish_meat', 'item_id': 2521,
     'need': 100, 'type': TASK_TYPE_NATURAL},
    {'task_id': 80001506, 'name': '海味入库', 'item': 'seawater_fish_meat', 'item_id': 2522,
     'need': 100, 'type': TASK_TYPE_NATURAL},
    {'task_id': 80001507, 'name': '丰盛拼盘', 'item': 'chicken_potato', 'item_id': 3030,
     'need': 100, 'type': TASK_TYPE_MEAL},
    {'task_id': 80001508, 'name': '甜糯组合', 'item': 'rice_mango', 'item_id': 3025,
     'need': 50, 'type': TASK_TYPE_MEAL},
    {'task_id': 80001509, 'name': '甜品储备', 'item': 'strawberry_charlotte', 'item_id': 3028,
     'need': 25, 'type': TASK_TYPE_MEAL},
    {'task_id': 80001510, 'name': '银矿采集', 'item': 'silver', 'item_id': 2705,
     'need': 25, 'type': TASK_TYPE_NATURAL},
    {'task_id': 80001511, 'name': '良木入库', 'item': 'elegant_wood', 'item_id': 2803,
     'need': 25, 'type': TASK_TYPE_NATURAL},
    {'task_id': 80001512, 'name': '香囊供给', 'item': 'sachet', 'item_id': 3039,
     'need': 10, 'type': TASK_TYPE_MANUFACTURE},
    {'task_id': 80001513, 'name': '餐具整备', 'item': 'cutlery', 'item_id': 3047,
     'need': 10, 'type': TASK_TYPE_MANUFACTURE},
    {'task_id': 80001514, 'name': '文书配套', 'item': 'ink_cartridge', 'item_id': 3053,
     'need': 10, 'type': TASK_TYPE_MANUFACTURE},
    {'task_id': 80001515, 'name': '时间管理', 'item': 'clock', 'item_id': 3054,
     'need': 10, 'type': TASK_TYPE_MANUFACTURE},
    {'task_id': 80001516, 'name': '电力储备', 'item': 'battery', 'item_id': 3055,
     'need': 10, 'type': TASK_TYPE_MANUFACTURE},
)

# 赛季 -> [(任务名, 物品英文名, 需要数量)]；物品名与经济库/仓库模板一致。
# 冬季由 WINTER_TASKS 派生，保持既有三元组 API 不变。
# Modify by MHY, 2026-11-10：只有仍在进行的赛季才放进这张表。过季任务挪到
# RETIRED_SEASON_PLAN_TASKS，读需求、算缺口、排产与常驻餐品轮换都只认这张表，
# 配置里残留的 Need_/Done_ 或缺失的键都不会再把旧任务默认值带回来。
SEASON_PLAN_TASKS = {
    'winter': [(task['name'], task['item'], task['need']) for task in WINTER_TASKS],
}

# Add by MHY, 2026-11-10：秋季任务已随赛季结束退场，只保留任务名/物品/需求给
# 开发计划页读取器识别旧截图与旧配置，不参与任何排产、缺口或配置写回。
RETIRED_SEASON_PLAN_TASKS = {
    'autumn': [
        ('麦田守望', 'wheat', 500),
        ('动物食品', 'pasture', 500),
        ('开拓豆源', 'soybean', 500),
        ('稻米供应', 'rice', 500),
        ('黄金粮仓', 'corn', 500),
        ('橙色活力', 'carrot', 250),
        ('乳品补给', 'milk', 250),
        ('甜蜜引擎', 'apple_juice', 250),
        ('咖啡供应', 'iced_coffee', 250),
        ('烤肉能量', 'roasted_skewer', 250),
        ('调味基础', 'onion', 100),
        ('健康饮食', 'salad', 100),            # 蔬菜沙拉（餐馆）
        ('营养组合', 'carrot_omelette', 100),  # 胡萝卜厚蛋烧（烤肉）
        ('拿铁时光', 'latte', 100),
        ('禽肉快炒', 'stir_fried_chicken', 100),
        ('便携快餐', 'steak_bowl', 50),
    ],
}

# Add by MHY, 2026-11-10：过季任务涉及的物品集合，供常驻餐品识别历史自动值。
RETIRED_SEASON_ITEMS = {item for tasks in RETIRED_SEASON_PLAN_TASKS.values()
                        for _, item, _ in tasks if item}

# 物品中文名（用于日志与配置显示；基础材料不在经济库里，单独列）
ITEM_CN = {
    'wheat': '小麦', 'pasture': '牧草', 'soybean': '大豆', 'rice': '大米',
    'corn': '玉米', 'carrot': '胡萝卜', 'milk': '牛奶', 'onion': '洋葱',
    # 冬季赛季任务
    'tea': '茶叶', 'citrus': '柑橘', 'mango': '芒果', 'avocado': '牛油果',
    'freshwater_fish_meat': '淡水鱼肉', 'seawater_fish_meat': '海水鱼肉',
    'silver': '银矿', 'elegant_wood': '典雅之木',
    'chicken_potato': '禽肉土豆拼盘', 'rice_mango': '芒果糯米饭',
    'strawberry_charlotte': '草莓夏洛特',
    'sachet': '香囊', 'cutlery': '刀叉餐具', 'ink_cartridge': '墨盒',
    'clock': '钟表', 'battery': '蓄电池',
}


# 开发季的「累计交付岛屿订单」里程碑（Add by MHY，2026-10-01 真机抓图确认）。
# 与季节无关，同一开发季内一直显示，通常早已全部领取。加进来是为了让读取器认识
# 它们：否则这一屏会被判成「0 个新任务」，连续三屏就触发 EMPTY_LIMIT「判定到底」
# 提前收工，后面的已知任务可能读不到。
# item 为 None：它们不产出也不消耗岛屿物品——排产目标、库存计算、常驻餐品轮换
# 都会跳过 None（各处都有 if not item 的判断），也不会进入 season_items_for_shop。
ORDER_MILESTONES = [
    ('稳定交付', None, 30),
    ('坚实后盾', None, 50),
    ('订单专家', None, 100),
    ('发展支柱', None, 150),
    ('开发核心', None, 200),
    ('繁荣之基', None, 300),
]


def season_is_active(season):
    """该赛季是否仍有进行中的开发计划任务（只有任务表里的赛季参与排产）。"""
    return season in SEASON_PLAN_TASKS


def season_is_retired(season):
    """该赛季是否已过季（任务只用于识别，不参与排产）。"""
    return season in RETIRED_SEASON_PLAN_TASKS


def is_retired_season_item(item):
    """物品是否属于已过季的开发计划任务。"""
    return bool(item) and item in RETIRED_SEASON_ITEMS


def plan_tasks(season):
    """
    取某赛季的提交任务列表（含与季节无关的订单里程碑）。

    Modify by MHY, 2026-11-10：过季任务仍可被页面读取器识别，但识别结果不得进入
    排产；需要排产的调用方先看 season_is_active，或直接读只含进行中赛季的
    SEASON_PLAN_TASKS。

    Args:
        season: spring/summer/autumn/winter

    Returns:
        list[(任务名, 物品英文名, 需要数量)]；订单里程碑的物品名为 None
    """
    tasks = SEASON_PLAN_TASKS.get(season)
    if tasks is None:
        # 只有任务表里完全没有该赛季时才回退到过季表：给读取器识别旧截图用
        tasks = RETIRED_SEASON_PLAN_TASKS.get(season, [])
    return list(tasks) + list(ORDER_MILESTONES)


def task_of_item(item, season):
    """
    反查物品对应的赛季任务。

    Args:
        item: 物品英文名
        season: 赛季

    Returns:
        tuple: (任务名, 需要数量)；没有该物品返回 (None, 0)
    """
    if not item:
        # 订单里程碑没有对应物品，反查直接给空（None == None 会误命中）
        return None, 0
    for name, task_item, need in plan_tasks(season):
        if task_item == item:
            return name, need
    return None, 0


def winter_task(item):
    """冬季任务条目（含 task_id/item_id/type）；不是冬季任务返回 None。"""
    for task in WINTER_TASKS:
        if task['item'] == item:
            return task
    return None


def season_items(season):
    """该赛季进行中任务涉及的物品集合（不含订单里程碑与过季任务）。"""
    return {item for _, item, _ in SEASON_PLAN_TASKS.get(season, []) if item}


def task_type(item, season):
    """
    任务类型：natural / meal / manufacture；不是该赛季进行中的任务返回 None。

    冬季用 WINTER_TASKS 里的显式标注；其他赛季按是否属于店铺商品推断。过季任务
    不再参与分类，避免旧物品被排产逻辑当成当前需求。
    """
    if not item:
        return None
    if season == 'winter':
        task = winter_task(item)
        if task:
            return task['type']
    if item not in season_items(season):
        return None
    from module.island.island_economy import ECONOMY_PRODUCTS
    return TASK_TYPE_MEAL if item in ECONOMY_PRODUCTS else TASK_TYPE_NATURAL


def _as_bool(value, default=True):
    """配置值转布尔（兼容 true/false 字符串，避免 bool('false') 为 True）。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ('true', '1', 'yes', 'on'):
            return True
        if text in ('false', '0', 'no', 'off', ''):
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def winter_task_enabled(config=None):
    """冬季模式开关值，默认开；是否生效由 planning_need 的 season 参数判断。"""
    if config is None:
        return True
    try:
        value = config.cross_get(WINTER_ENABLED_KEY, default=True)
    except Exception:
        return True
    return _as_bool(value, default=True)


def meal_buffer(config=None):
    """餐品任务的额外缓冲，默认 20；负数按 0，非法值回退默认值。"""
    if config is None:
        return DEFAULT_MEAL_BUFFER
    try:
        raw = config.cross_get(MEAL_BUFFER_KEY, default=DEFAULT_MEAL_BUFFER)
    except Exception:
        return DEFAULT_MEAL_BUFFER
    try:
        value = int(float(raw))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_MEAL_BUFFER
    return max(value, 0)


def configured_need(config, item, default):
    """读取 Need_<物品>；配置缺失或非法时用赛季表默认值。"""
    if config is None:
        return default
    try:
        raw = config.cross_get(f'{CONFIG_GROUP}.Need_{item}', default=default)
    except Exception:
        return default
    try:
        return max(int(float(raw)), 0)
    except (TypeError, ValueError, OverflowError):
        return default


def planning_need(season, item, need, winter_enabled=True,
                  meal_buffer_value=DEFAULT_MEAL_BUFFER):
    """
    排产目标数量：冬季自然类 +100、餐品类 +MealBuffer，其余不变。

    Args:
        season: 赛季
        item: 物品 canonical key
        need: 提交需求数量（Need_<物品>）
        winter_enabled: WinterTaskEnabled，仅在 winter 生效
        meal_buffer_value: MealBuffer，负数按 0

    Returns:
        int: 需要备货的总数量
    """
    try:
        need = max(int(need or 0), 0)
    except (TypeError, ValueError):
        need = 0
    if need <= 0:
        # Need_ 填 0 表示这项不用再补，不能因为自然储备又变回 100
        return 0
    if season != 'winter' or not winter_enabled:
        return need
    kind = task_type(item, season)
    if kind == TASK_TYPE_NATURAL:
        return need + WINTER_NATURAL_RESERVE
    if kind == TASK_TYPE_MEAL:
        try:
            buffer_value = max(int(meal_buffer_value or 0), 0)
        except (TypeError, ValueError):
            buffer_value = DEFAULT_MEAL_BUFFER
        return need + buffer_value
    return need


def configured_planning_need(config, season, item, need):
    """按配置的冬季开关与餐品缓冲计算排产目标。"""
    return planning_need(season, item, need,
                         winter_enabled=winter_task_enabled(config),
                         meal_buffer_value=meal_buffer(config))


def winter_plan_tasks(config=None):
    """
    冬季 16 项的排产目标（Need_ 优先，缺失时用赛季表）。

    Returns:
        list[dict]: 每项含 task_id/name/item/item_id/need/type/target；
        WinterTaskEnabled 关闭时返回空列表。
    """
    if not winter_task_enabled(config):
        return []
    buffer_value = meal_buffer(config)
    rows = []
    for task in WINTER_TASKS:
        need = configured_need(config, task['item'], task['need'])
        row = dict(task)
        row['need'] = need
        row['target'] = planning_need('winter', task['item'], need,
                                      winter_enabled=True,
                                      meal_buffer_value=buffer_value)
        rows.append(row)
    return rows


def cn_name(item):
    """物品中文名：经济库优先，其次基础材料表，最后回原名；无物品返回空串。"""
    from module.island.island_economy import ECONOMY_PRODUCTS
    if not item:
        return ''
    info = ECONOMY_PRODUCTS.get(item)
    if info:
        return info['cn_name']
    return ITEM_CN.get(item, item)


def submit_priority(season, warehouse, producible=None):
    """
    按「现在就能提交」优先排序赛季任务。

    仓库够的任务可以立刻提交拿奖励；不够的任务排在后面（需要先生产/采集）。

    Args:
        season: 赛季
        warehouse: {物品: 库存}
        producible: 可生产物品集合；None 不额外过滤

    Returns:
        list[(任务名, 物品, 需要数量, 当前库存, 是否可提交)]
    """
    if not season_is_active(season):
        # Add by MHY, 2026-11-10：过季赛季没有进行中的提交任务，不能按旧默认需求给建议
        return []
    result = []
    for name, item, need in plan_tasks(season):
        if not item:
            continue
        have = int(warehouse.get(item, 0))
        if producible is not None and item not in producible:
            continue
        result.append((name, item, need, have, have >= need))
    result.sort(key=lambda row: (not row[4], -row[3]))
    return result

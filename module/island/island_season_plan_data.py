"""岛屿赛季「开发计划」任务数据（来源：碧蓝航线 wiki 岛屿计划）。

每个赛季有一批提交任务：向岛屿仓库提交指定数量的物品，奖励固定为
生活经验指南 T3 x1 + T2 x2 + 星彩券 x1。物品既可能是基础作物/畜牧品，
也可能是店铺商品，因此提交前要按仓库实际库存决定优先级。

数据用于：
  - 判断哪些任务当前可提交（仓库够不够）
  - 反推生产计划（缺的物品要不要排产）
"""

# 奖励（所有赛季任务相同）
SEASON_PLAN_REWARD = ('生活经验指南T3x1', '生活经验指南T2x2', '星彩券x1')

# 赛季 -> [(任务名, 物品英文名, 需要数量)]；物品名与经济库/仓库模板一致
SEASON_PLAN_TASKS = {
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

# 物品中文名（用于日志与配置显示；基础材料不在经济库里，单独列）
ITEM_CN = {
    'wheat': '小麦', 'pasture': '牧草', 'soybean': '大豆', 'rice': '大米',
    'corn': '玉米', 'carrot': '胡萝卜', 'milk': '牛奶', 'onion': '洋葱',
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


def plan_tasks(season):
    """
    取某赛季的提交任务列表（含与季节无关的订单里程碑）。

    Args:
        season: spring/summer/autumn/winter

    Returns:
        list[(任务名, 物品英文名, 需要数量)]；订单里程碑的物品名为 None
    """
    return list(SEASON_PLAN_TASKS.get(season, [])) + list(ORDER_MILESTONES)


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

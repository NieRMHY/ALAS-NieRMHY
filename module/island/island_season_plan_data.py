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
        ('健康饮食', 'vegetable_salad', 100),
        ('营养组合', 'carrot_omelette', 100),
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


def plan_tasks(season):
    """
    取某赛季的提交任务列表。

    Args:
        season: spring/summer/autumn/winter

    Returns:
        list[(任务名, 物品英文名, 需要数量)]
    """
    return list(SEASON_PLAN_TASKS.get(season, []))


def cn_name(item):
    """物品中文名：经济库优先，其次基础材料表，最后回原名。"""
    from module.island.island_economy import ECONOMY_PRODUCTS
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
        have = int(warehouse.get(item, 0))
        if producible is not None and item not in producible:
            continue
        result.append((name, item, need, have, have >= need))
    result.sort(key=lambda row: (not row[4], -row[3]))
    return result

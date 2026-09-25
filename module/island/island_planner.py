"""岛屿生产/销售方案生成器（离线，不参与运行时执行）。

本模块只负责"出方案"：按经济库算出每家店的生产清单与上架清单，写成 ALAS
原有配置项；具体执行完全交给 ALAS 框架：

    生产清单 -> <Task>.<Task>.Meal1-8 / MealNumber1-8（原有生产逻辑，套餐原料自动展开）
    上架清单 -> IslandBusinessShop<N>.Product1-5（原有经营逻辑，含季节/库存替换）

方案生成是纯计算：不截图、不点击、不依赖游戏在线，可随时重跑覆盖配置。
"""
import ast
import json
import os
import re

from module.island.island_economy import (
    ECONOMY_SHOPS,
    SHOP_CN_NAMES,
    SHOP_LEVELS,
    EconomyDatabase,
)

UNPRODUCIBLE_FILE = os.path.join('config', 'island_unproducible.json')
# Add by MHY: 本账号「验证过能生产」的商品名单（从 ALAS 日志挖掘），
# 用于避免把未解锁商品排进生产清单（会 GameStuckError→重启→死循环）
VERIFIED_FILE = os.path.join('config', 'island_verified.json')

# Add by MHY: 店铺标识 -> (生产任务名, 经营端配置序号, 商店模块源码)
SHOP_TASKS = {
    'restaurant': ('IslandRestaurant', '1', 'module/island/island_restaurant.py'),
    'teahouse': ('IslandTeahouse', '2', 'module/island/island_teahouse.py'),
    'juu_eatery': ('IslandJuuEatery', '3', 'module/island/island_juu_eatery.py'),
    'grill': ('IslandGrill', '4', 'module/island/island_grill.py'),
    'juu_coffee': ('IslandJuuCoffee', '5', 'module/island/island_juu_coffee.py'),
}

MEAL_SLOTS = 8
SHELF_SLOTS = 5
MIN_STOCK = 2


def load_unproducible(shop):
    """
    读取账号未解锁/研发未完成的商品名单（由运行时选品失败自动记录）。

    Args:
        shop: 店铺类型标识

    Returns:
        set: 商品英文名集合
    """
    try:
        with open(UNPRODUCIBLE_FILE, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return set()
    return set(data.get(shop, []))


def save_unproducible(shop, names):
    """写回不可生产名单；names 为空时移除该店铺条目。"""
    try:
        with open(UNPRODUCIBLE_FILE, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if names:
        data[shop] = sorted(names)
    else:
        data.pop(shop, None)
    try:
        os.makedirs(os.path.dirname(UNPRODUCIBLE_FILE) or '.', exist_ok=True)
        with open(UNPRODUCIBLE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError:
        return False
    return True


def load_verified():
    """
    读取「已验证可生产」名单（{店铺: [商品]}）。

    Returns:
        dict: {shop: set(names)}；文件不存在返回空 dict
    """
    try:
        with open(VERIFIED_FILE, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {shop: set(names) for shop, names in data.items() if isinstance(names, list)}


def save_verified(data):
    """写入已验证名单。"""
    try:
        os.makedirs(os.path.dirname(VERIFIED_FILE) or '.', exist_ok=True)
        with open(VERIFIED_FILE, 'w', encoding='utf-8') as f:
            json.dump({k: sorted(v) for k, v in sorted(data.items())}, f,
                      ensure_ascii=False, indent=1)
    except OSError:
        return False
    return True


def mine_verified(paths):
    """
    从 ALAS 日志挖掘「成功安排过生产」的商品，作为可生产名单。

    日志证据只用生产派遣记录 '已安排生产：<中文名>'——它证明该商品在派单
    列表里能被选中（即已解锁）；经营端的 '选择餐品' 是货架点击，不能证明
    可生产，故不采纳。

    Args:
        paths: 日志文件路径列表

    Returns:
        dict: {shop: set(names)}
    """
    from module.island.island_economy import ECONOMY_PRODUCTS
    cn_to_en = {info['cn_name']: name for name, info in ECONOMY_PRODUCTS.items()}
    found = set()
    for path in paths:
        try:
            with open(path, encoding='utf-8', errors='ignore') as f:
                text = f.read()
        except OSError:
            continue
        for line in text.splitlines():
            match = re.search(r'已安排生产：([^\s]+)', line)
            if match:
                name = cn_to_en.get(match.group(1))
                if name:
                    found.add(name)

    result = {}
    for name in found:
        shop = ECONOMY_PRODUCTS[name]['shop']
        result.setdefault(shop, set()).add(name)
    return result


def code_products(shop):
    """
    解析商店模块源码，取出本店有按钮资源的商品（代码已实现）。

    这些商品才能在游戏里排产/上架；经济库里多出来的条目（wiki 有、
    代码没有）必须排除，否则排产时 KeyError。

    Args:
        shop: 店铺类型标识

    Returns:
        set: 商品英文名集合；源码缺失时返回空集合
    """
    path = SHOP_TASKS.get(shop, (None, None, None))[2]
    if not path or not os.path.exists(path):
        return set()
    with open(path, encoding='utf-8') as f:
        tree = ast.parse(f.read())
    names = set()
    for node in ast.walk(tree):
        # 商品条目形如 {'name': 'xxx', 'template': ..., 'var_name': ...}，
        # 各店组装方式不同（字面量列表 / append / seasonal 合并），
        # 因此按字典特征匹配而不是按 shop_items 赋值语句匹配。
        if not isinstance(node, ast.Dict):
            continue
        fields = {}
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
                fields[key.value] = value.value
        if 'name' not in fields:
            continue
        if not ({'var_name', 'template', 'button', 'selection'} & set(fields)):
            continue
        names.add(fields['name'])
    return names


def shelf_options(shop):
    """
    读取经营端上架清单的可选商品（配置项 Product1-5 的候选项）。

    以 argument.yaml 的选项列表为准，保证生成的方案一定能被配置校验接受。

    Args:
        shop: 店铺类型标识

    Returns:
        list: 商品英文名列表（不含 'None'）
    """
    import yaml
    index = SHOP_TASKS.get(shop, (None, '0', None))[1]
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, 'module', 'config', 'argument', 'argument.yaml')
    try:
        with open(path, encoding='utf-8') as f:
            docs = list(yaml.safe_load_all(f))
    except (OSError, ValueError):
        return []
    node = (docs[0] or {}).get(f'_IslandBusinessProduct{index}')
    if not isinstance(node, dict):
        return []
    return [n for n in node.get('option', []) if n and n != 'None']


def target_stock(shop, product, shop_level='diamond', economy=None):
    """
    商品目标库存：单格可售量 + 安全余量。

    Args:
        shop: 店铺类型标识
        product: 商品英文名
        shop_level: 店铺等级
        economy: 经济库实例；None 用默认

    Returns:
        int: 目标库存（不低于 MIN_STOCK）
    """
    economy = economy or EconomyDatabase()
    level = SHOP_LEVELS.get(shop_level, SHOP_LEVELS['bronze'])
    per_slot = level.get('per_slot', 6)
    sellable = int(per_slot * level.get('sell_rate', 1.0) / 1.6)
    return max(sellable + 1, MIN_STOCK)


class ShopPlan(object):
    """单店方案：生产清单 + 上架清单。"""

    def __init__(self, shop, shop_level, season):
        self.shop = shop
        self.cn_name = SHOP_CN_NAMES.get(shop, shop)
        self.shop_level = shop_level
        self.season = season
        self.meals = []   # [(商品英文名, 目标库存)]
        self.shelf = []   # [商品英文名]
        self.notes = []   # [说明]

    def __repr__(self):
        return f'<ShopPlan {self.cn_name} meals={len(self.meals)} shelf={len(self.shelf)}>'


def plan_shop(shop, shop_level='diamond', season=None, warehouse=None,
              meals_slots=MEAL_SLOTS, shelf_slots=SHELF_SLOTS,
              economy=None, producible=None, exclude=None, shelf_pool=None,
              verified=None):
    """
    生成单店方案。

    Args:
        shop: 店铺类型标识
        shop_level: 店铺等级（决定单格容量与售出系数）
        season: 当前季节（spring/summer/autumn/winter）；None 只安排常驻商品
        warehouse: {商品: 库存}；传入时上架清单会剔除没货的商品
        meals_slots: 生产清单槽位数
        shelf_slots: 上架清单格数
        economy: 经济库实例
        producible: 本店可生产商品集合；None 自动从源码解析
        exclude: 额外排除的商品（如未解锁名单）
        shelf_pool: 可上架商品候选；None 自动从配置读取
        verified: 已验证可生产商品集合；非 None 时生产清单只从中取
            （避免排进未解锁商品导致 GameStuckError 重启循环）

    Returns:
        ShopPlan
    """
    economy = economy or EconomyDatabase(season=season)
    plan = ShopPlan(shop, shop_level, season)
    producible = code_products(shop) if producible is None else set(producible)
    exclude = set(exclude or ()) | load_unproducible(shop)
    shelf_pool = shelf_options(shop) if shelf_pool is None else list(shelf_pool)

    # ---- 生产清单：本店可生产、当季、利润优先 ----
    candidates = []
    for item in economy.get_products_by_shop(shop):
        name = item['name']
        if name not in producible:
            continue
        if name in exclude:
            plan.notes.append(f'跳过 {economy.cn_name(name)}：未解锁名单内')
            continue
        if verified is not None and name not in verified:
            plan.notes.append(f'跳过 {economy.cn_name(name)}：本账号未验证可生产')
            continue
        candidates.append(name)
    candidates = economy.filter_products(candidates, season=season)
    candidates = economy.sort_by_profit(candidates)
    for name in candidates[:meals_slots]:
        plan.meals.append((name, target_stock(shop, name, shop_level, economy)))

    plan_names = {n for n, _ in plan.meals}
    # ---- 上架清单：优先卖自己会补货的商品，其余用仓库现有高利润商品补满 ----
    pool = [n for n in shelf_pool if n not in exclude]
    pool = economy.filter_products(pool, season=season)
    in_plan = [n for n in economy.sort_by_profit(pool) if n in plan_names]
    others = [n for n in economy.sort_by_profit(pool) if n not in plan_names]
    ranked = in_plan + others

    if warehouse is not None:
        in_stock = [n for n in ranked if warehouse.get(n, 0) > 0]
        for name in ranked:
            if name not in in_stock:
                plan.notes.append(f'上架跳过 {economy.cn_name(name)}：仓库无库存')
        ranked = in_stock

    plan.shelf = ranked[:shelf_slots]
    return plan


def plan_all(shop_level='diamond', season=None, warehouse=None,
             shelf_slots=SHELF_SLOTS, shops=None, extra_exclude=None,
             verified_only=False):
    """
    生成全部店铺方案。

    Args:
        shop_level: 店铺等级
        season: 当前季节
        warehouse: {商品: 库存}；None 不做库存过滤
        shelf_slots: 上架格数
        shops: 限定店铺列表；None 全部

    Returns:
        dict: {店铺标识: ShopPlan}
    """
    economy = EconomyDatabase(season=season)
    extra_exclude = extra_exclude or {}
    verified = load_verified() if verified_only else {}
    out = {}
    for shop in (shops or ECONOMY_SHOPS):
        out[shop] = plan_shop(shop, shop_level=shop_level, season=season,
                              warehouse=warehouse, shelf_slots=shelf_slots,
                              economy=economy,
                              exclude=extra_exclude.get(shop, set()),
                              verified=verified.get(shop) if verified_only else None)
    return out


def config_patch(plans):
    """
    把方案转成配置补丁（可直接深合并进 ALAS.json）。

    Args:
        plans: {店铺标识: ShopPlan}

    Returns:
        dict: {'IslandRestaurant': {'IslandRestaurant': {...}},   # 生产清单
               'IslandBusiness': {'IslandBusinessShop1': {...}}}  # 上架清单

    Note:
        经营端配置的完整路径是 IslandBusiness.IslandBusinessShopN.ProductN，
        写到顶层（IslandBusinessShopN 直接挂根）ALAS 不会读取，保存时清空。
    """
    patch = {}
    business = {}
    for shop, plan in plans.items():
        task, index, _ = SHOP_TASKS[shop]
        group = {}
        for i in range(1, MEAL_SLOTS + 1):
            if i <= len(plan.meals):
                name, number = plan.meals[i - 1]
                group[f'Meal{i}'] = name
                group[f'MealNumber{i}'] = number
            else:
                group[f'Meal{i}'] = 'None'
                group[f'MealNumber{i}'] = 0
        patch[task] = {task: group}

        shelf = {}
        for i in range(1, SHELF_SLOTS + 1):
            shelf[f'Product{i}'] = plan.shelf[i - 1] if i <= len(plan.shelf) else 'None'
        business[f'IslandBusinessShop{index}'] = shelf
    if business:
        patch['IslandBusiness'] = business
    return patch


def config_key_values(plans):
    """
    方案 → 配置键值对（供 config.cross_set_many 写回，避免与 ALAS 保存竞争）。

    Args:
        plans: {店铺标识: ShopPlan}

    Returns:
        dict: {'IslandRestaurant.IslandRestaurant.Meal1': ...,
               'IslandBusiness.IslandBusinessShop1.Product1': ...}
    """
    values = {}
    for shop, plan in plans.items():
        task, index, _ = SHOP_TASKS[shop]
        for i in range(1, MEAL_SLOTS + 1):
            if i <= len(plan.meals):
                name, number = plan.meals[i - 1]
            else:
                name, number = 'None', 0
            values[f'{task}.{task}.Meal{i}'] = name
            values[f'{task}.{task}.MealNumber{i}'] = number
        for i in range(1, SHELF_SLOTS + 1):
            values[f'IslandBusiness.IslandBusinessShop{index}.Product{i}'] = (
                plan.shelf[i - 1] if i <= len(plan.shelf) else 'None')
    return values


def refresh_verified_from_logs(log_glob='log/*_ALAS.txt', keep=3):
    """
    从最近的 ALAS 日志重建「已验证可生产」名单并落盘。

    Args:
        log_glob: 日志通配路径（相对 ALAS 根目录）
        keep: 取最近几个日志文件

    Returns:
        dict: {店铺: 数量}
    """
    import glob
    paths = sorted(glob.glob(log_glob))[-keep:]
    data = mine_verified(paths)
    save_verified(data)
    return {shop: len(names) for shop, names in data.items()}


def apply_patch(config_path, patch):
    """
    深合并配置补丁并写回文件（先备份 .bak）。

    Args:
        config_path: ALAS.json 路径
        patch: config_patch() 的返回值

    Returns:
        str: 备份文件路径
    """
    with open(config_path, encoding='utf-8') as f:
        config = json.load(f)
    backup = config_path + '.bak'
    with open(backup, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    for key, value in patch.items():
        if isinstance(value, dict) and key in config and isinstance(config[key], dict):
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, dict) and sub_key in config[key]:
                    config[key][sub_key].update(sub_value)
                else:
                    config[key][sub_key] = sub_value
        else:
            config[key] = value
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return backup


def format_report(plans):
    """把方案渲染成可读文本。"""
    economy = EconomyDatabase()
    lines = []
    for shop, plan in plans.items():
        lines.append(f'== {plan.cn_name}（{shop}, 等级 {plan.shop_level}, '
                     f'季节 {plan.season or "未指定"}）==')
        if plan.meals:
            meals = ' ｜ '.join(f'{economy.cn_name(n)}x{q}' for n, q in plan.meals)
            lines.append(f'  生产清单: {meals}')
        else:
            lines.append('  生产清单: （空）')
        if plan.shelf:
            shelf = ' ｜ '.join(economy.cn_name(n) for n in plan.shelf)
            lines.append(f'  上架清单: {shelf}')
        else:
            lines.append('  上架清单: （空）')
        for note in plan.notes:
            lines.append(f'  注: {note}')
    return '\n'.join(lines)

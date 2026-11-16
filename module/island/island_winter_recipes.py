# Add by MHY, 冬季限定餐品从游戏表推导店铺、生产时间和材料。
# 价格与利润缺少来源，仅供冬季营业储备计算局部合并，保留全局经济表。
import re

from module.island.island_season import SEASONAL_ITEMS
from module.island_planner import settings_map
from module.island_planner.data import (
    DIC_ISLAND_ITEM,
    DIC_ISLAND_RECIPE,
    DIC_ISLAND_RESTAURANT_MENU_TO_RECIPE,
)

# 每分钟工作量：DAILY_WORKLOAD 是一个岗位一天(24h)的工作量，不要另抄 600。
WORKLOAD_PER_MINUTE = settings_map.DAILY_WORKLOAD // (24 * 60)

# 经济库另有命名的原料（物品 ID -> 经济库材料名）。其余原料先查现有映射表，
# 查不到再按游戏物品英文名规范化。每一条都被
# test_island_winter_recipes.test_derived_materials_match_economy_table 的对照锁定。
MATERIAL_ALIAS = {
    2521: 'fresh_fish',   # Freshwater Fish Meat -> 经济库 fresh_fish
    2522: 'sea_fish',     # Saltwater Fish Meat -> 经济库 sea_fish
    2600: 'pork',         # Fresh Meat -> 经济库 pork
    2601: 'egg',          # Eggs -> 经济库 egg
    2602: 'chicken',      # Poultry -> 经济库 chicken
    3004: 'wheat_flour',  # Flour（磨坊加工品）-> 经济库 wheat_flour
}


def _product_names():
    """物品 ID -> 经济库材料名，转置现有映射表；同一物品多种写法时以先出现的为准。"""
    names = {}
    for crops in settings_map.CROP_ITEM_IDS.values():
        for name, item_id in crops.items():
            names.setdefault(item_id, name)
    for name, item_id in settings_map.DISH_ITEM_IDS.items():
        names.setdefault(item_id, name)
    for line in settings_map.MANUFACTURE_PRODUCTS.values():
        for name, item_id in line['products'].items():
            names.setdefault(item_id, name)
    return names


PRODUCT_NAMES = _product_names()


def material_name(item_id):
    """
    配方材料物品 ID -> 经济库材料名；物品表里查不到返回 None（未知，不臆造名字）。

    先查现有映射表（作物/菜品/制造品），再查 MATERIAL_ALIAS，最后按游戏物品英文名规范化
    （Winter Shiitake -> winter_shiitake，与经济库的 matsutake 同一套写法）。
    """
    if item_id in PRODUCT_NAMES:
        return PRODUCT_NAMES[item_id]
    if item_id in MATERIAL_ALIAS:
        return MATERIAL_ALIAS[item_id]
    info = DIC_ISLAND_ITEM.get(item_id)
    if not info:
        return None
    return re.sub(r'[^a-z0-9]+', '_', info['name']['en'].lower()).strip('_') or None


def _menu_recipe_ids():
    """菜品物品 ID -> 配方 ID（各餐厅菜单表合并）。"""
    recipes = {}
    for menu in DIC_ISLAND_RESTAURANT_MENU_TO_RECIPE.values():
        for item_id, recipe_id in menu.items():
            recipes.setdefault(item_id, recipe_id)
    return recipes


MENU_RECIPE_IDS = _menu_recipe_ids()


def _build_recipes():
    """按冬季限定菜品推出 {菜品: {shop, time_min, materials}} 与推导失败原因。"""
    recipes = {}
    unknown = {}
    for shop, names in SEASONAL_ITEMS['winter'].items():
        for name in names:
            item_id = settings_map.DISH_ITEM_IDS.get(name)
            if item_id is None:
                continue  # 作物/制造品，不是店铺卖品
            recipe_id = MENU_RECIPE_IDS.get(item_id)
            recipe = DIC_ISLAND_RECIPE.get(recipe_id) if recipe_id else None
            if recipe is None:
                unknown[name] = f'游戏数据里没有菜品 {item_id} 的配方'
                continue
            if item_id not in recipe['commission_product']:
                unknown[name] = f'配方 {recipe_id} 的产物不是 {item_id}'
                continue
            workload = recipe['workload']
            if workload <= 0:
                unknown[name] = f'配方 {recipe_id} 工作量非法：{workload}'
                continue
            materials = {}
            missing = []
            for material_id, count in recipe['commission_cost'].items():
                material = material_name(material_id)
                if material is None:
                    missing.append(material_id)
                    continue
                materials[material] = materials.get(material, 0) + count
            if missing:
                unknown[name] = f'材料物品无法命名：{sorted(missing)}'
                continue
            recipes[name] = {
                'shop': shop,
                'time_min': workload / WORKLOAD_PER_MINUTE,
                'materials': materials,
            }
    return recipes, unknown


# 冬季菜品的三项已知数据（游戏数据表推导；未进表 = 未知，见 WINTER_MEAL_UNKNOWN）
WINTER_MEAL_RECIPES, WINTER_MEAL_UNKNOWN = _build_recipes()


def winter_recipe(name):
    """冬季菜品的 shop/time_min/materials 副本；不在表里返回 None。"""
    info = WINTER_MEAL_RECIPES.get(name)
    return dict(info, materials=dict(info['materials'])) if info else None


def economy_extension():
    """可直接并入 ECONOMY_PRODUCTS 的条目（新字典，只有 shop/time_min/materials）。"""
    return {name: {'shop': info['shop'], 'time_min': info['time_min'],
                   'materials': dict(info['materials'])}
            for name, info in WINTER_MEAL_RECIPES.items()}


def with_winter_meals(products):
    """
    补上冬季菜品的新经济表（浅拷贝，不改入参、不覆盖已有条目）。

    只用于按 shop/time_min/materials 计算的路径；缺价格字段的条目不能交给
    validate_economy() 或按利润排序的代码。
    """
    merged = dict(products)
    for name, info in economy_extension().items():
        merged.setdefault(name, info)
    return merged


def required_base_materials():
    """
    并入经济表前还缺的基础材料名：材料既不是商品也不在 BASE_MATERIALS 里。

    延迟导入经济库，避免与 island_economy 互相 import。
    """
    from module.island.island_economy import BASE_MATERIALS, ECONOMY_PRODUCTS

    known = set(ECONOMY_PRODUCTS) | set(BASE_MATERIALS)
    return frozenset(material for info in WINTER_MEAL_RECIPES.values()
                     for material in info['materials'] if material not in known)

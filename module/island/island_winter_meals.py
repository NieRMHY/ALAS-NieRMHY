# Add by MHY, 冬季任务独立使用营业后的有限产能，不写回货架或八个基础槽位。
import json
import math
import os
from collections import Counter
from pathlib import Path

from module.config.time_source import now
from module.island.island_economy import CAPACITY_BOOST_CHARACTERS, ECONOMY_PRODUCTS, SHOP_LEVELS
from module.island.island_planner import SHOP_TASKS, shop_post_number
from module.island.island_season import SEASONAL_ITEMS
from module.island.island_season_plan_data import meal_buffer, winter_task_enabled
from module.island.island_winter_recipes import with_winter_meals
from module.island.island_season_progress import active_slots, read_slots
from module.island.island_state import STATE_DIR

MEAL_RECIPES = with_winter_meals(ECONOMY_PRODUCTS)

TASK_MEALS = ('chicken_potato', 'rice_mango', 'strawberry_charlotte')
FINITE_MEALS = frozenset((*TASK_MEALS, 'cheese'))


def enabled(config):
    return (config.cross_get('IslandPlan.IslandPlan.Season', default=None) == 'winter'
            and winter_task_enabled(config))


def business_requirements(config, include_targets=True):
    direct = Counter()
    explicit = {}
    unknown = set()
    level = config.cross_get('IslandBusiness.IslandBusiness.ShopLevel', default='diamond')
    capacity = SHOP_LEVELS.get(level, SHOP_LEVELS['diamond'])
    base_capacity = capacity['per_slot']
    # Add by MHY, 冬季保留现有 Product 配置；方案生成格数不限制实际经营。
    slots = capacity['slots']
    season = config.cross_get('IslandPlan.IslandPlan.Season', default=None)
    excluded = {item for key, shops in SEASONAL_ITEMS.items() if key != season
                for items in shops.values() for item in items}
    for shop, (task, index, _) in SHOP_TASKS.items():
        staff = [config.cross_get(f'IslandBusiness.IslandBusinessShop{index}.Char{i}', default='None')
                 for i in (1, 2)]
        per_slot = base_capacity + int(any(shop in CAPACITY_BOOST_CHARACTERS.get(char, ())
                                          for char in staff))
        occupied = 0
        for slot in range(1, 6):
            item = config.cross_get(f'IslandBusiness.IslandBusinessShop{index}.Product{slot}', default='None')
            if not item or item == 'None' or item in excluded:
                continue
            if occupied >= slots:
                break
            occupied += 1
            if item in MEAL_RECIPES:
                direct[item] += per_slot
            else:
                unknown.add(shop)
        if not include_targets:
            continue
        for slot in range(1, 9):
            item = config.cross_get(f'{task}.{task}.Meal{slot}', default='None')
            qty = int(config.cross_get(f'{task}.{task}.MealNumber{slot}', default=0) or 0)
            if item in excluded:
                continue
            if item in MEAL_RECIPES:
                explicit[item] = max(explicit.get(item, 0), qty)
            elif item and item != 'None' and qty > 0:
                unknown.add(shop)
    # 配置是库存下限；直接销售与各套餐耗用则相加，避免夏洛特/芝士被 max 合并漏算。
    totals = {item: max(direct[item], explicit.get(item, 0))
              for item in direct.keys() | explicit.keys()}
    for _ in range(len(MEAL_RECIPES)):
        ingredients = Counter()
        for item, qty in totals.items():
            for material, count in MEAL_RECIPES[item]['materials'].items():
                if material in MEAL_RECIPES:
                    ingredients[material] += qty * count
        updated = {item: max(explicit.get(item, 0), direct[item] + ingredients[item])
                   for item in totals.keys() | ingredients.keys()}
        if updated == totals:
            return totals, unknown
        totals = updated
    raise ValueError('餐品配方存在循环依赖')


def task_targets(config, baseline, totals):
    if not enabled(config):
        return {}
    targets = {}
    for slot in active_slots(read_slots(config, 'winter', set(TASK_MEALS))):
        item = slot['item']
        targets[item] = baseline.get(item, 0) + slot['need'] + meal_buffer(config)
    # 跨店库存未知时先等简餐店巡检；在产夏洛特也已计入 totals，避免重复补芝士。
    charlotte = 'strawberry_charlotte'
    if charlotte in targets and totals.get(charlotte) is not None:
        gap = max(0, targets[charlotte] - totals[charlotte])
        targets['cheese'] = baseline.get('cheese', 0) + gap * 2
    return targets


def spare_minutes(config, baseline, unknown, shop):
    # 未知菜品也可能跨店消耗原料，整条任务链等待配方完整。
    if unknown:
        return 0
    task = SHOP_TASKS[shop][0]
    posts = shop_post_number(shop, config.cross_get(f'{task}.{task}.PostNumber', default=None))
    # Add by MHY, 库存目标不是每日销量；只预留一轮货架补货及其原料工时。
    # 普通目标缺口由运行时先补齐，不能把已备足的 270 杯咖啡每日重复计费。
    shelf, shelf_unknown = business_requirements(config, include_targets=False)
    if shelf_unknown:
        return 0
    normal = sum(qty * MEAL_RECIPES[item]['time_min'] for item, qty in shelf.items()
                 if MEAL_RECIPES[item]['shop'] == shop)
    return max(0, posts * 24 * 60 * 0.9 - normal)


def plan_batches(config, shop, baseline, unknown, totals, stock, spent=0):
    budget = max(0, spare_minutes(config, baseline, unknown, shop) - spent)
    targets = task_targets(config, baseline, totals)
    batches = {}
    for item, target in targets.items():
        if ECONOMY_PRODUCTS[item]['shop'] != shop or totals.get(item) is None:
            continue
        count = min(max(0, target - totals[item]), int((budget + 1e-8) // ECONOMY_PRODUCTS[item]['time_min']))
        if item == 'strawberry_charlotte':
            # 仅用现货，留足咖啡店直售、醒神套餐和普通夏洛特的芝士。
            cheese = stock.get('cheese')
            count = min(count, max(0, (cheese - baseline.get('cheese', 0)) // 2) if cheese is not None and cheese >= 0 else 0)
        if count:
            batches[item] = count
            budget -= count * ECONOMY_PRODUCTS[item]['time_min']
    return batches


def protected_away(config, item):
    active = {slot['item'] for slot in active_slots(read_slots(config, 'winter', set(TASK_MEALS)))}
    if 'strawberry_charlotte' in active:
        active.add('cheese')
    pending = [item]
    visited = set()
    while pending:
        product = pending.pop()
        if product in active:
            return True
        if product in visited:
            continue
        visited.add(product)
        pending.extend(MEAL_RECIPES.get(product, {}).get('materials', {}))
    return False


def ledger_path(config):
    name = Path(str(getattr(config, 'config_name', 'ALAS'))).name
    return Path(STATE_DIR) / f'winter_meals_{name}.json'


def load_ledger(config):
    path = ledger_path(config)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        data = {}
    # 损坏账本向上传递异常：重置配额后继续生产会造成超量。
    if not isinstance(data, dict):
        raise ValueError('冬季账本应为对象')
    for key in ('totals', 'spent'):
        values = data.setdefault(key, {})
        if not isinstance(values, dict):
            raise ValueError(f'冬季账本 {key} 应为对象')
        for value in values.values():
            if value is None and key == 'totals':
                continue
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < 0):
                raise ValueError(f'冬季账本 {key} 数量无效')
    if data.get('date') != now().date().isoformat():
        data['date'] = now().date().isoformat()
        data['spent'] = {}
        data['totals'] = {}
    return data


def save_ledger(config, data):
    path = ledger_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)

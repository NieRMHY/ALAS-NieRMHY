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
from module.island.island_state import state_file

UNPRODUCIBLE_FILE = state_file('island_unproducible.json')
# Add by MHY: 本账号「验证过能生产」的商品名单（从 ALAS 日志挖掘），
# 用于避免把未解锁商品排进生产清单（会 GameStuckError→重启→死循环）
VERIFIED_FILE = state_file('island_verified.json')

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
# 每店 2 个岗位 x 24 小时 = 48 时/天的生产上限（社区方案口径）
CAPACITY_HOURS = 48.0


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


def seasonal_products(shop):
    """
    本店的季节限定商品（来自 island_season.SEASONAL_ITEMS，全季节并集）。

    餐馆/白熊的季节菜是运行时按季节拼进 shop_items 的，源码 AST 里看不到，
    必须单独补上，否则会被误判成「代码未实现」。

    Args:
        shop: 店铺类型标识

    Returns:
        set: 商品英文名集合
    """
    try:
        from module.island.island_season import SEASONAL_ITEMS
    except ImportError:
        return set()
    names = set()
    for season_items in SEASONAL_ITEMS.values():
        names.update(season_items.get(shop, []))
    return names


def code_products(shop):
    """
    本店有按钮资源的商品（代码已实现）：店铺源码 + 季节限定表。

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
    return names | seasonal_products(shop)


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
    商品目标库存：一个货架堆叠（per_slot）+ 安全余量。

    历史误读：早期按 per_slot * sell_rate / 1.6 计算，得到 5 < per_slot(6)，
    货架永远填不满一格；per_slot 是「每格可堆叠数量」，不是售出速度。

    Args:
        shop: 店铺类型标识
        product: 商品英文名
        shop_level: 店铺等级
        economy: 经济库实例；None 用默认

    Returns:
        int: 目标库存（不低于 per_slot）
    """
    level = SHOP_LEVELS.get(shop_level, SHOP_LEVELS['bronze'])
    per_slot = int(level.get('per_slot', 6))
    return max(per_slot, MIN_STOCK)


def production_requirements(shop, meals, economy=None):
    """
    递归展开生产需求，区分本店产能与跨店原料。

    套餐原料里若有别店商品（如简餐的草莓夏洛特需要咖啡店的芝士），
    不能算进本店产能，也不能排进本店生产清单。

    Args:
        shop: 店铺类型标识
        meals: [(商品英文名, 数量)]
        economy: 经济库实例；None 用默认

    Returns:
        tuple: (own, cross, minutes)
            own: {商品: 数量} 本店需要生产的（含递归原料）
            cross: {店铺: {商品: 数量}} 需要别店生产的原料
            minutes: 本店占用的岗位分钟数
    """
    economy = economy or EconomyDatabase()

    def walk(name, qty, own, cross, depth=0):
        info = economy.get_product(name)
        if not info or depth > 5:
            return
        owner = info.get('shop')
        if owner == shop:
            own[name] = own.get(name, 0) + qty
        else:
            cross.setdefault(owner, {})
            cross[owner][name] = cross[owner].get(name, 0) + qty
            return  # 别店商品不再向下展开（由该店自行展开原料）
        for sub, per in info['materials'].items():
            if sub in economy.economy_products:
                walk(sub, qty * per, own, cross, depth + 1)

    own, cross = {}, {}
    for name, qty in meals:
        walk(name, qty, own, cross)
    minutes = sum(economy.get_product(n)['time_min'] * q for n, q in own.items())
    return own, cross, minutes


def merge_requirements(base_meals, extra_requirements, meals_slots=MEAL_SLOTS):
    """
    把跨店需求并入本店生产清单（不覆盖已有项，按利润排序后截断）。

    Args:
        base_meals: [(商品, 数量)] 原清单
        extra_requirements: {商品: 数量} 追加需求
        meals_slots: 生产清单槽位数

    Returns:
        list[(商品, 数量)]
    """
    merged = {name: qty for name, qty in base_meals}
    for name, qty in extra_requirements.items():
        merged[name] = max(merged.get(name, 0), qty)
    economy = EconomyDatabase()
    ordered = sorted(merged.items(), key=lambda kv: -economy.profit_per_min(kv[0]))
    return ordered[:meals_slots]


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
        self.stockpile = []  # [(商品, 目标数量)] 囤积物（赛季任务等，不上架）
        self.minutes = 0  # 预计占用的岗位分钟数（含递归原料）

    def __repr__(self):
        return f'<ShopPlan {self.cn_name} meals={len(self.meals)} shelf={len(self.shelf)}>'


def plan_shop(shop, shop_level='diamond', season=None, warehouse=None,
              meals_slots=MEAL_SLOTS, shelf_slots=None,
              economy=None, producible=None, exclude=None, shelf_pool=None,
              stock_have=None,
              verified=None, manual_shelf=None, capacity_ratio=0.9,
              stockpile=None):
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
        manual_shelf: 用户/社区方案指定的上架商品，优先占格
        capacity_ratio: 岗位工时预算占比（默认 0.9，即 43.2 时/天），超出则裁剪
        stockpile: {商品: 目标库存} 需要囤积的物品（赛季任务等）：用空闲产能生产，
            并且**不上架**，避免被卖掉或被每日订单/货运消耗

    Returns:
        ShopPlan
    """
    economy = economy or EconomyDatabase(season=season)
    plan = ShopPlan(shop, shop_level, season)
    if shelf_slots is None:
        # 默认按店铺等级的货架格数（钻石 4 格），多填的格子游戏会忽略
        shelf_slots = int(SHOP_LEVELS.get(shop_level, SHOP_LEVELS['diamond']).get('slots', SHELF_SLOTS))
    producible = code_products(shop) if producible is None else set(producible)
    exclude = set(exclude or ()) | load_unproducible(shop)
    shelf_pool = shelf_options(shop) if shelf_pool is None else list(shelf_pool)

    verified_set = set(verified) if verified is not None else None

    # ---- 第一步：定货架（卖什么）----
    # 货架每格同时只卖一件，所以看「单格售价」而不是生产指标；
    # 能持续补货（本账号验证过可生产）的商品优先，避免高价格子长期空着。
    stockpile = dict(stockpile or {})
    for name in shelf_pool:
        if name in exclude:
            plan.notes.append(f'跳过 {economy.cn_name(name)}：未解锁名单内')
    # 囤积物不上架：上了货架就会被顾客买走，赛季任务就凑不齐
    pool = [n for n in shelf_pool if n not in exclude and n not in stockpile]
    pool = economy.filter_products(pool, season=season)

    def shelf_rank(name):
        restockable = 0 if (verified_set is None or name in verified_set) else 1
        return restockable, -economy.price_of(name)

    ranked = sorted(pool, key=shelf_rank)
    if manual_shelf:
        # 玩家手动指定的上架清单优先（社区方案/个人偏好），其余格位由方案补
        manual = [n for n in manual_shelf if n in pool]
        ranked = manual + [n for n in ranked if n not in manual]
    if warehouse is not None:
        # 有库存的优先；但只有库存全为 0 时才整表过滤，避免读数失败导致空货架
        in_stock = [n for n in ranked if warehouse.get(n, 0) > 0]
        if in_stock:
            for name in ranked:
                if name not in in_stock:
                    plan.notes.append(f'上架跳过 {economy.cn_name(name)}：仓库无库存')
            ranked = in_stock
    plan.shelf = ranked[:shelf_slots]

    # ---- 第二步：按货架排生产（含本店原料）----
    # 逐项按产能预算接纳：放不下就不上这个货架商品（货架与生产永远一致），
    # 避免出现「货架摆着、生产却没排」的空格子。
    budget = CAPACITY_HOURS * capacity_ratio * 60
    shelf_keep, stock_only, seen = [], [], set()

    def requirements_of(names):
        acc, seen_local = [], set()

        def walk(n, depth=0):
            if depth > 5 or n in seen_local or n not in producible or n in exclude:
                return
            if verified_set is not None and n not in verified_set:
                return
            info = economy.get_product(n)
            if not info:
                return
            seen_local.add(n)
            acc.append(n)
            for sub in info['materials']:
                if sub in economy.economy_products:
                    walk(sub, depth + 1)

        for n in names:
            walk(n)
        return acc

    def top_level_hours(names):
        """只把顶层商品写进清单（原料交给 ALAS 展开），避免产能重复计算。"""
        meals = [(n, target_stock(shop, n, shop_level, economy)) for n in names]
        _, _, minutes = production_requirements(shop, meals, economy)
        return minutes

    for name in plan.shelf:
        if verified_set is not None and name not in verified_set:
            stock_only.append(name)
            plan.notes.append(f'上架 {economy.cn_name(name)} 未验证可生产，仅靠现有库存')
            continue
        minutes = top_level_hours(shelf_keep + [name])
        if minutes > budget and shelf_keep:
            plan.notes.append(
                f'产能不足: {economy.cn_name(name)} 不排产（含原料 {minutes / 60:.1f} 时 > '
                f'预算 {budget / 60:.1f} 时）')
            continue
        shelf_keep.append(name)
        seen = set(requirements_of(shelf_keep))  # 顶层 + 已覆盖的原料

    plan.shelf = shelf_keep + stock_only

    meals = [(n, target_stock(shop, n, shop_level, economy)) for n in shelf_keep]
    extra_names = economy.filter_products(
        [item['name'] for item in economy.get_products_by_shop(shop)], season=season)
    for name in extra_names:
        if len(meals) >= meals_slots or name in seen:
            continue
        if name not in producible or name in exclude:
            continue
        if verified_set is not None and name not in verified_set:
            continue
        candidate = meals + [(name, target_stock(shop, name, shop_level, economy))]
        _, _, minutes = production_requirements(shop, candidate, economy)
        if minutes > budget:
            continue  # 产能不够，跳过这个商品（不动已有货架需求）
        meals = candidate
        seen.add(name)

    # ---- 空闲产能生产囤积物（赛季任务物品：攒够就行，不上架）----
    # Add by MHY, 三条规则：
    #  1) 不排除「已经是货架商品原料」的物品：原料需求按货架销量算，和赛季任务要
    #     交的数量不是一个量级，跳过就永远攒不够（真机：禽肉快炒停在 20/100）。
    #  2) 按「还差得最少」排序，一个个做：先做完的先释放产能。真机 grill 一次要
    #     碳烤肉串(差 22 个=8.3 时) + 爆炒禽肉(差 100 个=76 时)，整店预算只有
    #     43.2 时，一起排必然都排不下；顺序做则前者做完产能就让给后者。
    #  3) 估算按「还差多少」而不是目标总量：仓库已有 248/270 时不该按从零做 270
    #     来估（真机会因此误判产能不足）。排不下就按剩余产能做一部分。
    # 囤积是追加需求，merge_requirements 按 max 合并不会重复生产，正常上架销售
    # 不受影响——shelf 先定，囤积只用剩下的产能。
    # Add by MHY, 独占式：一个店一次只放**一件**赛季物品进生产清单，做完再做下一件。
    # 用户口径：绝对不能影响上架销售（货架份额是硬的），赛季任务慢慢排队即可。
    # 为什么不按预算小时数判：真机 grill 货架本身只占 19.0 时（预算 43.2 时），
    # 余量 24.2 时；而爆炒禽肉要 63.8 时、碳烤肉串要 65.6 时——按预算判就是
    # 永远「排不下」、永远排队，一件也做不成。同时只放一件的话，货架那 19 时
    # 份额不会被抢，那件做多久都只是慢，符合「时间足够」。
    # 顺序按「还差得少」：最接近完成的先做完，先释放位置给下一件。
    stock_have = dict(stock_have or {})
    for name, target in sorted(
            stockpile.items(),
            key=lambda kv: (max(0, int(kv[1]) - int(stock_have.get(kv[0], 0))), kv[0])):
        if name not in producible or name in exclude:
            continue
        # 赛季物品不受「只排已验证商品」限制：它们没有别的生产途径，
        # 而白名单是靠历史成功记录挖出来的——没排过就永远不会进白名单。
        # 真机踩过：胡萝卜厚蛋烧/拿铁/便携快餐因此一直是 0。
        # 真正的不可能生产由 exclude（island_unproducible.json）兜底。
        if len(meals) >= meals_slots:
            break
        target = int(target)
        remaining = max(0, target - int(stock_have.get(name, 0)))
        if remaining <= 0:
            # 已经攒够，不需要再生产；它仍留在囤积名单里（不上架、不被买走），
            # 等任务提交后由自动刷新放回货架
            continue
        plan.notes.append(f'囤积 {economy.cn_name(name)}x{target}（还差 {remaining}）：'
                          f'本轮独占排产，做完/提交后再排下一件')
        meals = meals + [(name, target)]
        seen.add(name)
        plan.stockpile.append((name, target))
        break
    plan.meals = meals
    plan_names = {n for n, _ in plan.meals}
    if plan_names:
        plan.notes.append(f'在产: {", ".join(economy.cn_name(n) for n in plan_names)}')
    return plan


def plan_all(shop_level='diamond', season=None, warehouse=None,
             shelf_slots=None, shops=None, extra_exclude=None,
             verified_only=False, manual_shelf=None, capacity_ratio=0.9,
             stockpile=None, stock_have=None):
    """
    生成全部店铺方案。

    Args:
        shop_level: 店铺等级
        season: 当前季节
        warehouse: {商品: 库存}；None 不做库存过滤
        shelf_slots: 上架格数
        shops: 限定店铺列表；None 全部
        extra_exclude: {店铺: {商品}} 额外排除
        verified_only: 只排已验证可生产的商品
        manual_shelf: {店铺: [商品]} 用户指定的上架商品，优先占格

    Returns:
        dict: {店铺标识: ShopPlan}
    """
    economy = EconomyDatabase(season=season)
    extra_exclude = extra_exclude or {}
    verified = load_verified() if verified_only else {}
    order = list(shops or ECONOMY_SHOPS)
    out = {}
    for shop in order:
        out[shop] = plan_shop(shop, shop_level=shop_level, season=season,
                              warehouse=warehouse, shelf_slots=shelf_slots,
                              economy=economy,
                              exclude=extra_exclude.get(shop, set()),
                              verified=verified.get(shop) if verified_only else None,
                              manual_shelf=(manual_shelf or {}).get(shop),
                              capacity_ratio=capacity_ratio,
                              stockpile=(stockpile or {}).get(shop),
                              stock_have=stock_have)
    # ---- 跨店原料回填：别店需要的原料排到生产店 ----
    for shop in order:
        _, cross, _ = production_requirements(shop, out[shop].meals, economy)
        for owner, requirements in cross.items():
            if owner not in out or owner == shop:
                continue
            # 别店商品必须是该店可生产、且不在排除名单里
            usable = {n: q for n, q in requirements.items()
                      if n in code_products(owner)
                      and n not in load_unproducible(owner)
                      and n not in extra_exclude.get(owner, set())}
            if not usable:
                continue
            out[owner].meals = merge_requirements(out[owner].meals, usable)
            out[shop].notes.append(
                f"跨店原料: {', '.join(usable)} 由 {SHOP_CN_NAMES.get(owner, owner)} 生产")
            out[owner].notes.append(
                f"为 {SHOP_CN_NAMES.get(shop, shop)} 供应: {', '.join(usable)}")
    # ---- 产能核算：每店 2 个岗位 x 24 小时 ----
    for shop in order:
        own, _, minutes = production_requirements(shop, out[shop].meals, economy)
        out[shop].minutes = minutes
        out[shop].notes.append(
            f'预计占用产能 {minutes / 60:.2f} 时（上限 {CAPACITY_HOURS} 时，'
            f'{minutes / 60 / CAPACITY_HOURS * 100:.0f}%）')
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
    从最近的 ALAS 日志**补充**「已验证可生产」名单并落盘。

    Add by MHY：原来是整体覆盖，且只挖最近 keep 个日志。真机后果：log/ 下只有
    一个匹配文件时只挖出 4 个商品，把已有的 40 个冲成 4 个；某商品只要连续几天
    没被排产就会永久退出白名单——与 8b9bece27 修的 verified_only 死锁同源。
    改为并集，只增不减：历史验证过的商品不会因为近期没排产而被遗忘。
    商品若真的不再可生产，由 island_unproducible.json 兜底。

    Args:
        log_glob: 日志通配路径（相对 ALAS 根目录）
        keep: 取最近几个日志文件

    Returns:
        dict: {店铺: 数量}
    """
    import glob
    paths = sorted(glob.glob(log_glob))[-keep:]
    mined = mine_verified(paths)
    current = load_verified()
    merged = {}
    for shop in set(mined) | set(current):
        merged[shop] = set(mined.get(shop, ())) | set(current.get(shop, ()))
    save_verified(merged)
    return {shop: len(names) for shop, names in sorted(merged.items())}


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
        if plan.minutes:
            lines.append(f'  产能: {plan.minutes / 60:.2f} 时 / {CAPACITY_HOURS:.0f} 时 '
                         f'({plan.minutes / 60 / CAPACITY_HOURS * 100:.0f}%)')
        for note in plan.notes:
            lines.append(f'  注: {note}')
    return '\n'.join(lines)

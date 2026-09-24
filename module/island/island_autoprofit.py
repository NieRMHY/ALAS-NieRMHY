"""
岛屿计划 - AutoProfit 感知生产模块

在保留现有 Meal1-8 手动槽位兜底的前提下，为五家餐饮店铺提供
「利润驱动」的自动排产：根据经济数据库的利润/分钟排序，结合
仓库实际库存与店铺售卖容量，动态生成本轮生产计划。

接入方式（Add by MHY, 岛屿经济闭环）：
- 新模块零侵入：店铺子类在 __init__ 末尾调用
  setup_autoprofit(self) 即可启用感知层；
- IslandEconomyConfigError 仅在用户显式开启 AutoProfit 但配置矛盾时抛出；
- 手动槽位（Meal1-8）始终作为兜底：自动选品填满后仍剩余的缺口
  交给原有 _compute_base_demands 逻辑处理。
"""

from module.island.island_economy import (
    EconomyDatabase,
    ECONOMY_PRODUCTS,
    SHOP_CN_NAMES,
    get_global_economy,
)
from module.logger import logger

import json
import os


# AutoProfit 触发的最小补货阈值（目标库存 - 当前库存 > 此值才排产）
AUTOPROFIT_MIN_DEFICIT = 2

# 运行时学习的「不可生产商品」名单（账号未解锁/研发未完成，派单列表无图标）。
# 由选品连续失败触发记录，排产时排除，避免反复 GameStuckError 重启游戏。
UNPRODUCIBLE_FILE = os.path.join('config', 'island_unproducible.json')


def load_unproducible(shop):
    """
    读取本店已确认不可生产的商品名集合。

    Args:
        shop: 店铺类型标识

    Returns:
        set[str]
    """
    try:
        with open(UNPRODUCIBLE_FILE, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return set()
    return set(data.get(shop, []))


def remove_unproducible(shop, name):
    """
    解除禁用：账号已解锁该商品（选品列表出现其图标）时恢复排产。

    Args:
        shop: 店铺类型标识
        name: 商品英文名
    """
    try:
        with open(UNPRODUCIBLE_FILE, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    items = set(data.get(shop, []))
    if name not in items:
        return
    items.discard(name)
    if items:
        data[shop] = sorted(items)
    else:
        data.pop(shop, None)
    try:
        with open(UNPRODUCIBLE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError as e:
        logger.warning(f"[岛屿-AutoProfit] 更新不可生产名单失败: {e}")
        return
    logger.info(
        f"[岛屿-AutoProfit] {SHOP_CN_NAMES.get(shop, shop)} {name} 已在选品列表出现"
        f"（账号已解锁），解除禁用并恢复排产")


def add_unproducible(shop, name):
    """
    记录不可生产商品（选品连续失败时调用），供后续排产排除。

    Args:
        shop: 店铺类型标识
        name: 商品英文名
    """
    data = {}
    try:
        with open(UNPRODUCIBLE_FILE, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        pass
    items = set(data.get(shop, []))
    if name in items:
        return
    items.add(name)
    data[shop] = sorted(items)
    try:
        os.makedirs(os.path.dirname(UNPRODUCIBLE_FILE) or '.', exist_ok=True)
        with open(UNPRODUCIBLE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError as e:
        logger.warning(f"[岛屿-AutoProfit] 写入不可生产名单失败: {e}")
        return
    logger.warning(
        f"[岛屿-AutoProfit] {SHOP_CN_NAMES.get(shop, shop)} {name} 连续选品失败，"
        f"判定为未解锁，记入不可生产名单（后续不再排产，不重启游戏）")


def get_autoprofit_planner(shop, shop_level='diamond'):
    """
    规划器工厂：未知店铺（如 manufacture）返回 None，调用方保持原行为。

    Args:
        shop: 店铺类型标识
        shop_level: 店铺等级

    Returns:
        AutoProfitPlanner 或 None
    """
    try:
        return AutoProfitPlanner(shop=shop, shop_level=shop_level)
    except IslandEconomyConfigError:
        logger.info(f"[岛屿-AutoProfit] {shop} 不在餐饮经济库中，跳过感知生产")
        return None


class IslandEconomyConfigError(Exception):
    """AutoProfit 配置矛盾（如店铺等级未知），调用方可捕获后回退手动模式。"""


class AutoProfitPlanner:
    """
    单店铺的感知生产规划器

    根据店铺等级容量、经营消耗假设与仓库库存，计算每个商品的
    目标库存与补货缺口，输出按利润/分钟降序的生产计划。
    纯逻辑无 UI 依赖，可独立单测。
    """

    def __init__(self, shop, economy=None, shop_level='diamond',
                 safety_margin=2, max_items=None):
        """
        Args:
            shop: 店铺类型标识（restaurant/teahouse/...）
            economy: EconomyDatabase 实例；None 用全局单例
            shop_level: 店铺等级（bronze/silver/gold/diamond）
            safety_margin: 安全余量（目标库存之上的额外缓冲件数）
            max_items: 最多选品数；None 用店铺餐品格数
        """
        if shop not in ECONOMY_PRODUCTS and shop not in SHOP_CN_NAMES:
            # 未知店铺类型直接报配置错误，由上层回退手动模式
            raise IslandEconomyConfigError(f'未知店铺类型: {shop}')
        self.shop = shop
        self.economy = economy or get_global_economy()
        self.shop_level = shop_level
        self.safety_margin = safety_margin
        self.slots, self.per_slot, self.capacity = \
            EconomyDatabase.shop_capacity(shop_level)
        self.max_items = max_items or self.slots

    def target_stock(self, product, sell_rate=None):
        """
        计算商品目标库存：单格容量 / 售出系数 + 安全余量。

        Modify by MHY: 每个商品只占一个餐品格（每格 per_slot 个），
        目标库存按"单格售出量"计算而非整店容量——整店 24 件/商品
        远超单格销量，导致库存虚高、岗位提前闲置。

        Args:
            product: 商品英文名
            sell_rate: 售出系数；None 用店铺等级默认值

        Returns:
            int: 目标库存
        """
        from module.island.island_economy import SHOP_LEVELS
        lv = SHOP_LEVELS.get(self.shop_level, SHOP_LEVELS['bronze'])
        rate = sell_rate if sell_rate is not None else lv['sell_rate']
        # 售出系数含义：sell_rate/1.6 的加成（wiki 实测口径）
        sellable = int(self.per_slot * rate / 1.6)
        return sellable + self.safety_margin

    def build_plan(self, warehouse_counts, in_production=None, season=None,
                   exclude=(), available=None):
        """
        生成本轮生产计划。

        Args:
            warehouse_counts: {商品名: 仓库库存}
            in_production: {商品名: 在制数量}；None 视为空
            season: 季节；None 用经济库实例季节
            exclude: 排除商品（如本轮强制跳过项）
            available: 可生产商品名集合；None 不过滤。
                       Add by MHY：经济库收录 wiki 全部商品，但代码可能缺少
                       某个商品的按钮资源（如 lemon_shrimp/pineapple_juice），
                       不过滤会在排产时 KeyError。

        Returns:
            list[(商品名, 补货数量)] 按利润/分钟降序，只含有缺口的商品
        """
        in_production = in_production or {}

        def producible(name):
            return available is None or name in available

        # 1. 选品：利润排序取前 max_items 个（含当季季节限定），仅保留可生产的
        candidates = [p for p in self.economy.recommend_products(
            self.shop, season=season, top=self.max_items * 2, exclude=exclude)
            if producible(p['name'])][:self.max_items]
        if not candidates:
            return []

        # 2. 计算缺口
        plan = []
        for item in candidates:
            name = item['name']
            target = self.target_stock(name)
            current = warehouse_counts.get(name, 0) + in_production.get(name, 0)
            deficit = target - current
            if deficit > AUTOPROFIT_MIN_DEFICIT:
                plan.append((name, deficit))

        # 3. Add by MHY: 套餐原料联动——计划中的套餐若原料不足，把原料加入计划。
        # 否则会出现"计划全是套餐、原料为0、全部卡料→岗位闲置"的断链。
        for name, qty in list(plan):
            info = self.economy.get_product(name)
            if not info:
                continue
            for mat, per in info['materials'].items():
                if mat not in self.economy.economy_products or not producible(mat):
                    continue
                # 原料也是本店可生产商品（如冰咖啡/柑橘咖啡）且库存不足
                have = warehouse_counts.get(mat, 0) + in_production.get(mat, 0)
                need = per * qty
                if have < need:
                    mat_target = max(self.target_stock(mat), need)
                    mat_deficit = mat_target - have
                    if mat_deficit > AUTOPROFIT_MIN_DEFICIT and mat not in dict(plan):
                        plan.append((mat, mat_deficit))

        logger.info(
            f"[岛屿-AutoProfit] {SHOP_CN_NAMES.get(self.shop, self.shop)} "
            f"计划: {[(n, q) for n, q in plan]} (容量{self.capacity}, 等级{self.shop_level})")
        return plan

    def support_plan(self, name, warehouse_counts, in_production=None,
                     quantity=None, exclude=(), _depth=0):
        """
        上游原料保障计划：为生产 name 计算当前缺失、且本店可自产的中间品。

        与 build_plan 的原料联动不同，本方法不依赖"目标库存有缺口"——
        空岗填充商品即使库存已超目标仍需补齐原料，否则缺料会让岗位一直
        空着（真机：啾咖啡缺冰咖啡、啾啾简餐缺香橙派）。

        Args:
            name: 目标商品
            warehouse_counts: {商品: 仓库库存}
            in_production: {商品: 在制数量}
            quantity: 目标生产数量；None 用该商品目标库存
            exclude: 排除商品（不可生产名单）
            _depth: 递归深度（内部使用）

        Returns:
            list[(商品, 数量)]：缺失的可自产中间品，深层原料在前
        """
        if _depth > 4 or name in exclude:
            return []
        info = self.economy.get_product(name)
        if not info:
            return []
        in_production = in_production or {}
        qty = quantity or self.target_stock(name)
        plan = []
        for sub, per in info['materials'].items():
            if sub not in self.economy.economy_products or sub in exclude:
                continue
            need = per * qty
            have = warehouse_counts.get(sub, 0) + in_production.get(sub, 0)
            if have >= need:
                continue
            want = max(self.target_stock(sub), need - have)
            # 先保证中间品自身的原料，再排中间品本身
            plan.extend(self.support_plan(sub, warehouse_counts, in_production,
                                          want, exclude, _depth + 1))
            plan.append((sub, want))
        seen = set()
        out = []
        for item, q in plan:
            if item in seen:
                continue
            seen.add(item)
            out.append((item, q))
        return out

    def manual_slots_to_targets(self, post_products):
        """
        将手动槽位 (name, number) 列表转为保底目标映射。

        自动选品不会低于手动槽位设定值：取两者最大值。
        """
        return dict(post_products)


def merge_autoprofit_with_manual(auto_plan, manual_targets):
    """
    合并自动计划与手动槽位目标：同名取最大值，保持利润排序。

    Args:
        auto_plan: list[(name, qty)]（AutoProfitPlanner.build_plan 输出）
        manual_targets: {name: qty}（Meal1-8 槽位）

    Returns:
        list[(name, qty)] 按利润/分钟降序
    """
    merged = {}
    for name, qty in auto_plan:
        merged[name] = max(merged.get(name, 0), qty)
    for name, qty in manual_targets.items():
        merged[name] = max(merged.get(name, 0), qty)
    # 利润排序交给调用方（持有 economy 实例）处理，这里只按数量降序稳定输出
    return sorted(merged.items(), key=lambda x: -x[1])


def select_business_products(shop, available_names, manual_names=(), slots=None,
                             season=None, economy=None):
    """
    经营端自动选品（Add by MHY, 岛屿经济闭环）：为商店选择上架商品。

    与生产端同一经济库对齐：优先手动配置（Product1-5），不足 slots 个时
    从可上架商品中按利润/分钟补足；排除非当季限定。

    Args:
        shop: 店铺类型标识（restaurant/teahouse/...）
        available_names: 该商店经营界面可上架的商品英文名列表
                         （IslandBusiness.shop_products 的 name 集合）
        manual_names: 手动配置的商品名（保底，优先保留）
        slots: 上架槽位数（默认 5，即 Product1-5）
        season: 季节；None 用经济库实例季节
        economy: EconomyDatabase；None 用全局单例

    Returns:
        list[str]: 上架商品名，手动项在前（按原顺序），自动补足项按利润/分钟降序
    """
    eco = economy or get_global_economy()
    slots = slots or 5

    # 手动项去重保序，且必须在可上架列表内
    picked = []
    for name in manual_names:
        if name in available_names and name not in picked:
            picked.append(name)

    if len(picked) >= slots:
        return picked[:slots]

    # 候选 = 可上架 - 已选 - 非当季限定
    candidates = eco.filter_products(
        [n for n in available_names if n not in picked], season=season)
    ranked = eco.sort_by_profit(candidates)

    for name in ranked:
        if len(picked) >= slots:
            break
        picked.append(name)

    logger.info(
        f"[岛屿-AutoProfit] {SHOP_CN_NAMES.get(shop, shop)} 上架: {picked}"
        f"（手动 {len([n for n in manual_names if n in picked])} 项 + 自动补足）")
    return picked

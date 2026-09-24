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


# AutoProfit 触发的最小补货阈值（目标库存 - 当前库存 > 此值才排产）
AUTOPROFIT_MIN_DEFICIT = 2


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
                   exclude=()):
        """
        生成本轮生产计划。

        Args:
            warehouse_counts: {商品名: 仓库库存}
            in_production: {商品名: 在制数量}；None 视为空
            season: 季节；None 用经济库实例季节
            exclude: 排除商品（如本轮强制跳过项）

        Returns:
            list[(商品名, 补货数量)] 按利润/分钟降序，只含有缺口的商品
        """
        in_production = in_production or {}
        # 1. 选品：利润排序取前 max_items 个（含当季季节限定）
        candidates = self.economy.recommend_products(
            self.shop, season=season, top=self.max_items, exclude=exclude)
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
                if mat not in self.economy.economy_products:
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

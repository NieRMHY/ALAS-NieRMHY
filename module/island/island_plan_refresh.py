"""岛屿计划总览：一次性「刷新生产/上架方案」开关（Add by MHY，独立模块）。

WebUI 岛屿计划 → 总览 里勾选「刷新生产/上架方案」后，下一次任意岛屿任务
启动时会执行一次：

    1.（可选）从最近日志刷新「已验证可生产」白名单
    2. 按经济库重新生成生产清单 + 上架清单
    3. 通过 config.cross_set_many 写回配置（走 ALAS 自己的保存事务）
    4. 开关自动复位（一次性，不会每次任务都刷）

写配置用 config 对象而不是直接改文件，避免与调度器的保存互相覆盖。
"""
from module.island.island_economy import SHOP_CN_NAMES
from module.island.island_planner import (
    SHELF_SLOTS,
    SHOP_TASKS,
    config_key_values,
    plan_all,
    refresh_verified_from_logs,
)
from module.logger import logger

REFRESH_KEY = 'IslandPlan.IslandPlan.RefreshPlan'
VERIFIED_KEY = 'IslandPlan.IslandPlan.PlanVerifiedOnly'
MINE_KEY = 'IslandPlan.IslandPlan.PlanMineVerified'
SHELF_KEY = 'IslandPlan.IslandPlan.PlanShelfSlots'
SEASON_KEY = 'IslandPlan.IslandPlan.Season'


PAGE_FILE = 'config/island_season_plan_page.json'


def season_stockpile():
    """
    从赛季页面读数算出各店还要生产到什么数量（排进基础需求用）。

    之前方案刷新从不传 stockpile，导致「只在赛季任务里需要、却不在货架也不在
    基础需求里」的物品永远生产不出来——真机实测胡萝卜厚蛋烧、拿铁、便携快餐
    一直是 0，赛季任务卡死。页面读数是权威来源；材料类（农田牧场产物）没有
    对应店铺，交给农田牧场，直接跳过。

    Returns:
        dict: {店铺: {物品: 目标数量}}，没有缺口时返回 {}
    """
    import json
    from module.island.island_economy import ECONOMY_PRODUCTS

    try:
        with open(PAGE_FILE, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}

    stockpile = {}
    for info in data.values():
        item = info.get('item')
        if not item or info.get('claimed') or item not in ECONOMY_PRODUCTS:
            continue
        shop = ECONOMY_PRODUCTS[item].get('shop')
        need = int(info.get('need') or 0)
        have = int(info.get('have') or 0)
        if not shop or need <= have:
            continue
        # 目标给的是总量：planner 按目标库存排产
        stockpile.setdefault(shop, {})[item] = need
    return stockpile


def refresh_plan_if_requested(config, island=None):
    """
    总览开关勾选时刷新一次生产/上架方案。

    Args:
        config: AzurLaneConfig 实例
        island: 岛屿任务实例；传入时会顺带读取赛季「开发计划」页面

    Returns:
        bool: 是否执行了刷新
    """
    if not config.cross_get(REFRESH_KEY, default=False):
        return False

    logger.hr('岛屿方案刷新', level=2)
    stockpile = season_stockpile()
    try:
        # 赛季页读取已独立成 IslandSeasonPlan 任务（不再搭在每个岛屿任务上）
        season = config.cross_get(SEASON_KEY, default=None)
        verified_only = bool(config.cross_get(VERIFIED_KEY, default=True))
        shelf_slots = int(config.cross_get(SHELF_KEY, default=5) or 5)
        if config.cross_get(MINE_KEY, default=True):
            counts = refresh_verified_from_logs()
            logger.info(f"[岛屿-方案刷新] 已验证可生产白名单已更新: {counts}")

        # 玩家手动配置的上架清单优先保留（例如照抄社区方案），其余格位由方案补
        manual_shelf = {}
        for shop, (task, index, _) in SHOP_TASKS.items():
            manual = []
            for i in range(1, SHELF_SLOTS + 1):
                value = config.cross_get(
                    f'IslandBusiness.IslandBusinessShop{index}.Product{i}', default='None')
                if value and value != 'None':
                    manual.append(value)
            if manual:
                manual_shelf[shop] = manual
        if manual_shelf:
            logger.info(f"[岛屿-方案刷新] 保留手动上架: "
                        f"{ {SHOP_CN_NAMES.get(k, k): v for k, v in manual_shelf.items()} }")

        if stockpile:
            logger.info(f"[岛屿-方案刷新] 赛季缺口排产: "
                        f"{ {SHOP_CN_NAMES.get(k, k): v for k, v in stockpile.items()} }")
        plans = plan_all(season=season, shelf_slots=shelf_slots,
                         verified_only=verified_only, manual_shelf=manual_shelf,
                         stockpile=stockpile)
        values = config_key_values(plans)
        config.cross_set_many(values)
        logger.info(f"[岛屿-方案刷新] 已写入 {len(values)} 项配置（季节 {season}，"
                    f"只排已验证商品 {verified_only}）")
        for shop, plan in plans.items():
            meals = '、'.join(f'{n}x{q}' for n, q in plan.meals) or '（空）'
            logger.info(f"[岛屿-方案刷新] {plan.cn_name}: 生产 {meals}；"
                        f"上架 {plan.shelf or '（空）'}；"
                        f"产能 {plan.minutes / 60:.2f} 时")
    except Exception:
        logger.exception("[岛屿-方案刷新] 刷新失败，本次跳过")
    finally:
        # 一次性开关：无论成败都复位，避免每次岛屿任务重复刷新
        config.cross_set(REFRESH_KEY, False)
        try:
            config.update()
        except Exception:
            logger.exception("[岛屿-方案刷新] 配置保存失败")
    return True

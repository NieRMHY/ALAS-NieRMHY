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
    load_verified,
    plan_all,
    refresh_verified_from_logs,
)
from module.island.island_state import state_file
from module.logger import logger

REFRESH_KEY = 'IslandPlan.IslandPlan.RefreshPlan'
VERIFIED_KEY = 'IslandPlan.IslandPlan.PlanVerifiedOnly'
MINE_KEY = 'IslandPlan.IslandPlan.PlanMineVerified'
SHELF_KEY = 'IslandPlan.IslandPlan.PlanShelfSlots'
SEASON_KEY = 'IslandPlan.IslandPlan.Season'


PAGE_FILE = state_file('island_season_plan_page.json')
# 上次自动生成的上架清单，用于区分「用户手填」与「上次方案」（见 _manual_shelf）
GENERATED_FILE = state_file('island_plan_generated.json')


# 赛季任务物品的囤积余量（Add by MHY）：按任务提交数量生产，再多留这么多。
# 提交会把物品扣走，留一点免得刚达标就被别的菜谱消耗掉、又要反复补产。
# 真机实测不设余量时严重超产：蔬菜沙拉 102、苹果汁 317，而任务只需要 100 / 250。
SEASON_BUFFER = 20


def season_stockpile(season=None):
    """
    从赛季页面读数算出各店还要生产到什么数量（排进基础需求用）。

    之前方案刷新从不传 stockpile，导致「只在赛季任务里需要、却不在货架也不在
    基础需求里」的物品永远生产不出来——真机实测胡萝卜厚蛋烧、拿铁、便携快餐
    一直是 0，赛季任务卡死。页面读数是权威来源；材料类（农田牧场产物）没有
    对应店铺，交给农田牧场，直接跳过。

    Add by MHY, 已提交（done）的物品必须排除：提交后本季不再需要它，否则库存被
    别的菜谱消耗到需求线以下时又会被排回生产目标——真机上「提交过了还在产」
    就是这么来的。蔬菜沙拉真机实测：done 之后库存 2100 只是碰巧高过需求 100 才
    没被排产，掉下来就会被重新排进去。

    目标数量是「任务需求 + SEASON_BUFFER」：按需生产，不再让物品无限堆积。

    Args:
        season: 赛季；传入时排除已提交的物品

    Returns:
        dict: {店铺: {物品: 目标数量}}，没有缺口时返回 {}
    """
    import json
    from module.island.island_away_cook import done_items, load_notified
    from module.island.island_economy import ECONOMY_PRODUCTS

    try:
        with open(PAGE_FILE, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}

    done = done_items(season, load_notified()) if season else set()
    stockpile = {}
    for info in data.values():
        item = info.get('item')
        if not item or item in done or info.get('claimed') or item not in ECONOMY_PRODUCTS:
            continue
        shop = ECONOMY_PRODUCTS[item].get('shop')
        need = int(info.get('need') or 0)
        have = int(info.get('have') or 0)
        if not shop or need + SEASON_BUFFER <= have:
            continue
        # 目标给的是总量：planner 按目标库存排产。多留 SEASON_BUFFER 份余量，
        # 刚好够提交一次又不至于堆在仓库里。
        stockpile.setdefault(shop, {})[item] = need + SEASON_BUFFER
    return stockpile


def load_generated():
    """读取上次自动生成的上架清单。"""
    import json
    try:
        with open(GENERATED_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_generated(plans):
    """记录本次自动生成的上架清单，供下次刷新区分自动方案与手动配置。"""
    import json
    import os
    data = {shop: list(plan.shelf) for shop, plan in plans.items()}
    directory = os.path.dirname(GENERATED_FILE)
    try:
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        with open(GENERATED_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    except OSError:
        logger.warning('[岛屿-方案刷新] 上架清单落盘失败，下次可能误判为手动配置')


def _manual_shelf(config):
    """
    取出玩家真正手动填写的上架清单。

    Product1-5 正是上一次刷新自己写进去的键。不加区分的话，第二次刷新起会把
    「上次的自动方案」当成用户手动清单无条件置顶，货架从此再也换不了品
    （离线实测：带 manual_shelf 时 5 家店的 shelf 与线上完全一致，等于没刷）。
    因此只有当前值与上次自动生成值**不同**时，才认定为手动配置。

    Args:
        config: AzurLaneConfig 实例

    Returns:
        dict: {店铺: [商品]}
    """
    generated = load_generated()
    manual = {}
    for shop, (task, index, _) in SHOP_TASKS.items():
        current = []
        for i in range(1, SHELF_SLOTS + 1):
            value = config.cross_get(
                f'IslandBusiness.IslandBusinessShop{index}.Product{i}', default='None')
            if value and value != 'None':
                current.append(value)
        if not current:
            continue
        if current == list(generated.get(shop, [])):
            continue  # 与上次自动生成一致：仍是方案的产物，不该钉死
        manual[shop] = current
    return manual


def refresh_plan_if_requested(config):
    """
    总览开关勾选时刷新一次生产/上架方案。

    Args:
        config: AzurLaneConfig 实例

    Returns:
        bool: 是否执行了刷新
    """
    if not config.cross_get(REFRESH_KEY, default=False):
        return False

    logger.hr('岛屿方案刷新', level=2)
    # 赛季页读取已独立成 IslandSeasonPlan 任务（不再搭在每个岛屿任务上）
    season = config.cross_get(SEASON_KEY, default=None)
    # 排产目标要排除本赛季已提交的物品，否则库存掉下来会被重新排产
    stockpile = season_stockpile(season)
    try:
        verified_only = bool(config.cross_get(VERIFIED_KEY, default=True))
        shelf_slots = int(config.cross_get(SHELF_KEY, default=5) or 5)
        if config.cross_get(MINE_KEY, default=True):
            counts = refresh_verified_from_logs()
            logger.info(f"[岛屿-方案刷新] 已验证可生产白名单已更新: {counts}")
        if verified_only:
            # 某店没有白名单条目时 plan_all 会整个跳过可生产过滤（fail-open）。
            # 这道闸门本是防「未解锁商品选品失败 -> GameStuckError -> 重启游戏」，
            # 静默失效代价很高，所以显式告警。
            verified = load_verified()
            missing = [SHOP_CN_NAMES.get(s, s) for s in SHOP_TASKS if not verified.get(s)]
            if missing:
                logger.warning(f"[岛屿-方案刷新] 以下店铺没有已验证名单，本次不做可生产"
                               f"过滤（未解锁商品可能触发选品失败重启）: {missing}")

        # 玩家手动配置的上架清单优先保留（例如照抄社区方案），其余格位由方案补
        manual_shelf = _manual_shelf(config)
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
        save_generated(plans)
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

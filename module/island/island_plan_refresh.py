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
# 上次自动请求刷新时的赛季缺口快照（见 request_refresh_on_gap_change）
GAP_FILE = state_file('island_season_gap.json')
# 上次自动生成的上架清单，用于区分「用户手填」与「上次方案」（见 _manual_shelf）
GENERATED_FILE = state_file('island_plan_generated.json')


# 赛季任务物品的囤积余量（Add by MHY）：按任务提交数量生产，再多留这么多。
# 提交会把物品扣走，留一点免得刚达标就被别的菜谱消耗掉、又要反复补产。
# 真机实测不设余量时严重超产：蔬菜沙拉 102、苹果汁 317，而任务只需要 100 / 250。
SEASON_BUFFER = 20


def season_stockpile(progress=None):
    """
    从赛季进度算出各店还要生产到什么数量（排进基础需求用）。

    之前方案刷新从不传 stockpile，导致「只在赛季任务里需要、却不在货架也不在
    基础需求里」的物品永远生产不出来——真机实测胡萝卜厚蛋烧、拿铁、便携快餐
    一直是 0，赛季任务卡死。材料类（农田牧场产物）没有对应店铺，交给农田牧场，
    直接跳过。

    Modify by MHY, 进度改为仓库读数（见 island_season_progress），不再依赖赛季页
    OCR 与「已领取/done」标记：提交任务后仓库数量掉下去，缺口自然重新出现；
    要停止某项生产，把配置里该物品的需求数量改成 0 即可。

    目标数量是「任务需求 + SEASON_BUFFER」：按需生产，不再让物品无限堆积。

    Args:
        progress: {物品: (当前数量, 需求数量)}，None 视为没有进度

    Returns:
        dict: {店铺: {物品: 目标数量}}，没有缺口时返回 {}
    """
    from module.island.island_economy import ECONOMY_PRODUCTS

    # Modify by MHY, 进度来自仓库读数（island_season_progress），不再读赛季页快照
    if progress is None:
        return {}
    stockpile = {}
    for item, (have, need) in progress.items():
        if item not in ECONOMY_PRODUCTS:
            continue
        shop = ECONOMY_PRODUCTS[item].get('shop')
        if not shop or not need or need + SEASON_BUFFER <= have:
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


def season_have(progress):
    """
    赛季进度里各物品的当前数量（供 planner 按「还差多少」估算产能）。

    不按目标总量估算：仓库已有 248/270 时，按从零做 270 估会被误判产能不足
    （真机：碳烤肉串就差 22 个却被估成 102 时，远超整店预算 43.2 时）。

    Args:
        progress: {物品: (当前数量, 需求数量)}

    Returns:
        dict: {物品: 当前数量}
    """
    return {item: int(have) for item, (have, _need) in (progress or {}).items()}


def current_progress(config, season):
    """
    读取当前赛季进度（仓库读数 + 用户手改），读不到赛季时返回 None。

    Args:
        config: AzurLaneConfig 实例
        season: 赛季

    Returns:
        dict | None: {物品: [当前数量, 需求数量]}
    """
    from module.island.island_economy import ECONOMY_PRODUCTS
    from module.island.island_season_progress import load_progress

    if not season:
        return None
    return load_progress(config, season, set(ECONOMY_PRODUCTS))


def load_gap():
    """上次自动请求刷新时记录的赛季缺口与已提交集合。"""
    import json
    try:
        with open(GAP_FILE, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return set(), set()
    return set(data.get('gap') or ()), set(data.get('done') or ())


def save_gap(gap, done):
    """记录本次快照。"""
    import json
    import os
    try:
        directory = os.path.dirname(GAP_FILE)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        with open(GAP_FILE, 'w', encoding='utf-8') as f:
            json.dump({'gap': sorted(gap), 'done': sorted(done)}, f,
                      ensure_ascii=False, indent=1)
    except OSError:
        logger.warning('[岛屿-方案刷新] 赛季缺口快照保存失败')


def flatten_gap(stockpile):
    """{店铺: {物品: 数量}} -> {'店铺/物品'} 集合，便于比对。"""
    return {f'{shop}/{item}' for shop, items in (stockpile or {}).items()
            for item in items}


def request_refresh_on_gap_change(config, season):
    """
    赛季缺口出现新项时自动请求一次方案刷新（Add by MHY）。

    货架方案是一次性快照：物品进囤积时会被从货架剔除（摆上货架就会被顾客买走，
    赛季任务就凑不齐）——必须重新生成方案才会生效。靠手勾「刷新生产/上架方案」
    容易忘，所以这里比对快照自动触发。

    只在「出现新缺口」时触发：要把该物品从货架挪进囤积。

    「攒够目标」不触发：那时物品正停在囤积里、既不上架也不被买走，刷新反而会把它
    推回货架，被买空后又变成缺口，来回翻。你提交任务后仓库数量掉下去，缺口会重新
    出现，这时同样走「新缺口」触发，不再需要「已提交」标记。

    Args:
        config: AzurLaneConfig 实例
        season: 赛季

    Returns:
        bool: 是否请求了刷新
    """
    gap = flatten_gap(season_stockpile(current_progress(config, season)))
    old_gap, _ = load_gap()
    if gap == old_gap:
        return False
    save_gap(gap, set())
    if not (gap - old_gap):
        # 只是有物品攒够了：让它留在囤积里，不动方案
        return False
    config.cross_set(REFRESH_KEY, True)
    try:
        config.update()
    except Exception:
        logger.exception('[岛屿-方案刷新] 自动刷新请求保存失败')
        return False
    return True


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
    season = config.cross_get(SEASON_KEY, default=None)
    # Modify by MHY, 赛季进度取自仓库读数（island_season_progress），不再读赛季页
    progress = current_progress(config, season)
    stockpile = season_stockpile(progress)
    # 产能估算按「还差多少」，不是按目标总量
    stock_have = season_have(progress)
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
                         stockpile=stockpile, stock_have=stock_have)
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

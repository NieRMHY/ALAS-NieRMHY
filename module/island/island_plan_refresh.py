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


def sync_season_plan_page(config, island):
    """
    读取赛季「开发计划」页面并落盘（先只观察，不改行为）。

    页面是任务进度的真相来源：仓库库存只能反推，页面能直接给出每项任务的
    已有/需要，以及哪些任务已从列表消失（提交完成）。第一次跑先记录结果，
    确认页面语义后再用它驱动轮换与「已完成」判定。

    Args:
        config: AzurLaneConfig 实例
        island: 岛屿任务实例（提供 UI 能力）

    Returns:
        dict: {任务名: {'item', 'have', 'need'}}
    """
    import json
    import os

    from module.island.island_season_plan_data import plan_tasks
    from module.island.island_season_plan_reader import read_season_plan_page

    season = config.cross_get(SEASON_KEY, default=None)
    if not season:
        return {}
    result = read_season_plan_page(island, season)
    if not result:
        return {}

    try:
        directory = os.path.dirname(PAGE_FILE)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        with open(PAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, sort_keys=True)
    except OSError:
        logger.warning('[岛屿-赛季计划] 页面结果落盘失败')

    expected = [task for task, _, _ in plan_tasks(season)]
    missing = [task for task in expected if task not in result]
    for task, info in sorted(result.items()):
        logger.info(f"[岛屿-赛季计划] {task}: {info['have']}/{info['need']}（{info['item']}）")
    logger.info(f"[岛屿-赛季计划] 页面共 {len(result)} 项，未出现在页面上的 "
                f"{len(missing)} 项: {missing}")
    return result


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
    try:
        if island is not None:
            try:
                sync_season_plan_page(config, island)
            except Exception:
                logger.exception('[岛屿-赛季计划] 页面读取异常，已跳过')
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

        plans = plan_all(season=season, shelf_slots=shelf_slots,
                         verified_only=verified_only, manual_shelf=manual_shelf)
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

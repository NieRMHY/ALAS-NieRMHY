"""岛屿计划总览：一次性「刷新生产/上架方案」开关（Add by MHY，独立模块）。

WebUI 岛屿计划 → 总览 里勾选「刷新生产/上架方案」后，下一次任意岛屿任务
启动时会执行一次：

    1.（可选）从最近日志刷新「已验证可生产」白名单
    2. 按经济库重新生成生产清单 + 上架清单
    3. 通过 config.cross_set_many 写回配置（走 ALAS 自己的保存事务）
    4. 开关自动复位（一次性，不会每次任务都刷）

写配置用 config 对象而不是直接改文件，避免与调度器的保存互相覆盖。
"""
from module.island.island_planner import (
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
    try:
        season = config.cross_get(SEASON_KEY, default=None)
        verified_only = bool(config.cross_get(VERIFIED_KEY, default=True))
        shelf_slots = int(config.cross_get(SHELF_KEY, default=5) or 5)
        if config.cross_get(MINE_KEY, default=True):
            counts = refresh_verified_from_logs()
            logger.info(f"[岛屿-方案刷新] 已验证可生产白名单已更新: {counts}")

        plans = plan_all(season=season, shelf_slots=shelf_slots,
                         verified_only=verified_only)
        values = config_key_values(plans)
        config.cross_set_many(values)
        logger.info(f"[岛屿-方案刷新] 已写入 {len(values)} 项配置（季节 {season}，"
                    f"只排已验证商品 {verified_only}）")
        for shop, plan in plans.items():
            meals = '、'.join(f'{n}x{q}' for n, q in plan.meals) or '（空）'
            logger.info(f"[岛屿-方案刷新] {plan.cn_name}: 生产 {meals}；"
                        f"上架 {plan.shelf or '（空）'}")
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

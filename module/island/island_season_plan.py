"""岛屿赛季任务（开发季 → 开发计划）独立任务（Add by MHY）。

为什么独立成任务：赛季页面的读取原本挂在 Island.__init__ 的刷方案钩子上，
结果任何岛屿任务（农田、店铺、牧场…）都会跑一遍赛季页导航，既拖慢其它
任务，也容易把上层任务留在无法识别的页面。

本任务只做两件事：
    1. 读「开发季 → 开发计划」页面，拿到每项任务的进度与「已领取」标记
    2. 用「已领取」同步「已完成」状态，让常驻餐品不再重复生产已交过的物品

提交动作暂未实现（用户手动提交）；页面数据会落盘供排查。
"""
from module.island.island_away_cook import mark_claimed, load_notified, save_notified
from module.island.island_plan_refresh import PAGE_FILE
from module.island.island_season import SeasonConfig
from module.island.island_season_plan_data import cn_name
from module.island.island_season_plan_reader import read_season_plan_page
from module.island.island import Island
from module.logger import logger


class IslandSeasonPlan(Island):
    """赛季任务：读取开发计划页面并同步已完成状态。"""

    # 页面进度变化只跟生产挂钩，几小时同步一次足够
    DELAY_MINUTE = 180

    def run(self):
        logger.hr('岛屿赛季任务', level=1)
        try:
            self._run()
        finally:
            # 不设延迟会被调度器反复触发（真机踩过：一分钟内跑了三次）
            self.config.task_delay(minute=self.DELAY_MINUTE)

    def _run(self):
        season = SeasonConfig(self.config).season
        if not season:
            logger.warning('[岛屿-赛季任务] 未配置赛季，跳过')
            return

        result = read_season_plan_page(self, season)
        if not result:
            logger.warning('[岛屿-赛季任务] 未读到赛季任务，跳过')
            return

        self._log_progress(result)
        self._save_page(result)
        if self.config.IslandSeasonPlan_SyncDone:
            self._sync_done(season, result)

    def _save_page(self, result):
        """页面结果落盘，便于事后排查（config/island_season_plan_page.json）。"""
        import json
        import os
        try:
            directory = os.path.dirname(PAGE_FILE)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            with open(PAGE_FILE, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2, sort_keys=True)
        except OSError:
            logger.warning('[岛屿-赛季任务] 页面结果落盘失败')

    def _log_progress(self, result):
        """把页面读到的进度写进日志，便于核对。"""
        for task, info in sorted(result.items(), key=lambda kv: kv[1]['have'] / max(kv[1]['need'], 1)):
            flag = '已领取' if info.get('claimed') else f"{info['have']}/{info['need']}"
            logger.info(f"[岛屿-赛季任务] {task}: {flag}（{cn_name(info['item'])}）")
        claimed = [t for t, i in result.items() if i.get('claimed')]
        logger.info(f"[岛屿-赛季任务] 页面共 {len(result)} 项，已领取 {len(claimed)} 项: {claimed}")

    def _sync_done(self, season, result):
        """
        用页面上的「已领取」标记同步已完成状态。

        已领取 = 任务已提交，之后不必再生产；反过来不带已领取标记的物品会
        被取消 done（例如赛季初重置、或之前靠库存掉幅误判的情况）。
        """
        notified = load_notified()
        changed = mark_claimed(season, result, notified)
        save_notified(notified)
        if changed:
            logger.info(f"[岛屿-赛季任务] 已完成状态已同步: {changed}")
        else:
            logger.info('[岛屿-赛季任务] 已完成状态无变化')

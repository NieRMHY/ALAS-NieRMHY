"""岛屿赛季任务（开发季 → 开发计划）纯逻辑任务（Add by MHY）。

Modify by MHY, 2026-10-10：不再进游戏 OCR 赛季页。赛季页的进度文字会被误读
（拿铁 82 读成 282、牛奶 7250 这类前缀多读），而邮件、方案刷新、常驻餐品轮换都依赖
这个数。店铺每次收取生产、核对销售前都会进仓库读准确库存，并记进配置里的
IslandSeasonPlan.Progress（见 island_season_progress），本任务只做三件事：

    1. 进度达标（仓库里已攒够）就发一封邮件提醒你去提交
    2. 缺口出现新项时，自动请求一次生产/上架方案刷新（把物品挪进囤积、不上架）
    3. 之后由店铺的空闲产能生产逻辑接着补缺口（该逻辑不变）

本任务不碰游戏画面：没有设备操作，也不会因为页面识别失败而重启游戏。
页面读取器（island_season_plan_reader）与就地提交逻辑作为储备保留在仓库里。

收餐会触发本任务，限流避免每家店铺跑完都真算一遍。
"""
from module.island.island_away_cook import notify_ready_from_progress
from module.island.island_plan_refresh import current_progress, request_refresh_on_gap_change
from module.island.island_season import SeasonConfig
from module.island.island_state import state_file
from module.logger import logger


class IslandSeasonPlan:
    """赛季任务：按仓库读数判断达标、发邮件、触发方案刷新。"""

    MIN_INTERVAL_MINUTE = 20
    DELAY_MINUTE = 30
    LAST_RUN_FILE = state_file('island_season_plan_last.json')

    def __init__(self, config, device=None):
        self.config = config
        self.device = device

    def run(self):
        logger.hr('岛屿赛季任务', level=1)
        try:
            if self._too_soon():
                logger.info(f'[岛屿-赛季任务] 距上次不足 {self.MIN_INTERVAL_MINUTE} 分钟，跳过')
                return
            self._run()
            self._mark_ran()
        finally:
            # 无论成功、跳过还是抛异常都必须排下次运行时间：否则任务会立刻被
            # 调度器再次触发，配合店铺的 task_call 形成连环重启（真机事故：
            # _too_soon 里的 ImportError 导致 18:14 起反复重启游戏）
            self.config.task_delay(minute=self.DELAY_MINUTE)

    def _too_soon(self):
        """距上次实际计算是否太近（收餐触发很频繁，需要限流）。"""
        import json
        # 注意：时间源是 module.config.time_source.timestamp()，不是 current_time
        from module.config.time_source import timestamp
        try:
            with open(self.LAST_RUN_FILE, encoding='utf-8') as f:
                last = json.load(f).get('last')
        except (OSError, ValueError):
            return False
        if not last:
            return False
        return (timestamp() - float(last)) < self.MIN_INTERVAL_MINUTE * 60

    def _mark_ran(self):
        """记录本次实际计算时间。"""
        import json
        import os
        from module.config.time_source import timestamp
        try:
            directory = os.path.dirname(self.LAST_RUN_FILE)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            with open(self.LAST_RUN_FILE, 'w', encoding='utf-8') as f:
                json.dump({'last': timestamp()}, f)
        except OSError:
            logger.warning('[岛屿-赛季任务] 记录运行时间失败')

    def _run(self):
        season = SeasonConfig(self.config).season
        if not season:
            logger.warning('[岛屿-赛季任务] 未配置赛季，跳过')
            return
        progress = current_progress(self.config, season)
        self._log_progress(progress)

        # 赛季缺口出现新项时自动请求刷新方案：货架方案是一次性快照，物品攒够或
        # 被订单消耗之后不会自己回到货架/囤积，靠手勾容易忘。
        try:
            if request_refresh_on_gap_change(self.config, season):
                logger.info('[岛屿-赛季任务] 赛季缺口变化，已请求刷新生产/上架方案')
        except Exception:
            logger.exception('[岛屿-赛季任务] 自动请求方案刷新失败')
        notify_ready_from_progress(self.config, season, progress)

    @staticmethod
    def _log_progress(progress):
        """把当前进度写进日志，便于核对。"""
        from module.island.island_season_plan_data import cn_name
        for item, (have, need) in sorted(progress.items(),
                                         key=lambda kv: kv[1][0] / max(kv[1][1], 1)):
            logger.info(f'[岛屿-赛季任务] {cn_name(item)}: {have}/{need}')

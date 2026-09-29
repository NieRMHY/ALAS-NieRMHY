"""岛屿赛季任务（开发季 → 开发计划）独立任务（Add by MHY）。

为什么独立成任务：赛季页面的读取原本挂在 Island.__init__ 的刷方案钩子上，
结果任何岛屿任务（农田、店铺、牧场…）都会跑一遍赛季页导航，既拖慢其它
任务，也容易把上层任务留在无法识别的页面。

本任务只做两件事：
    1. 读「开发季 → 开发计划」页面，拿到每项任务的进度与「已领取」标记
    2. 用「已领取」同步「已完成」状态，让常驻餐品不再重复生产已交过的物品

提交动作暂未实现（用户手动提交）；页面数据会落盘供排查。
"""
from module.island.island_away_cook import (
    load_notified,
    mark_claimed,
    notify_ready_from_page,
    ready_to_submit,
    save_notified,
)
from module.island.island_plan_refresh import PAGE_FILE
from module.island.island_season import SeasonConfig
from module.island.island_season_plan_data import cn_name
from module.island.island_season_plan_reader import read_season_plan_page
from module.island.island import Island
from module.logger import logger


class IslandSeasonPlan(Island):
    """赛季任务：读取开发计划页面并同步已完成状态。"""

    # 收餐会触发本任务；限流避免每家店铺跑完都真读一遍页面
    MIN_INTERVAL_MINUTE = 20
    DELAY_MINUTE = 30
    LAST_RUN_FILE = 'config/island_season_plan_last.json'

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
        """距上次实际读取是否太近（收餐触发很频繁，需要限流）。"""
        import json
        import os
        # 注意：时间源是 module.config.time_source.timestamp()，
        # 之前误写成 current_time（那里叫 now），真机直接 ImportError
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
        """记录本次实际读取时间。"""
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

        result = read_season_plan_page(self, season)
        if not result:
            logger.warning('[岛屿-赛季任务] 未读到赛季任务，跳过')
            return

        self._log_progress(result)
        self._save_page(result)
        ready = ready_to_submit(season, result)
        if ready:
            logger.info('[岛屿-赛季任务] 可以提交: ' +
                        '、'.join(f'{t}（{cn_name(i)} {h}/{n}）' for t, i, h, n in ready))
        notify_ready_from_page(self.config, season, result)
        if self.config.IslandSeasonPlan_Submit and ready:
            self._submit_ready(ready, result)

    def _submit_ready(self, ready, result):
        """
        自动提交已达标的任务（开关默认关闭）。

        只对页面上读到的、进度已满且未领取的卡片动手；任何一步没成功就停下，
        本轮不再继续点，避免误点。提交成功与否由下一轮页面读取确认。
        """
        for task, item, have, need in ready:
            info = result.get(task) or {}
            if not self._submit_card(task, info):
                logger.warning(f'[岛屿-赛季任务] {task} 自动提交未成功，本轮停止提交')
                return

    def _submit_card(self, task, info):
        """
        点掉一张已达标卡片的「提交」按钮，并处理确认弹窗。

        Args:
            task: 任务名
            info: 页面读取结果里的卡片信息（含 row/col/offset）

        Returns:
            bool: 是否完成了点击流程
        """
        from module.handler.assets import POPUP_CONFIRM
        from module.island.island_season_plan_reader import claim_box

        row, col, offset = info.get('row'), info.get('col'), int(info.get('offset') or 0)
        if row is None or col is None:
            # 卡片位置未知（本轮由其它屏读到），下轮再试
            logger.info(f'[岛屿-赛季任务] {task} 缺少卡片位置，跳过本次提交')
            return False

        box = claim_box(row, col)
        x = (box[0] + box[2]) // 2
        y = (box[1] + box[3]) // 2 + offset
        logger.info(f'[岛屿-赛季任务] 提交 {task}：点击 ({x}, {y})')
        self.device.click_minitouch(x, y)
        self.device.sleep(1)

        clicked_popup = False
        for _ in self.loop(timeout=8):
            if self.appear_then_click(POPUP_CONFIRM, interval=1):
                clicked_popup = True
                continue
            break
        logger.info(f'[岛屿-赛季任务] {task} 提交点击完成'
                    f'{"（含确认弹窗）" if clicked_popup else "（未出现确认弹窗）"}')
        return True
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

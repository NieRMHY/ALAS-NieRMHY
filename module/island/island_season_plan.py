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
from module.island.island_plan_refresh import PAGE_FILE, request_refresh_on_gap_change
from module.island.island_season import SeasonConfig
from module.island.island_season_plan_data import cn_name
from module.island.island_season_plan_reader import read_season_plan_page
from module.island.island import Island
from module.island.island_state import state_file
from module.logger import logger


class IslandSeasonPlan(Island):
    """赛季任务：读取开发计划页面并同步已完成状态。"""

    # 收餐会触发本任务；限流避免每家店铺跑完都真读一遍页面
    MIN_INTERVAL_MINUTE = 20
    DELAY_MINUTE = 30
    LAST_RUN_FILE = state_file('island_season_plan_last.json')

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

        # Add by MHY, 提交在读取过程中就地完成：卡片就在那一屏时坐标才准。
        # 旧实现是读完退出页面后再回头点，点击全部落在岛屿主页上（10-01 的 111 次、
        # 10-02 的 41 次零效果）；改成读完再重新进页面扫描也不稳，两次扫描撞上的
        # 屏不同，卡片可能恰好停在被屏幕下沿裁掉的位置而读不出状态。
        # Add by MHY, 自动提交暂时停用（储备）。提交点击依赖赛季页的实时定位，
        # 链路长且脆弱（前后返工三次）；改成「按任务需求 +20 生产」之后，物品攒够
        # 就能在游戏里直接领，不再需要机器人代点。「可以提交」的邮件提醒仍然保留，
        # 它现在是唯一的提示手段。
        # 恢复时把下面两行的注释放开即可，_submit_on_screen 一整套逻辑都还在。
        self._submitted = set()
        # result = read_season_plan_page(self, season, on_cards=self._submit_on_screen)
        result = read_season_plan_page(self, season)
        if not result:
            logger.warning('[岛屿-赛季任务] 未读到赛季任务，跳过')
            return
        # 刚就地交掉的卡片，页面上马上会变成已领取；先按已领取算，
        # 免得同一轮刚交完又发一封「可以提交」
        for task in self._submitted:
            if task in result:
                result[task]['claimed'] = True

        self._log_progress(result)
        self._save_page(result)
        # Add by MHY, 赛季缺口变化时自动请求刷新生产/上架方案：货架方案是一次性
        # 快照，物品攒够或任务交掉之后不会自己回到货架，靠手勾容易忘。
        # 判据与「攒够不触发」的理由见 request_refresh_on_gap_change。
        try:
            if request_refresh_on_gap_change(self.config, season):
                logger.info('[岛屿-赛季任务] 赛季缺口变化，已请求刷新生产/上架方案')
        except Exception:
            logger.exception('[岛屿-赛季任务] 自动请求方案刷新失败')
        ready = ready_to_submit(season, result)
        if ready:
            logger.info('[岛屿-赛季任务] 可以提交: ' +
                        '、'.join(f'{t}（{cn_name(i)} {h}/{n}）' for t, i, h, n in ready))
        notify_ready_from_page(self.config, season, result)
        if self.config.IslandSeasonPlan_SyncDone:
            # 用页面上的「已领取」同步已完成状态（之前这段被误插到 _submit_card
            # 的 return 之后，成了死代码，F821 报 season/result 未定义才发现）
            self._sync_done(season, result)


    def _submit_on_screen(self, cards):
        """
        读取过程中就地提交达标的卡片（开关默认关闭）。

        当前停用，作为储备保留（见 _run 里的说明）。

        Add by MHY, 必须就地提交：卡片此刻就在这一屏，坐标是现场读到的，可以直接点。
        旧实现是读完退出页面后再按记录坐标点，点击全部落在岛屿主页上（真机 10-01 的
        111 次、10-02 的 41 次零效果，营养组合停在 100/100 九个小时没领到）；改成
        「读完再重新进页面扫描」也不稳——两次扫描撞上的屏不同，卡片可能恰好停在被
        屏幕下沿裁掉的位置，读不出状态就没法点。

        Args:
            cards: 本屏 read_cards 的结果
        """
        if not self.config.IslandSeasonPlan_Submit:
            return
        for card in cards:
            task = card.get('task')
            if not task or task in self._submitted:
                continue
            if card.get('claimed') is not False:
                # None 是徽章被屏幕下沿裁掉，状态未知；True 是已领取，都不动手
                continue
            need = int(card.get('need') or 0)
            if not need or int(card.get('have') or 0) < need:
                continue
            self._submitted.add(task)
            if not self._submit_card(task, card):
                logger.warning(f'[岛屿-赛季任务] {task} 缺少卡片位置，本轮不再提交')
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

    def _save_page(self, result):
        """页面结果落盘，便于事后排查（config/island/ 下）。"""
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
            # Add by MHY, claimed 为 None 表示徽章被裁掉、状态未知
            if info.get('claimed') is True:
                flag = '已领取'
            elif info.get('claimed') is None:
                flag = f"{info['have']}/{info['need']}？"
            else:
                flag = f"{info['have']}/{info['need']}"
            # 订单里程碑没有对应物品，不留空括号
            item_cn = cn_name(info['item'])
            logger.info(f"[岛屿-赛季任务] {task}: {flag}" + (f"（{item_cn}）" if item_cn else ""))
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

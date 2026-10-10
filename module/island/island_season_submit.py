"""赛季页就地提交（储备，当前未接入任何任务）（Add by MHY）。

自动提交依赖赛季页读取，而页面读取已停用（进度改取仓库读数，见 island_season_progress）。
提交点击的坐标逻辑与踩坑记录保留在这里：恢复时让 IslandSeasonPlan 继承 Island，
并把 read_season_plan_page(self, season, on_cards=self._submit_on_screen) 接回去。

Add by MHY, 必须就地提交：卡片此刻就在这一屏，坐标是现场读到的，可以直接点；
读完退出页面再回头点会落在岛屿主页上（真机 10-01 的 111 次点击零效果）。
"""
from module.logger import logger


class SeasonSubmitMixin:
    """就地提交混入类：宿主需提供 config / device / loop / appear_then_click。"""

    def _submit_on_screen(self, cards):
        """
        读取过程中就地提交达标的卡片（开关默认关闭）。

        Add by MHY, 必须就地提交：卡片此刻就在这一屏，坐标是现场读到的，可以直接点。
        旧实现是读完退出页面后再按记录坐标点，点击全部落在岛屿主页上（真机 10-01 的
        111 次、10-02 的 41 次零效果，营养组合停在 100/100 九个小时没领到）；改成
        「读完再重新进页面扫描」也不稳——两次扫描撞上的屏不同，卡片可能恰好停在被
        屏幕下沿裁掉的位置，读不出状态就没法点。

        Args:
            cards: 本屏 read_cards 的结果
        """
        # 恢复时宿主需自行提供开关（IslandSeasonPlan_Submit 已随进度改版从配置里移除）
        if not getattr(self, 'submit_enabled', False):
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

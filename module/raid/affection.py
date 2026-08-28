"""共斗刷好感处理器，在突袭活动中通过沉船快速积累舰船好感度。

与连战刷好感（coalition_scuttle）同构：牺牲一侧舰船让战斗快速以 D 评价结束，
好感按出击次数 +1/16 累加且与胜负无关，共斗无门票、D 评价不扣心情，
是消耗最低的刷好感场景。支持刷前排好感（牺牲旗舰位）与刷后排好感（牺牲前排）。
"""

from module.exception import ScriptEnd, ScriptError
from module.logger import logger
from module.notify import handle_notify
from module.raid.scuttle import RaidScuttleRun

# 每次出击好感增量：1/16，MVP 双倍不计（刷好感不追求 MVP）
AFFECTION_PER_SORTIE = 0.0625
# 出击时心情低于该值不累计好感，与连战刷好感保持一致
AFFECTION_EMOTION_MIN = 40
# 真胜利判定的石油扣减阈值：困难图胜利扣 25 油，D 评价仅扣水面船数（<=6），中间无重叠
OIL_WIN_THRESHOLD = 10


class RaidAffectionRun(RaidScuttleRun):
    """共斗刷好感主循环，牺牲一侧舰船速刷 D 评价，为目标侧累计好感。"""

    # Add by MHY, 上场评价为正常结算待石油校验，及上场前石油值
    _pending_normal_end = False
    _oil_prev = None

    @property
    def _target_vanguard(self):
        """当前是否以刷前排好感为目标（牺牲旗舰位）。"""
        return self.config.RaidAffection_Target == 'vanguard'

    @property
    def change_vanguard(self):
        # Modify by MHY, 刷后排好感时牺牲前排，换船只换前排白船
        return not self._target_vanguard

    @property
    def change_flagship(self):
        # Modify by MHY, 刷前排好感时牺牲旗舰位，换船只换旗舰白船
        return self._target_vanguard

    def _affection_add(self):
        """战斗结束后为目标侧累计好感。

        心情按编队 1 追踪，出击时心情低于 40 不计；计数写回配置自动
        持久化，双计数器随目标切换各自保留。
        """
        fleet = self.emotion.fleets[0]
        if fleet.value + self.emotion.reduce_per_battle < AFFECTION_EMOTION_MIN:
            logger.info(f'[共斗好感] 出击时心情不足{AFFECTION_EMOTION_MIN}，不计好感')
            return
        key = 'VanguardAffection' if self._target_vanguard else 'MainAffection'
        current = float(getattr(self.config, f'RaidAffection_{key}') or 0)
        new = min(round(current + AFFECTION_PER_SORTIE, 4), 100.0)
        setattr(self.config, f'RaidAffection_{key}', new)
        logger.attr(f'共斗好感-{"前排" if self._target_vanguard else "后排"}', f'{new:.4f}/100')

    def check_affection_stop(self):
        """目标侧好感达到 100 时禁用任务并发通知。"""
        key = 'VanguardAffection' if self._target_vanguard else 'MainAffection'
        current = float(getattr(self.config, f'RaidAffection_{key}') or 0)
        if current >= 100:
            logger.hr('共斗好感已满，停止刷好感任务')
            logger.info(
                f'前排好感: {float(self.config.RaidAffection_VanguardAffection or 0):.2f}，'
                f'后排好感: {float(self.config.RaidAffection_MainAffection or 0):.2f}')
            self.config.Scheduler_Enable = False
            handle_notify(
                self.config.Error_OnePushConfig,
                title='共斗好感已满，任务暂停',
                content=f'<{self.config.config_name}> 前排好感: '
                        f'{float(self.config.RaidAffection_VanguardAffection or 0):.2f}，'
                        f'后排好感: {float(self.config.RaidAffection_MainAffection or 0):.2f}，'
                        f'共斗刷好感已暂停',
            )
            self.config.task_stop()

    def run(self, name='', mode='', total=0):
        """
        运行共斗刷好感主循环。

        每场战斗（无论胜负）结束后累计一次好感；意外胜利时沿用
        RaidScuttle 的换白船自愈逻辑；好感满 100 或触发停止条件后退出。

        Args:
            name (str): 突袭活动名称，为空时从配置读取。
            mode (str): 突袭难度，为空时从配置读取。
            total (int): 总运行次数上限，0 表示不限。
        """
        name = name if name else self.config.Campaign_Event
        mode = mode if mode else self.config.Raid_Mode
        if not name or not mode:
            raise ScriptError(f'RaidAffection arguments unfilled. name={name}, mode={mode}')

        # Add by MHY, 共斗仅一个舰队出击，情绪只追踪编队1（record/show/检查的 zip 均按 fleets 截断）
        if not self.emotion.using_public:
            self.emotion.fleets = [self.emotion.fleet_1]

        self.run_count = 0
        self.run_limit = self.config.StopCondition_RunCount
        while 1:
            if total and self.run_count == total:
                break
            if self.event_time_limit_triggered():
                self.config.task_stop()
            # Add by MHY, 好感满 100 暂停任务
            self.check_affection_stop()

            logger.hr(f'{name}_{mode}', level=2)
            if self.config.StopCondition_RunCount > 0:
                logger.info(f'剩余次数: {self.config.StopCondition_RunCount}')
            else:
                logger.info(f'计数: {self.run_count}')

            if not self._raid_has_oil_icon:
                from module.ui.page import page_campaign_menu
                self.ui_ensure(page_campaign_menu)
                oil = self.get_oil()
                # Add by MHY, 石油校验：评价识别可能误判（如 D 误识别为 C），石油扣减不会骗人
                if self._pending_normal_end:
                    self._pending_normal_end = False
                    if self._oil_prev is not None and self._oil_prev - oil >= OIL_WIN_THRESHOLD:
                        logger.info(
                            f'[共斗好感] 石油校验: 上场为真胜利 '
                            f'(扣油 {self._oil_prev - oil} >= {OIL_WIN_THRESHOLD})，换新白船')
                        self._sacrifice_refresh(mode=mode, raid=name)
                    else:
                        oil_drop = self._oil_prev - oil if self._oil_prev is not None else '未知'
                        logger.info(f'[共斗好感] 石油校验: 上场评价误识别 (扣油 {oil_drop})，不换船继续')
                self._oil_prev = oil
                if self.triggered_stop_condition(oil_check=True, coin_check=True):
                    break

            self.device.stuck_record_clear()
            self.device.click_record_clear()
            if not self.is_raid_rpg():
                from module.ui.page import page_raid
                self.ui_ensure(page_raid)
            else:
                from module.ui.page import page_rpg_stage
                self.ui_ensure(page_rpg_stage)
                self.raid_rpg_swipe()
            self.disable_event_on_raid()

            if mode == 'ex' and not self.is_raid_rpg():
                if not self.get_remain(mode):
                    logger.info('[共斗好感] 触发停止条件: EX模式突袭门票为零')
                    if self.config.task.command == 'RaidAffection':
                        with self.config.multi_set():
                            self.config.StopCondition_RunCount = 0
                            self.config.Scheduler_Enable = False
                    break

            self.device.stuck_record_clear()
            self.device.click_record_clear()
            try:
                self.raid_execute_once(mode=mode, raid=name)
            except ScriptEnd as e:
                logger.hr('脚本结束')
                logger.info(str(e))
                break

            self.run_count += 1
            if self.config.StopCondition_RunCount:
                self.config.StopCondition_RunCount -= 1

            # Add by MHY, 无论胜负，出击即累计好感
            self._affection_add()

            # 评价为正常结算时暂存，待下场读油校验真伪后再决定是否换白船
            # Modify by MHY, C 评价可能为 D 误识别，石油扣减才是胜负铁证
            if self.triggered_normal_end:
                self.triggered_normal_end = False
                self._pending_normal_end = True

            if self.triggered_stop_condition():
                break
            if self.config.task_switched():
                self.config.task_stop()

    def _sacrifice_refresh(self, mode, raid):
        """真胜利后重进编队换新白船，无可用白船时延迟 30 分钟。

        Args:
            mode (str): 难度模式。
            raid (str): 突袭活动名称。
        """
        self.raid_enter_preparation(mode=mode, raid=raid, skip_first_screenshot=False)
        success = True
        if self.change_vanguard:
            success = self.vanguard_change()
        if self.change_flagship:
            success = success and self.flagship_change()

        self.enter_map_cancel(skip_first_screenshot=False)

        if self.config.task_switched():
            self.campaign.ensure_auto_search_exit()
            self.config.task_stop()
        elif not success:
            self.campaign.ensure_auto_search_exit()
            self.config.task_delay(minute=30)
            self.config.task_stop()

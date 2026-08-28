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


class RaidAffectionRun(RaidScuttleRun):
    """共斗刷好感主循环，牺牲一侧舰船速刷 D 评价，为目标侧累计好感。"""

    @property
    def _target_vanguard(self):
        """当前是否以刷前排好感为目标（牺牲旗舰位）。"""
        return self.config.RaidAffection_Target == 'vanguard'

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

        # 刷前排好感时牺牲旗舰位，刷后排好感时牺牲前排，由 Sacrifice 覆盖换船逻辑
        if self._target_vanguard:
            self.config.override(RaidScuttle_Sacrifice='flagship')
        else:
            self.config.override(RaidScuttle_Sacrifice='vanguard')

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

            # 意外胜利后换新白船（复用 RaidScuttle 自愈逻辑）
            if self.triggered_normal_end:
                self.raid_enter_preparation(mode=mode, raid=name, skip_first_screenshot=False)
                success = True
                if self.change_vanguard:
                    success = self.vanguard_change()
                if self.change_flagship:
                    success = success and self.flagship_change()

                self.enter_map_cancel(skip_first_screenshot=False)
                self.triggered_normal_end = False

                if self.config.task_switched():
                    self.campaign.ensure_auto_search_exit()
                    self.config.task_stop()
                elif not success:
                    self.campaign.ensure_auto_search_exit()
                    self.config.task_delay(minute=30)
                    self.config.task_stop()

            if self.triggered_stop_condition():
                break
            if self.config.task_switched():
                self.config.task_stop()

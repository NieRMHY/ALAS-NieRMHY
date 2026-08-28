"""共斗刷好感处理器，在突袭活动中通过沉船快速积累舰船好感度。

与连战刷好感（coalition_scuttle）同构：牺牲一侧舰船让战斗快速以 D 评价结束，
好感按出击次数 +1/16 累加且与胜负无关，共斗无门票、D 评价不扣心情，
是消耗最低的刷好感场景。支持刷前排好感（牺牲旗舰位）与刷后排好感（牺牲前排）。

共斗编队按难度独立保存，因此支持双线刷法：一队用普通难度、二队用困难难度
（或其他组合），两条线各绑一组心情追踪，心情不足的线自动跳过另一线继续。
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
    # 上场出击的线标签（如 hard/normal），用于真胜利通知与日志
    _last_line_label = ''

    def _lines(self):
        """返回启用的刷取线列表，每条线为 (难度, 目标键, 舰队编号, 标签)。

        一队绑定 Raid.Mode 与 RaidAffection.Target，心情追踪舰队 1；
        二队由 Fleet2Enable 启用，绑定 Fleet2Mode/Fleet2Target，心情追踪舰队 2。
        """
        lines = [
            (self.config.Raid_Mode, self.config.RaidAffection_Target, 1, self.config.Raid_Mode),
        ]
        if self.config.RaidAffection_Fleet2Enable:
            lines.append((
                self.config.RaidAffection_Fleet2Mode,
                self.config.RaidAffection_Fleet2Target,
                2,
                f'{self.config.RaidAffection_Fleet2Mode}二队',
            ))
        return lines

    def _line_emotion_ready(self, fleet_index):
        """预检线的心情是否可支撑一场出击（出击后仍不低于控制阈值与好感门槛）。

        不做等待与延迟，仅用于双线间的切换决策。
        """
        fleet = self.emotion.fleets[fleet_index - 1]
        threshold = max(AFFECTION_EMOTION_MIN, fleet.limit) + self.emotion.reduce_per_battle
        return fleet.value + self.emotion.reduce_per_battle >= threshold

    def _line_recovered(self, fleet_index):
        """计算线的心情恢复到可出击阈值的时间。"""
        fleet = self.emotion.fleets[fleet_index - 1]
        threshold = max(AFFECTION_EMOTION_MIN, fleet.limit) + self.emotion.reduce_per_battle
        return fleet.get_recovered(threshold - fleet.limit)

    def _affection_add(self, fleet_index, target):
        """战斗结束后为线的目标侧累计好感。

        出击时心情低于 40 不计；计数写回配置自动持久化，
        双计数器随目标切换各自保留。
        """
        fleet = self.emotion.fleets[fleet_index - 1]
        if fleet.value + self.emotion.reduce_per_battle < AFFECTION_EMOTION_MIN:
            logger.info(f'[共斗好感] 出击时心情不足{AFFECTION_EMOTION_MIN}，不计好感')
            return
        key = 'VanguardAffection' if target == 'vanguard' else 'MainAffection'
        current = float(getattr(self.config, f'RaidAffection_{key}') or 0)
        new = min(round(current + AFFECTION_PER_SORTIE, 4), 100.0)
        setattr(self.config, f'RaidAffection_{key}', new)
        logger.attr(f'共斗好感-{"前排" if target == "vanguard" else "后排"}', f'{new:.4f}/100')

    def check_affection_stop(self):
        """启用的线中任一目标侧好感达到 100 时禁用任务并发通知。"""
        targets = {target for _, target, _, _ in self._lines()}
        for target in targets:
            key = 'VanguardAffection' if target == 'vanguard' else 'MainAffection'
            if float(getattr(self.config, f'RaidAffection_{key}') or 0) >= 100:
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
        运行共斗刷好感主循环，心情驱动地在启用线之间切换。

        每条线使用独立难度与目标侧，心情不足的线自动跳过；
        所有线均不足时延迟任务到最早的恢复时间。战斗无论胜负
        均累计一次好感，真胜利仅发通知提醒。

        Args:
            name (str): 突袭活动名称，为空时从配置读取。
            mode (str): 忽略，由线的难度决定。
            total (int): 总运行次数上限，0 表示不限。
        """
        name = name if name else self.config.Campaign_Event
        if not name:
            raise ScriptError(f'RaidAffection arguments unfilled. name={name}')

        lines = self._lines()
        # 轮转游标：优先当前线的下一条，实现双线交替
        cursor = 0

        self.run_count = 0
        self.run_limit = self.config.StopCondition_RunCount
        while 1:
            if total and self.run_count == total:
                break
            if self.event_time_limit_triggered():
                self.config.task_stop()
            # Add by MHY, 好感满 100 暂停任务
            self.check_affection_stop()

            # 心情驱动选线：从轮转起点扫描一周，取第一条心情可用的线
            picked = None
            for offset in range(len(lines)):
                index = (cursor + offset) % len(lines)
                mode, target, fleet_index, label = lines[index]
                if self._line_emotion_ready(fleet_index):
                    picked = (index, mode, target, fleet_index, label)
                    break
                logger.info(f'[共斗好感] 线 {label} 心情不足，跳过')

            if picked is None:
                recovered = min(self._line_recovered(f) for _, _, f, _ in lines)
                logger.info(f'[共斗好感] 所有线心情不足，延迟任务到 {recovered}')
                self.config.task_delay(target=recovered)
                break

            cursor, mode, target, fleet_index, label = picked
            logger.hr(f'{name}_{label}', level=2)
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
                        oil_drop = self._oil_prev - oil
                        logger.info(f'[共斗好感] 石油校验: 上场为真胜利 (扣油 {oil_drop})，发通知提醒')
                        # Modify by MHY, 真胜利不换船，仅通知（牺牲侧阵容由用户自行管理）
                        handle_notify(
                            self.config.Error_OnePushConfig,
                            title='共斗刷好感意外胜利',
                            content=f'<{self.config.config_name}> 线 {self._last_line_label} '
                                    f'真胜利 (扣油 {oil_drop})，请检查牺牲侧白船阵容',
                        )
                    else:
                        oil_drop = self._oil_prev - oil if self._oil_prev is not None else '未知'
                        logger.info(f'[共斗好感] 石油校验: 上场评价误识别 (扣油 {oil_drop})，继续')
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
                    logger.info(f'[共斗好感] 线 {label} 触发停止条件: EX模式突袭门票为零')
                    if self.config.task.command == 'RaidAffection':
                        with self.config.multi_set():
                            self.config.StopCondition_RunCount = 0
                            self.config.Scheduler_Enable = False
                    break

            self.device.stuck_record_clear()
            self.device.click_record_clear()
            try:
                # 线的心情追踪：舰队1走 fleet1_all_fleet2_standby，舰队2走 standby 变体，
                # 使 emotion.check_reduce 只扣减该线绑定的舰队
                if fleet_index == 1:
                    self.config.override(Fleet_FleetOrder='fleet1_all_fleet2_standby')
                else:
                    self.config.override(Fleet_FleetOrder='fleet1_standby_fleet2_all')
                self.raid_execute_once(mode=mode, raid=name)
            except ScriptEnd as e:
                logger.hr('脚本结束')
                logger.info(str(e))
                break

            self.run_count += 1
            if self.config.StopCondition_RunCount:
                self.config.StopCondition_RunCount -= 1

            # Add by MHY, 无论胜负，出击即累计好感
            self._affection_add(fleet_index, target)
            self._last_line_label = label

            # 评价为正常结算时暂存，待下场读油校验真伪后再决定是否提醒
            if self.triggered_normal_end:
                self.triggered_normal_end = False
                self._pending_normal_end = True

            if self.triggered_stop_condition():
                break
            if self.config.task_switched():
                self.config.task_stop()

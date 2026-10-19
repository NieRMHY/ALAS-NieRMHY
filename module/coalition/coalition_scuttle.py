"""连战刷好感战斗模块（联盟连战玩法），处理编队1/2刷好感、第3编队沉船的结算逻辑。

针对牺牲编队 D 评价沉船场景进行优化，控制心情扣减、好感度累加和战斗结束判定，
并处理沉船专用的结算弹窗与确认操作。"""

from module.coalition.assets import *
from module.coalition.combat import CoalitionCombat
from module.coalition.coalition import Coalition
from module.exception import CampaignEnd, ScriptEnd, ScriptError
from module.logger import logger
from module.notify import handle_notify, notify_title
from module.ui.page import page_coalition


class CoalitionScuttleCombat(CoalitionCombat):
    """连战刷好感战斗结算处理，优先识别沉船专用结算按钮并处理确认弹窗。"""

    # Modify by MHY, 保留连战1/2队刷好感、3队牺牲，结果识别复用公共单场上下文。
    combat_shipwreck_emotion = False
    coalition_result_confirm_buttons = (SCUTTLE_CONFIRM, COALITION_REWARD_CONFIRM)
    triggered_normal_end = False
    _is_sacrifice_fleet = False
    _affection_recorded = False

    def coalition_emotion_reduce(self):
        # Add by MHY, 两个受益编队各扣一场基础心情，牺牲编队不记账。
        return self.battle_count < 2

    def combat_result_record(self, rank=None, defeated=False, fleet_unavailable=False):
        super().combat_result_record(rank=rank, defeated=defeated, fleet_unavailable=fleet_unavailable)
        result = self.combat_result
        self.triggered_normal_end = result.rank in ('S', 'A', 'B') and not result.defeated
        # Add by MHY, 执行和重新入场都会识别结果，同一编队只累计一次好感。
        if self.triggered_normal_end and not self._affection_recorded:
            self._affection_recorded = True
            self._affection_add(result.fleet_index)

    def auto_search_combat_execute(self, emotion_reduce=True, fleet_index=1, battle=None,
                                   expected_end=None, shipwreck_reduce=None):
        self._is_sacrifice_fleet = fleet_index >= 3
        self._affection_recorded = False
        self.triggered_normal_end = False
        # Modify by MHY, 公共入口每场重置结果和模式检查，保留用户配置的皮肤/手操识别。
        return super().auto_search_combat_execute(
            emotion_reduce=emotion_reduce, fleet_index=fleet_index, battle=battle,
            expected_end=expected_end, shipwreck_reduce=False)

    def coalition_combat(self):
        self.battle_count = 0
        self.combat_preparation(emotion_reduce=False)

        try:
            while True:
                logger.hr(f'{self.FUNCTION_NAME_BASE}{self.battle_count}', level=2)
                self.auto_search_combat_execute(
                    emotion_reduce=self.coalition_emotion_reduce() and self.emotion.is_calculate,
                    fleet_index=self.battle_count + 1,
                    expected_end=self.auto_search_combat_end)
                self.coalition_combat_re_enter()
                self.battle_count += 1
        except CampaignEnd:
            logger.info('联动战斗结束。')

    # Modify by MHY, 好感度追踪：编队1/2 胜利且出击时心情≥40 累加 1/16
    def _affection_add(self, fleet_index):
        """胜利时累加编队好感度。

        仅编队1/2参与；出击时心情≥40（正常状态）才累加 1/16。
        好感度写回配置自动持久化，满100由 check_affection_stop 暂停任务。
        """
        if fleet_index not in (1, 2):
            return
        # Modify by MHY, 新心情模型用下限判断好感门槛，公共模式使用共享账本。
        fleet = self.emotion.public_fleet if self.emotion.using_public else self.emotion.fleets[fleet_index - 1]
        # Add by MHY, 无视心情模式保留本地好感追踪，直接用手动配置值且无需恢复校准。
        start_emotion = fleet.lower + self.emotion.reduce_per_battle if self.emotion.is_calculate else fleet.value
        if start_emotion < 40:
            logger.info(f'[好感度] 编队{fleet_index}出击时心情不足40，不计好感')
            return
        key = 'Fleet1Affection' if fleet_index == 1 else 'Fleet2Affection'
        current = float(getattr(self.config, f'CoalitionScuttle_{key}') or 0)
        new = min(round(current + 0.0625, 4), 100.0)
        setattr(self.config, f'CoalitionScuttle_{key}', new)
        logger.attr(f'好感度-编队{fleet_index}', f'{new:.2f}/100')


class CoalitionScuttleRun(Coalition, CoalitionScuttleCombat):
    """连战刷好感主循环，编队1/2 各扣2点心情并累加好感度，第3编队沉船不追踪。"""

    def handle_combat_low_emotion(self):
        """
        重写红脸出击警告弹窗处理。

        沉船任务中牺牲船必然低心情，红脸弹窗出现时点击确认继续出击。
        """
        return self.handle_popup_confirm('IGNORE_LOW_EMOTION')

    # Add by MHY, 牺牲编队（第3队）手操流程绝不释放鱼雷/空袭，否则会击沉来撞的敌方
    # 破坏沉船节奏；受益编队（1/2）不受影响，手操时照常释放
    def handle_combat_weapon_release(self):
        if self._is_sacrifice_fleet:
            return False
        return super().handle_combat_weapon_release()

    def coalition_execute_once(self, event, stage, fleet):
        """执行一次连战刷好感战斗。

        覆盖父类方法，心情预估按编队1/2各1场（各扣2点）。
        连战刷好感内部分3个编队依次接敌，前2个编队胜利各扣2点心情，第3编队（牺牲）沉船不追踪。

        Args:
            event: 活动名称。
            stage: 关卡名称。
            fleet: 舰队模式。
        """
        self.config.override(
            Campaign_Name=f'{event}_{stage}',
            Campaign_UseAutoSearch=False,
            # Modify by MHY, fleet1_mob_fleet2_boss 使 check_reduce 按 (battle-1, 1) 预估到编队1/2
            Fleet_FleetOrder='fleet1_mob_fleet2_boss',
        )
        if self.config.Coalition_Fleet == 'single' and self.config.Emotion_Fleet1Control == 'prevent_red_face':
            logger.warning('AL does not allow single coalition with emotion < 30, '
                           'emotion control is forced to prevent_yellow_face')
            self.config.override(Emotion_Fleet1Control='prevent_yellow_face')
        if stage == 'sp':
            self.config.override(Coalition_Fleet='multi')

        # Modify by MHY, 编队1/2各扣1场2点心情，第3编队（牺牲）不预估
        try:
            self.emotion.check_reduce(battle=2)
        except ScriptEnd:
            self.coalition_map_exit(event)
            raise

        if self._coalition_has_oil_icon and self.triggered_stop_condition(oil_check=True, coin_check=True):
            self.coalition_map_exit(event)
            raise ScriptEnd

        self.enter_map(event=event, stage=stage, mode=fleet)
        self.coalition_combat()

    def triggered_stop_condition(self, oil_check=False, pt_check=False, coin_check=False):
        """
        检查是否触发了停止条件。

        连战刷好感不因 triggered_normal_end（舰船被击沉）而停止任务，
        由 RunCount 控制何时停止。D评价和非D评价都算1次有效战斗。

        Returns:
            bool: 是否触发了停止条件。
        """
        if super().triggered_stop_condition(oil_check=oil_check, pt_check=pt_check, coin_check=coin_check):
            return True

        return False

    # Add by MHY, 好感度满100暂停任务
    def check_affection_stop(self):
        """任一编队好感度达到100时禁用任务并发通知（TaskEnd 由调度器捕获）。"""
        a1 = float(self.config.CoalitionScuttle_Fleet1Affection or 0)
        a2 = float(self.config.CoalitionScuttle_Fleet2Affection or 0)
        if a1 >= 100 or a2 >= 100:
            logger.hr('好感度已满，停止连战刷好感任务')
            logger.info(f'编队1好感: {a1:.2f}，编队2好感: {a2:.2f}')
            # 禁用调度器，避免任务被立即重新调度形成刷屏循环
            self.config.Scheduler_Enable = False
            # 通知渠道由 Error_OnePushConfig 配置（配 smtp 即发邮件）
            handle_notify(
                self.config.Error_OnePushConfig,
                title=notify_title(self.config.config_name, '好感', '已满，连战暂停'),
                content=f'<{self.config.config_name}> 编队1好感: {a1:.2f}，'
                        f'编队2好感: {a2:.2f}，连战刷好感已暂停',
            )
            self.config.task_stop()

    def run(self, event='', mode='', fleet='', total=0):
        """
        运行连战刷好感主循环，编队1/2 扣减心情并累加好感度，满100暂停。

        SP关卡特殊逻辑：
        - 只有明确 S 评价且没有战败画面才视为通过
        - 其他结果按次数限制继续出击

        Args:
            event (str): 活动名称，为空时从配置读取。
            mode (str): 关卡名称，为空时从配置读取。
            fleet (str): 舰队模式，为空时从配置读取。
            total (int): 总运行次数上限，0 表示不限。
        """
        event = event if event else self.config.Campaign_Event
        mode = mode if mode else self.config.Coalition_Mode
        fleet = fleet if fleet else self.config.Coalition_Fleet
        if not event or not mode or not fleet:
            raise ScriptError(f'CoalitionScuttle arguments unfilled. name={event}, mode={mode}, fleet={fleet}')

        event, mode = self.handle_stage_name(event, mode)
        self.run_count = 0
        self.run_limit = self.config.StopCondition_RunCount

        while 1:
            # 达到指定运行次数则结束
            if total and self.run_count == total:
                break
            if self.event_time_limit_triggered():
                self.config.task_stop()
            # Add by MHY, 好感度满100暂停任务
            self.check_affection_stop()

            # 日志输出
            logger.hr(f'{event}_{mode}', level=2)
            if self.config.StopCondition_RunCount > 0:
                logger.info(f'剩余次数: {self.config.StopCondition_RunCount}')
            else:
                logger.info(f'计数: {self.run_count}')

            # 无燃油图标时，先在战役菜单检查停止条件
            if not self._coalition_has_oil_icon:
                from module.ui.page import page_campaign_menu
                self.ui_goto(page_campaign_menu)
                if self.triggered_stop_condition(oil_check=True, coin_check=True):
                    break

            # 确保进入联盟页面
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            self.ui_goto_coalition()
            self.disable_event_on_raid()
            self.coalition_ensure_mode(event, 'battle')

            # 检查 PT 和金币停止条件
            if self.triggered_stop_condition(pt_check=True, coin_check=True):
                break

            # 执行战斗
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            try:
                self.coalition_execute_once(event=event, stage=mode, fleet=fleet)
            except ScriptEnd as e:
                logger.hr('脚本结束')
                logger.info(str(e))
                break

            # 战斗结束后更新计数
            self.run_count += 1
            if self.config.StopCondition_RunCount:
                self.config.StopCondition_RunCount -= 1

            # SP关卡仅S评价视为已通过，延迟至服务器刷新
            # A/B/C/D评价均视为未通过，继续出击
            if mode == 'sp' and self.combat_result.rank == 'S' and not self.combat_result.defeated:
                logger.info('SP以S评价通过')
                self.config.task_delay(server_update=True)
                self.config.task_stop()

            # 检查停止条件
            if self.triggered_stop_condition(pt_check=True, coin_check=True):
                break
            # 检查调度器是否切换了任务
            if self.config.task_switched():
                self.config.task_stop()

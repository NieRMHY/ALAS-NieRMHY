"""连战刷好感战斗模块（联盟连战玩法），处理编队1/2刷好感、第3编队沉船的结算逻辑。

针对牺牲编队 D 评价沉船场景进行优化，控制心情扣减、好感度累加和战斗结束判定，
并处理沉船专用的结算弹窗与确认操作。"""

from module.combat.assets import (
    BATTLE_STATUS_D, BATTLE_STATUS_A, BATTLE_STATUS_B, BATTLE_STATUS_S,
    COMBAT_AUTO_SWITCH,
    OPTS_INFO_D,
    EXP_INFO_D, EXP_INFO_A, EXP_INFO_B, EXP_INFO_S
)
from module.coalition.assets import *
from module.coalition.combat import CoalitionCombat
from module.coalition.coalition import Coalition
from module.exception import ScriptEnd, ScriptError
from module.logger import logger
from module.notify import handle_notify
from module.ui.page import page_coalition


class CoalitionScuttleCombat(CoalitionCombat):
    """连战刷好感战斗结算处理，优先识别沉船专用结算按钮并处理确认弹窗。"""

    triggered_normal_end = False
    _is_shipwreck = False  # 当前战斗是否为沉船D评价
    _is_s_rank = False  # 当前战斗是否为S评价
    # Add by MHY, 当前编队是否为牺牲编队（第3队），手操流程禁武器释放
    _is_sacrifice_fleet = False

    def auto_search_combat_execute(self, emotion_reduce=True, fleet_index=1, expected_end=None):
        """
        重写自动搜索战斗执行，连战刷好感编队1/2胜利各扣2心情，第3编队（牺牲）沉船不扣。

        连战刷好感3个编队依次接敌，前2个编队胜利扣减2心情并累加好感度，
        第3编队（牺牲）沉船不追踪心情。胜利结算时由 _affection_add 累加好感度。

        Args:
            emotion_reduce (bool): 是否扣减心情（第3编队牺牲时为False）。
            fleet_index (int): 编队编号，1/2为刷好感编队，3为牺牲编队。
            expected_end (callable): 自定义结束条件。
        """
        from module.base.timer import Timer
        from module.combat.assets import OPTS_INFO_D
        from module.combat.auto_search_combat import AutoSearchCombat
        from module.exception import CampaignEnd

        self.device.stuck_record_clear()
        self.device.click_record_clear()

        # 编队1/2胜利各扣2心情，第3编队（牺牲）沉船不扣心情
        if emotion_reduce:
            self.emotion.reduce(fleet_index)

        # fleet_index>=2（含牺牲编队）统一使用 Fleet2 战斗模式
        auto = self.config.Fleet_Fleet1Mode if fleet_index == 1 else self.config.Fleet_Fleet2Mode
        # Modify by MHY, 第3编队（牺牲）切手操：模式由用户配置，站桩或藏左上；
        # 编队1/2（受益）保持用户战斗配置（可自律）
        self._is_sacrifice_fleet = fleet_index >= 3
        if self._is_sacrifice_fleet:
            auto = self.config.CoalitionScuttle_SacrificeMode
            logger.info(f'[连战好感] 第{fleet_index}编队（牺牲）战斗模式: {auto}')
        confirm_timer = Timer(10)
        confirm_timer.start()

        while 1:
            self.device.screenshot()

            if self.handle_submarine_call('do_not_use', call=False):
                continue
            if self.handle_combat_auto(auto):
                continue
            if self.handle_combat_manual(auto):
                continue
            if self.handle_popup_confirm('AUTO_SEARCH_COMBAT_EXECUTE'):
                continue
            if not self._withdraw and self.handle_urgent_commission():
                continue
            if self.handle_story_skip():
                continue
            if self.handle_guild_popup_cancel():
                continue
            if self.handle_vote_popup():
                continue
            if self.handle_mission_popup_ack():
                continue

            # 结束条件
            if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
                self.device.screenshot_interval_set()
                raise CampaignEnd
            if self.is_combat_executing():
                confirm_timer.reset()
                continue
            if self.handle_get_ship():
                continue

            # D评价沉船：第3编队（牺牲）不追踪心情
            if self.appear_then_click(OPTS_INFO_D, offset=(30, 30), interval=2):
                self._withdraw = True
                self._is_shipwreck = True
                break
            # D评价结算界面：S/A/B/C评价的动画过渡帧可能短暂误匹配D评价模板，
            # 但只有真正的沉船才会出现OPTS_INFO_D弹窗。
            # 此处不设置沉船标记（未经过OPTS_INFO_D确认），让后续S/A/B/C条件覆盖。
            if self.appear(BATTLE_STATUS_D) or self.appear(EXP_INFO_D):
                break
            if confirm_timer.reached():
                self._withdraw = True
                self._is_shipwreck = True
                self.device.click(OPTS_INFO_D)
                confirm_timer.reset()
                break

            # A/B评价：胜利，编队1/2 累加好感度（牺牲编队不参与）
            if self.appear(BATTLE_STATUS_A) or self.appear(BATTLE_STATUS_B) \
                    or self.appear(EXP_INFO_A) or self.appear(EXP_INFO_B):
                self._affection_add(fleet_index)
                break

            # C评价：胜利但不额外扣减心情，也不累加好感度
            if self.appear(BATTLE_STATUS_C) or self.appear(EXP_INFO_C):
                break

            # S评价或自动搜索运行中
            if self.appear(BATTLE_STATUS_S) or self.appear(EXP_INFO_S) \
                    or self.is_auto_search_running():
                self._is_s_rank = True
                self._affection_add(fleet_index)
                self.device.screenshot_interval_set()
                break

            if callable(expected_end):
                if expected_end():
                    self.device.screenshot_interval_set()
                    break

    def coalition_combat(self):
        """
        连战刷好感战斗执行，编队1/2胜利各扣2心情，第3编队（牺牲）沉船不扣。

        3个编队依次接敌：编队1/2 各扣减2点心情并累加好感度，
        第3编队（牺牲）沉船不追踪心情。
        """
        from module.exception import CampaignEnd

        self.battle_count = 0
        self.combat_preparation(emotion_reduce=False)

        try:
            while 1:
                logger.hr(f'{self.FUNCTION_NAME_BASE}{self.battle_count}', level=2)
                self._is_shipwreck = False
                self._is_s_rank = False
                # Modify by MHY, 编队1/2依次接敌各扣2心情，第3编队（牺牲）沉船不扣心情
                self.auto_search_combat_execute(
                    emotion_reduce=self.battle_count < 2,
                    fleet_index=self.battle_count + 1,
                    expected_end=self.auto_search_combat_end
                )
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
        fleet = self.emotion.fleets[fleet_index - 1]
        # reduce() 已把扣减后心情写入配置，+reduce_per_battle 重建出击前心情
        if fleet.value + self.emotion.reduce_per_battle < 40:
            logger.info(f'[好感度] 编队{fleet_index}出击时心情不足40，不计好感')
            return
        key = 'Fleet1Affection' if fleet_index == 1 else 'Fleet2Affection'
        current = float(getattr(self.config, f'CoalitionScuttle_{key}') or 0)
        new = min(round(current + 0.0625, 4), 100.0)
        setattr(self.config, f'CoalitionScuttle_{key}', new)
        logger.attr(f'好感度-编队{fleet_index}', f'{new:.2f}/100')

    def handle_battle_status(self, drop=None):
        """
        处理连战刷好感的战斗结算画面，优先识别沉船专用结算按钮。

        沉船结算流程：BATTLE_STATUS_D → OPTS_INFO_D → SCUTTLE_CONFIRM → 父类结算。
        识别到标准结算（非D类）时标记 triggered_normal_end 表示舰船被完全击沉。

        Args:
            drop (DropImage): 掉落物图像处理器。

        Returns:
            bool: 是否成功识别并处理了战斗结算。
        """
        if self.is_combat_executing():
            return False
        if self.appear(BATTLE_STATUS_D, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(BATTLE_STATUS_D)
            return True
        if self.appear(OPTS_INFO_D, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(OPTS_INFO_D)
            return True
        # 沉船结算后的确认按钮
        if self.appear_then_click(SCUTTLE_CONFIRM, offset=(20, 20), interval=2):
            return True
        if super().handle_battle_status(drop=drop):
            logger.warning("触发正常结束")
            self.triggered_normal_end = True
            return True

        return False

    def handle_exp_info(self):
        """
        处理连战刷好感的经验结算画面。

        Returns:
            bool: 是否成功识别并处理了经验结算。
        """
        if self.is_combat_executing():
            return False
        if self.appear_then_click(EXP_INFO_D):
            self.device.sleep((0.25, 0.5))
            return True
        if super().handle_exp_info():
            return True

        return False

    def coalition_combat_re_enter(self, skip_first_screenshot=True):
        """
        连战刷好感重新进入战斗，在原有逻辑基础上增加确认按钮处理。

        Pages:
            in: battle_status
            out: is_combat_executing
        """
        from module.base.timer import Timer
        from module.os_ash.assets import BATTLE_STATUS

        logger.info('[联动-扫荡] 联动自沉战斗重新进入')
        status_clicked = False
        click_timer = Timer(0.3)
        click_last = Timer(2)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # End
            if self.is_combat_loading():
                break
            if self.is_combat_executing():
                break
            if self.in_coalition():
                from module.exception import CampaignEnd
                raise CampaignEnd

            if self.appear_then_click(BATTLE_STATUS, offset=(80, 20), interval=2):
                continue
            if self.appear_then_click(COALITION_REWARD_CONFIRM, offset=(20, 20), interval=2):
                status_clicked = False
                continue
            # 沉船结算确认按钮
            if self.appear_then_click(SCUTTLE_CONFIRM, offset=(20, 20), interval=2):
                continue
            if self.handle_get_ship():
                continue
            if self.handle_battle_status():
                status_clicked = True
                click_last.reset()
                continue
            if status_clicked:
                if click_timer.reached() and not click_last.reached():
                    self.device.click(BATTLE_STATUS)
                    click_timer.reset()


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

    # Add by MHY, 牺牲编队一次性手操切换：通用 handle_combat_auto 在点击切换后
    # 依赖摇杆模板翻转确认，截图延迟期会误判来回连点（震荡期舰队自律开火）。
    # 加无摇杆多帧确认：入场演出期按钮未渲染会被误判为自律中而误点开自律。
    # 有摇杆直接确认；无摇杆须战斗执行中且连续3帧才点一次，受益编队走基类
    _manual_no_joystick_frames = 0

    def combat_auto_reset(self):
        super().combat_auto_reset()
        self._manual_no_joystick_frames = 0

    def handle_combat_auto(self, auto):
        if self._is_sacrifice_fleet:
            if self.auto_mode_checked:
                return False
            if self.combat_joystick_appear():
                logger.info('[连战好感] 牺牲编队检测到摇杆，已在手操模式')
                self.auto_mode_checked = True
                return False
            if self.auto_mode_click_timer.reached():
                logger.info('[连战好感] 牺牲编队摇杆未出现，放弃切换保持现状')
                self.auto_mode_checked = True
                return False
            if not self.auto_skip_timer.reached():
                return False
            # 战斗未进入执行态（入场演出/加载中）不做判定，按钮未渲染会误判
            if not self.is_combat_executing():
                return False
            # 连续 3 帧无摇杆才认定真自律，防单帧模板失配误触发
            self._manual_no_joystick_frames += 1
            if self._manual_no_joystick_frames < 3:
                return False
            if not self.auto_click_interval_timer.reached():
                return False
            logger.info(f'[连战好感] 牺牲编队连续{self._manual_no_joystick_frames}帧无摇杆（自律中），点击一次切换到手操')
            # 切换确认期用最短截图间隔，避免下一帧还在旧状态就被判定
            self.device.screenshot_interval_set(0.001)
            self.device.click(COMBAT_AUTO_SWITCH)
            self.auto_click_interval_timer.reset()
            self.auto_mode_checked = True
            self.auto_mode_switched = True
            return True
        return super().handle_combat_auto(auto)

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
                title='好感已满，连战暂停',
                content=f'<{self.config.config_name}> 编队1好感: {a1:.2f}，'
                        f'编队2好感: {a2:.2f}，连战刷好感已暂停',
            )
            self.config.task_stop()

    def run(self, event='', mode='', fleet='', total=0):
        """
        运行连战刷好感主循环，编队1/2 扣减心情并累加好感度，满100暂停。

        SP关卡特殊逻辑：
        - D评价（沉船）：视为未通过，继续出击
        - 非D评价（成功）：视为已通过，延迟至服务器刷新

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
            if mode == 'sp' and self._is_s_rank and not self._is_shipwreck:
                logger.info('SP以S评价通过')
                self.config.task_delay(server_update=True)
                self.config.task_stop()

            # 检查停止条件
            if self.triggered_stop_condition(pt_check=True, coin_check=True):
                break
            # 检查调度器是否切换了任务
            if self.config.task_switched():
                self.config.task_stop()

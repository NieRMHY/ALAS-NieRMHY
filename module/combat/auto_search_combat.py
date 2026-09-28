"""自动搜索战斗管理器。

管理通关模式（快进模式）下的自动搜索战斗流程。

在通关模式下，游戏会自动进行地图探索和战斗。
此模块负责：
- 启动自动搜索（地图中的出击按钮）
- 等待自动搜索完成（检测回到关卡页面）
- 处理战斗期间的异常（退役、低情绪、撤退等）
- 检测停止条件（石油/物资限制、通关次数等）
- Boss 战后的关卡推进

继承自 MapOperation + Combat + CampaignStatus，
组合了地图操作、战斗系统和战役状态追踪的能力。
"""

from module.base.timer import Timer
from module.campaign.campaign_status import CampaignStatus
from module.combat.assets import *
from module.combat.combat import Combat
from module.exception import CampaignEnd, ScriptEnd
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_ON, GET_MISSION
from module.logger import logger
from module.map.assets import WITHDRAW, SWITCH_OVER, FLEET_WITHDRAW, FLEET_SWITCH_CONFIRM, FLEET_WITHDRAW_BOSS
from module.map.map_operation import MapOperation


class AutoSearchCombat(MapOperation, Combat, CampaignStatus):
    """自动搜索战斗执行器。

    在通关模式下编排自动搜索战斗流程，处理各种战斗异常和停止条件。

    Attributes:
        _auto_search_in_stage_timer (Timer): 关卡页面检测计时器。
        _auto_search_status_confirm (bool): 自动搜索状态是否已确认。
        _withdraw (bool): 是否已执行撤退。
        _defeat_count (int): 战败次数。
        _shipwreck_emotion_reduced (bool): 沉船心情扣减是否已执行，防止重复扣减。
        _auto_search_emotion_reduce (bool): 当前战斗是否启用心情扣减。
        _auto_search_fleet_index (int): 当前战斗的舰队索引。
        auto_search_oil_limit_triggered (bool): 石油限制是否已触发。
        auto_search_coin_limit_triggered (bool): 物资限制是否已触发。
    """
    _auto_search_in_stage_timer = Timer(3, count=6)
    _auto_search_status_confirm = False
    _withdraw = False
    _defeat_count = 0
    _shipwreck_emotion_reduced = False
    _auto_search_emotion_reduce = False
    _auto_search_fleet_index = 1
    auto_search_oil_limit_triggered = False
    auto_search_coin_limit_triggered = False

    def _handle_auto_search_menu_missing(self):
        """处理自动搜索菜单缺失的异常情况。

        有时游戏出现异常未显示自动搜索菜单，Boss 战后直接返回关卡页面。
        若停留在关卡页面超过一定时间，则判定自动搜索已结束。

        Returns:
            bool: 是否触发自动搜索结束。
        """
        if self.is_in_stage():
            if self._auto_search_in_stage_timer.reached():
                logger.info('捕获自动搜索菜单缺失')
                return True
        else:
            self._auto_search_in_stage_timer.reset()

        return False

    def map_offensive_auto_search(self, skip_first_screenshot=True):
        """在地图中启动自动搜索。

        Args:
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。

        Pages:
            in: in_map, MAP_OFFENSIVE
            out: is_combat_loading
        """
        self.interval_reset(AUTO_SEARCH_MAP_OPTION_ON)
        for _ in self.loop():

            if self.handle_auto_search_map_option():
                self.interval_reset(AUTO_SEARCH_MAP_OPTION_ON)
                continue
            # 处理碧蓝航线客户端异常：
            # 从退役界面退出并立即开启自动搜索时，图标显示正在运行但实际未动作。
            # 定时点击：每 3 秒尝试关闭自动搜索一次，不包含初始阶段
            if self.appear(AUTO_SEARCH_MAP_OPTION_ON, offset=self._auto_search_offset, interval=3) \
                    and self.appear_then_click(AUTO_SEARCH_MAP_OPTION_ON):
                continue
            if self.handle_combat_low_emotion():
                continue
            if self.handle_retirement():
                continue

            # 结束判断
            if self.is_combat_loading():
                break

    def auto_search_watch_fleet(self, checked=False):
        """监控舰队索引与舰船等级。

        Args:
            checked (bool, optional): 舰队移动期间监控操作仅执行或记录一次。
                设为 True 跳过再次执行。默认为 False。

        Returns:
            bool: 监控操作是否已执行。
        """
        prev = self.fleet_current_index
        self.get_fleet_show_index()
        self.get_fleet_current_index()
        if self.fleet_current_index == prev:
            # 与当前舰队一致，仅输出一次日志
            if not checked:
                logger.info(f'[自动搜索-舰队] 舰队: {self.fleet_show_index}, 当前舰队索引: {self.fleet_current_index}')
                checked = True
                self.lv_get(after_battle=True)
        else:
            # 舰队发生切换
            logger.info(f'[自动搜索-舰队] 舰队: {self.fleet_show_index}, 当前舰队索引: {self.fleet_current_index}')
            checked = True
            self.lv_get(after_battle=False)

        return checked

    def auto_search_watch_oil(self, checked=False):
        """监控当前石油存量并更新石油限制状态。

        Args:
            checked (bool, optional): 是否已执行过检查。默认为 False。

        Returns:
            bool: 检查是否已执行。
        """
        if not checked:
            oil = self.get_oil()
            if oil == 0:
                logger.warning('未找到石油')
            else:
                if oil < max(self.config.StopCondition_OilLimitHardFloor, self.config.StopCondition_OilLimit):
                    logger.info('达到石油上限')
                    self.auto_search_oil_limit_triggered = True
                else:
                    if self.auto_search_oil_limit_triggered:
                        logger.warning('[自动搜索-石油] 石油限制已触发但石油已恢复，'
                                       '可能是因为之前的OCR结果错误')
                    self.auto_search_oil_limit_triggered = False
                checked = True

        return checked

    def auto_search_watch_coin(self, checked=False):
        """监控当前物资存量并更新物资限制状态。

        Args:
            checked (bool, optional): 是否已执行过检查。默认为 False。

        Returns:
            bool: 检查是否已执行。
        """
        if not checked:
            limit = self.config.TaskBalancer_CoinLimit
            coin = self.get_coin()
            if coin == 0:
                logger.warning('未找到物资')
            else:
                if self.is_balancer_task():
                    if coin < limit:
                        logger.info('达到物资上限')
                        self.auto_search_coin_limit_triggered = True
                    else:
                        # 物资充足
                        self.auto_search_coin_limit_triggered = False
                else:
                    if self.auto_search_coin_limit_triggered:
                        logger.warning('[自动搜索-物资] 物资限制已触发但物资已恢复，'
                                       '可能是因为之前的OCR结果错误')
                    self.auto_search_coin_limit_triggered = False
                checked = True

        return checked

    def _wait_until_in_map(self, skip_first_screenshot=True):
        """等待直到回到地图界面。

        处理退役或强化退出后立即开启自动搜索时，
        图标显示运行但游戏无响应的客户端异常。

        Args:
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。

        Pages:
            in: 退出退役或强化界面
            out: in_map()
        """
        timeout = Timer(3, count=6).start()
        for _ in self.loop():

            if self.is_in_map():
                break
            if timeout.reached():
                logger.warning('[自动搜索-地图] 等待退役后进入地图超时，假设已在地图中')
                break

    def auto_search_moving(self, skip_first_screenshot=True):
        """监控自动搜索中的舰队移动状态。

        持续监控舰队移动、更新资源状态，并处理途中遭遇的退役、心情、剧情等弹窗。

        Args:
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。

        Raises:
            CampaignEnd: 检测到自动搜索菜单或菜单丢失时抛出，表示本轮探索结束。

        Pages:
            in: 地图界面
            out: is_combat_loading()
        """
        logger.info('自动搜索移动中')
        self.device.stuck_record_clear()
        checked_fleet = False
        checked_oil = False
        checked_coin = False
        for _ in self.loop():

            if self.is_auto_search_running():
                checked_fleet = self.auto_search_watch_fleet(checked_fleet)
                if not checked_oil or not checked_coin:
                    checked_oil = self.auto_search_watch_oil(checked_oil)
                    checked_coin = self.auto_search_watch_coin(checked_coin)
            if self.handle_retirement():
                self.map_offensive_auto_search()
                # 地图出击在 is_combat_loading 处结束
                break
            if self.handle_auto_search_map_option():
                continue
            if self.handle_combat_low_emotion():
                self._auto_search_status_confirm = True
                continue
            if self.handle_story_skip():
                continue
            if self.handle_map_cat_attack():
                continue
            if self.handle_vote_popup():
                continue

            # 结束判断
            if self.is_combat_loading():
                break
            if self.is_combat_executing():
                logger.info('[自动搜索-战斗] 战斗执行中')
                break
            if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
                raise CampaignEnd

    def auto_search_combat_execute(self, emotion_reduce, fleet_index, battle=None, expected_end=None):
        """执行自动搜索战斗过程。

        包含战斗加载、自律/手动控制、潜艇召唤、弹窗处理及结算判定。

        Args:
            emotion_reduce (bool): 是否扣减心情。
            fleet_index (int): 舰队索引（1 为道中队，2 为 Boss 队）。
            battle (tuple[int, int], optional): 当前战斗场次信息 (当前战斗计数, 总战斗计数)。默认为 None。
            expected_end (callable, optional): 外部传入的战斗结束判定回调函数。默认为 None。

        Raises:
            CampaignEnd: 检测到自动搜索菜单时抛出，表示探索已结束。

        Pages:
            in: is_combat_loading()
            out: 战斗结算状态
        """
        logger.info('自动搜索战斗加载中')
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        self.device.screenshot_interval_set('combat')
        for _ in self.loop():

            if self.handle_combat_automation_confirm():
                continue
            if self.handle_story_skip():
                continue
            if self.handle_vote_popup():
                continue
            # 加载期间出现的红脸（低心情）弹窗同样没有任何其他处理器会认，
            # 不处理会一直等到 GameStuckError。ignore 模式下点「确定」继续出击
            if self.handle_combat_low_emotion():
                continue
            # 过图期间弹出的「船坞已满」弹窗没有任何其他处理器会认，
            # 不处理会一直等到 GameStuckError。处理完退役/强化后重新开启
            # 自动搜索，等待游戏自己再次进入战斗加载
            if self.handle_retirement():
                # 退役流程在地图上进行，先恢复普通截图间隔
                self.device.screenshot_interval_set()
                self.map_offensive_auto_search()
                self.device.screenshot_interval_set('combat')
                continue

            # End
            if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
                raise CampaignEnd
            pause = self.is_combat_executing()
            if pause:
                logger.attr('战斗UI', pause)
                break

        logger.info('[自动搜索-战斗] 战斗执行')
        self.submarine_call_reset()
        submarine_mode = 'do_not_use'
        if self.config.Submarine_Fleet:
            submarine_mode = self.config.Submarine_Mode
        force_call = battle[0] == battle[1] - 1 if battle is not None else False
        self.combat_auto_reset()
        self.combat_manual_reset()
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        if emotion_reduce:
            self.emotion.reduce(fleet_index)
        auto = self.config.Fleet_Fleet1Mode if fleet_index == 1 else self.config.Fleet_Fleet2Mode

        confirm_timer = Timer(10)
        confirm_timer.start()
        while 1:
            self.device.screenshot()

            if self.handle_submarine_call(submarine_mode, call=force_call):
                continue
            if self.handle_combat_auto(auto):
                continue
            if self.handle_combat_manual(auto):
                continue
            if auto != 'combat_auto' and self.auto_mode_checked and self.is_combat_executing():
                if self.handle_combat_weapon_release():
                    continue
            # 处理各种弹窗
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

            # 结束判断
            if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
                self.device.screenshot_interval_set()
                raise CampaignEnd
            if self.is_combat_executing():
                confirm_timer.reset()
                continue
            if self.handle_get_ship():
                continue
            if self.appear_then_click(OPTS_INFO_D, offset=(30, 30), interval=2):
                if emotion_reduce and not self._shipwreck_emotion_reduced:
                    self.emotion.reduce(fleet_index, shipwreck=True)
                    self._shipwreck_emotion_reduced = True
                self._withdraw = True
                break
            # D评价结算界面（BATTLE_STATUS_D / EXP_INFO_D）
            # S/A/B/C评价的动画过渡帧可能短暂误匹配D评价模板，
            # 但只有真正的沉船才会出现OPTS_INFO_D弹窗。
            # 此处不设置 _withdraw，让后续S/A/B/C评价条件覆盖误匹配。
            # 真正的D评价会先被上方OPTS_INFO_D捕获。
            if self.appear(BATTLE_STATUS_D) or self.appear(EXP_INFO_D):
                break
            if confirm_timer.reached():
                # 结算确认超时：不扣心情、不盲目点击OPTS_INFO_D
                # 只设置_withdraw让status处理，status中检测到OPTS_INFO_D才扣心情
                logger.warning('[自动搜索-战斗] 结算确认超时，进入status处理')
                self._withdraw = True
                confirm_timer.reset()
                break
            # A/B/C评价：自动搜索中非S评价意味着有舰船沉没，扣减沉船心情（10点）
            # S评价不扣减额外沉船心情，仅保留进入战斗时的基础扣减（2点）
            # 设置_shipwreck_emotion_reduced防止C评价后续出现OPTS_INFO_D时重复扣减
            if self.appear(BATTLE_STATUS_A) or self.appear(BATTLE_STATUS_B) or self.appear(BATTLE_STATUS_C) \
                    or self.appear(EXP_INFO_A) or self.appear(EXP_INFO_B) or self.appear(EXP_INFO_C):
                if emotion_reduce:
                    self.emotion.reduce(fleet_index, shipwreck=True)
                    self._shipwreck_emotion_reduced = True
                break
            if self.appear(BATTLE_STATUS_S) or self.appear(EXP_INFO_S) \
                    or self.appear(GET_MISSION) or self.is_auto_search_running():
                self.device.screenshot_interval_set()
                break
            if callable(expected_end):
                if expected_end():
                    self.device.screenshot_interval_set()
                    break
            

    def _wait_withdraw_stable(self, withdraw_stable_timer):
        """
        等待WITHDRAW按钮稳定出现，防止界面过渡动画导致误判。

        Args:
            withdraw_stable_timer (Timer): WITHDRAW按钮稳定计时器

        Returns:
            bool: True表示WITHDRAW按钮已稳定出现，可以点击；
                  False表示按钮尚未出现或不稳定，需要继续等待。
        """
        withdraw_appear = self.appear(WITHDRAW, offset=(30, 30))
        if withdraw_appear:
            if not withdraw_stable_timer.reached():
                return False
            return True
        else:
            withdraw_stable_timer.reset()
            return False

    def _handle_fleet_switch_over(self):
        """
        处理舰队切换操作：仅撤退当前战败舰队，切换到另一队继续战斗。
        包含超时保护，避免UI异常时无限循环。

        沉船后舰队切换流程可能为：
        EXP_INFO_D → FLEET_SWITCH_CONFIRM(延迟出现) → SWITCH_OVER/FLEET_WITHDRAW → 自动搜索恢复
        FLEET_SWITCH_CONFIRM可能在结算画面过渡后才延迟出现，
        因此在此方法中也需要检测，避免错过点击时机。

        SWITCH_OVER点击后，游戏可能显示AUTO_SEARCH_MAP_OPTION_OFF，
        需要点击它开启自动搜索，否则is_auto_search_running()一直返回False，
        导致SWITCH_OVER被反复点击触发GameTooManyClickError。

        Returns:
            bool: True表示切换成功，False表示超时。
        """
        timeout = Timer(10, count=20).start()
        switch_over_clicked = 0
        while 1:
            self.device.screenshot()
            # 舰队切换完成，自动搜索恢复运行
            if self.is_auto_search_running():
                break
            # FLEET_SWITCH_CONFIRM可能在结算过渡后延迟出现
            if self.appear_then_click(FLEET_SWITCH_CONFIRM, offset=(30, 30)):
                continue
            if self.appear_then_click(FLEET_WITHDRAW, offset=(30, 30)):
                break
            if self.appear(FLEET_WITHDRAW_BOSS, offset=(30, 30)):
                self.withdraw()
                break
            # 只点击一次SWITCH_OVER切换舰队，然后处理自律选项开启自动搜索
            # 点击多次会导致GameTooManyClickError
            if switch_over_clicked < 1 and self.appear_then_click(SWITCH_OVER, interval=2):
                switch_over_clicked += 1
                continue
            # 处理自动搜索地图选项（关闭AUTO_SEARCH_MAP_OPTION_OFF，开启自动搜索）
            if self.handle_auto_search_map_option():
                continue
            if timeout.reached():
                logger.warning('舰队切换超时，改为撤退')
                self.withdraw()
                break
        self.fleet_alive_multiple = False
        return True

    def auto_search_combat_status(self):
        """处理自动搜索战斗后的结算与战败恢复。

        处理经验结算、掉落物品、战败撤退与舰队切换，直至自动搜索重新运行或关卡结束。

        Raises:
            CampaignEnd: 战斗结束且回到自动搜索菜单，或触发撤退时抛出。
            ScriptEnd: 连续战败达到上限且配置为撤退停止时抛出。

        Pages:
            in: 任意结算界面
            out: is_auto_search_running()
        """
        logger.info('[自动搜索-结算] 战斗结算')
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        exp_info = False  # 用于处理游戏中的白屏异常
        withdraw_stable_timer = Timer(2)

        for _ in self.loop():

            # 结束判断
            if self.is_auto_search_running():
                self._auto_search_status_confirm = False
                # 战斗正常结束（非战败），重置连续战败计数
                if self._defeat_count > 0:
                    logger.info('战斗胜利，重置失败计数')
                    self._defeat_count = 0
                break
            if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
                raise CampaignEnd

            # 撤退处理
            if self._withdraw:
                # 先处理战斗结算界面（D评价、经验信息、获得舰船等），
                # 结算完成后才会出现FLEET_SWITCH_CONFIRM或WITHDRAW按钮
                # 沉船D评价流程：OPTS_INFO_D → BATTLE_STATUS_D → EXP_INFO_D → OPTS_INFO_D(再次出现) → FLEET_SWITCH_CONFIRM
                if self.appear_then_click(OPTS_INFO_D, offset=(30, 30), interval=2):
                    continue
                if self.handle_battle_status():
                    continue
                if self.handle_exp_info():
                    continue
                if self.handle_get_ship():
                    continue
                if self.handle_get_items():
                    continue
                if self.handle_popup_confirm('combat_status'):
                    continue

                defeat_withdraw = self.config.Campaign_DefeatWithdraw
                if defeat_withdraw == 'withdraw_continue' or defeat_withdraw == 'withdraw_stop':
                    # 撤退后继续任务 / 撤退后关闭任务：
                    # 点击FLEET_SWITCH_CONFIRM仅关闭弹窗，不取消撤退
                    # 游戏在舰队战败后弹出FLEET_SWITCH_CONFIRM，点击后才能看到WITHDRAW按钮
                    if self.appear_then_click(FLEET_SWITCH_CONFIRM, offset=(30, 30)):
                        continue
                    if self.handle_popup_confirm('WITHDRAW'):
                        continue
                    if not self._wait_withdraw_stable(withdraw_stable_timer):
                        continue
                    self._withdraw = False
                    if defeat_withdraw == 'withdraw_stop':
                        # 撤退后关闭任务：连续3次战败才关闭任务
                        self._defeat_count += 1
                        logger.attr('战败计数', f'{self._defeat_count}/3')
                        if self._defeat_count >= 3:
                            # 连续3次战败，关闭任务
                            # withdraw()内部抛出CampaignEnd，
                            # 需要捕获后转换为ScriptEnd以终止任务
                            try:
                                self.withdraw()
                            except CampaignEnd:
                                raise ScriptEnd('DefeatWithdraw=withdraw_stop')
                        else:
                            # 未满3次，撤退后继续任务
                            self.withdraw()
                            break
                    else:
                        self.withdraw()
                    break
                elif defeat_withdraw == 'switch_fleet':
                    # 切换队伍继续出击：尝试切换另一队继续战斗
                    if self.appear_then_click(FLEET_SWITCH_CONFIRM, offset=(30, 30)):
                        self.fleet_alive_multiple = False
                        self._withdraw = False
                        continue
                    if not self._wait_withdraw_stable(withdraw_stable_timer):
                        continue

                    self._withdraw = False
                    if not self.fleet_alive_multiple:
                        self.withdraw()
                        break
                    else:
                        self._handle_fleet_switch_over()
                        continue

            # 战斗结算状态处理
            if self.handle_get_ship():
                continue
            if not self._withdraw and self.handle_auto_search_map_option():
                self._auto_search_status_confirm = False
                continue
            # 处理各种弹窗
            if self.handle_popup_confirm('AUTO_SEARCH_COMBAT_STATUS'):
                continue
            if self.handle_urgent_commission():
                continue
            if self.handle_story_skip():
                continue
            if self.handle_guild_popup_cancel():
                continue
            if self.handle_vote_popup():
                continue
            if self.handle_mission_popup_ack():
                continue

            # 处理战斗结算界面——SABC评价在自动搜索中可能快速自动过渡，
            # 若截图恰好捕获到结算画面则点击推进并记录评价
            # D评价点击BATTLE_STATUS_D后，会出现OPTS_INFO_D沉船弹窗
            if self.handle_battle_status():
                continue
            if self.handle_exp_info():
                continue
            # 检测D评价（沉船）弹窗——这是沉船的确认性标志（二次确认）
            # 只有OPTS_INFO_D出现才确认是真正的D评价并扣心情
            # S/A/B/C转场误匹配BATTLE_STATUS_D不会出现OPTS_INFO_D，不会扣心情
            if self.appear(OPTS_INFO_D, offset=(30, 30)):
                logger.info('[自动搜索-结算] 检测到沉船弹窗，进入撤退处理')
                if self._auto_search_emotion_reduce and not self._shipwreck_emotion_reduced:
                    self.emotion.reduce(self._auto_search_fleet_index, shipwreck=True)
                    self._shipwreck_emotion_reduced = True
                self._withdraw = True
                continue

            # 处理低心情出击状态
            if self._auto_search_status_confirm:
                if not exp_info and self.handle_get_ship():
                    continue
                if self.handle_get_items():
                    continue
                if self.handle_battle_status():
                    continue
                if self.handle_popup_confirm('combat_status'):
                    continue
                if self.handle_exp_info():
                    exp_info = True
                    continue

    def auto_search_combat(self, emotion_reduce=None, fleet_index=1, battle=None):
        """执行单次自动搜索战斗全流程。

        包含战斗执行及后续的状态结算。
        注意：fleet_index 中 1 表示道中队，2 表示 Boss 队，
        不同于编队准备或自动搜索设置中的舰队编号。

        Args:
            emotion_reduce (bool, optional): 是否扣减心情。若为 None 则使用 self.emotion.is_calculate。默认为 None。
            fleet_index (int, optional): 舰队索引（1 为道中队，2 为 Boss 队）。默认为 1。
            battle (tuple[int, int], optional): 当前战斗场次信息。默认为 None。
        """
        emotion_reduce = emotion_reduce if emotion_reduce is not None else self.emotion.is_calculate

        self._auto_search_emotion_reduce = emotion_reduce
        self._auto_search_fleet_index = fleet_index
        self._shipwreck_emotion_reduced = False
        self.auto_search_combat_execute(emotion_reduce=emotion_reduce, fleet_index=fleet_index, battle=battle)
        self.auto_search_combat_status()

        logger.info('[自动搜索-战斗] 战斗结束')

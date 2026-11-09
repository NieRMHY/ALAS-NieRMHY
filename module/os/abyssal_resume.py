"""深渊关卡防误判与可选断点记录；实际寻路、战斗与脱离仍由 OSFleet 执行。"""

from module.config.utils import get_os_next_reset
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.os.assets import ABYSSAL_MAP_CHECK, ABYSSAL_STAGE_2, MAP_GOTO_GLOBE


ABYSSAL_RESUME_KEY = 'OpsiAbyssal.Storage.Storage.AbyssalResume'
ABYSSAL_CONTINUE_KEY = 'OpsiAbyssal.OpsiAbyssal.ContinueAfterRestart'

# Add by MHY, 2026-11-08: 深渊类型只认当前画面的专有关卡特征，断点记录不参与判断
ABYSSAL_PAGE_CONFIRMED = 'confirmed'
ABYSSAL_PAGE_OTHER = 'other'
ABYSSAL_PAGE_UNKNOWN = 'unknown'

# 续接动作：确认深渊才续接，画面不足但断点完整时保留现场，其余按当前画面继续
ABYSSAL_ACTION_RESUME = 'resume'
ABYSSAL_ACTION_DEFER = 'defer'
ABYSSAL_ACTION_CLEAR = 'clear'


class AbyssalResumeMixin:
    """所有深渊共用关卡确认，只有续接开启时才保存断点。"""

    def abyssal_continue_enabled(self):
        """读取独立深渊任务的开关，兼容智能调度等代理入口。"""
        return self.config.cross_get(ABYSSAL_CONTINUE_KEY, default=False) is True

    def abyssal_page_state(self):
        """按当前画面判断海域类型，任何断点记录都不参与判断。

        Returns:
            str: ABYSSAL_PAGE_CONFIRMED 画面出现深渊专有关卡特征；
                ABYSSAL_PAGE_OTHER 可确认不在深渊（普通海域或隐秘海域）；
                ABYSSAL_PAGE_UNKNOWN 在特殊海域，但画面没有深渊专有特征。
        """
        # Add by MHY, 2026-11-08: 深渊模板只截了国服，非国服不能拿断点猜海域类型
        if self.appear(ABYSSAL_MAP_CHECK, offset=(20, 20)):
            return ABYSSAL_PAGE_CONFIRMED
        if self.appear(ABYSSAL_STAGE_2, offset=(20, 20)):
            return ABYSSAL_PAGE_CONFIRMED
        if not self.is_in_special_zone():
            return ABYSSAL_PAGE_OTHER
        # 海域名里的隐秘关键字四个服务器都有识别，命中即可正向排除深渊。
        if self.is_obscure_zone:
            return ABYSSAL_PAGE_OTHER
        return ABYSSAL_PAGE_UNKNOWN

    def is_in_abyssal(self):
        """只有当前画面确认深渊时才为真，避免接管其他特殊海域。"""
        return self.abyssal_page_state() == ABYSSAL_PAGE_CONFIRMED

    def abyssal_resume_action(self):
        """按页面证据决定续接动作，断点只在画面无法确认时用于保留现场。"""
        page = self.abyssal_page_state()
        if page == ABYSSAL_PAGE_CONFIRMED:
            return ABYSSAL_ACTION_RESUME
        if page == ABYSSAL_PAGE_UNKNOWN and self._abyssal_resume_pending():
            return ABYSSAL_ACTION_DEFER
        return ABYSSAL_ACTION_CLEAR

    def _abyssal_resume_pending(self):
        """存在同服务器、同周期、同海域且字段完整的断点，才值得保留现场。"""
        return self._valid_abyssal_state(
            self.config.cross_get(ABYSSAL_RESUME_KEY, default=None))

    def _abyssal_state_in_current_zone(self, state):
        """断点必须属于同一服务器、同一重置周期和当前海域。"""
        zone = getattr(self, 'zone', None)
        return (isinstance(state, dict)
                and zone is not None
                and state.get('server') == self.config.SERVER
                and state.get('reset') == get_os_next_reset().isoformat()
                and state.get('zone') == zone.zone_id)

    def _valid_abyssal_state(self, state):
        """海域匹配之外还要求字段完整，缺字段的旧记录不能用来保留现场。"""
        return (self._abyssal_state_in_current_zone(state)
                and state.get('entry_fleet') in (0, 1, 2, 3, 4)
                and state.get('phase') in ('search', 'boss')
                and state.get('active') in (0, 1, 2, 3, 4)
                and isinstance(state.get('fighting'), bool)
                and isinstance(state.get('completed'), list)
                and all(fleet in (1, 2, 3, 4) for fleet in state['completed']))

    def _defer_abyssal_resume(self):
        """画面无法确认深渊时保留断点与现场，交人工判断后再处理。

        Raises:
            RequestHumanTakeover: 当前特殊海域类型不确定，需要人工确认。
        """
        logger.warning('[大世界-深渊续接] 当前特殊海域没有深渊专有关卡特征'
                       '（深渊模板只有国服截图），无法确认这片海域是深渊')
        logger.warning('[大世界-深渊续接] 已保留断点与当前海域，既不清记录也不进新坐标；'
                       '确认仍是深渊请手动处理后重新开始任务，确认是其他海域请先退出该海域')
        raise RequestHumanTakeover('大世界深渊续接无法确认当前特殊海域类型')

    def resume_abyssal_on_init(self):
        """通过公开任务上下文续接，独立地图对象也不依赖智能调度的私有方法。"""
        from module.config.config import name_to_function
        from module.os.tasks.abyssal import OpsiAbyssal
        from module.os.tasks.task_context import opsi_task_context
        from module.os_handler.resource_state import reset_resource_caches

        with opsi_task_context(self.config, name_to_function('OpsiAbyssal'),
                               bind_task='OpsiAbyssal', disable_task_switch=True):
            task = OpsiAbyssal(config=self.config, device=self.device)
            task.zone = self.zone
            task.clear_abyssal()
        # 维修可能已切到港口，调用方必须重新确认海域，不能沿用深渊的旧位置。
        self.zone_init()
        reset_resource_caches(self)

    def _load_abyssal_resume(self):
        """旧断点只能用于相同服务器、重置周期和海域。"""
        state = self.config.cross_get(ABYSSAL_RESUME_KEY, default=None)
        if self._valid_abyssal_state(state):
            state = dict(state, completed=list(state['completed']))
            state.setdefault('stage', 'boss' if state['phase'] == 'boss' else 'entry1')
            state.setdefault('resume_used', False)
            # 旧版本仅凭红色障碍就可能误记 boss，只有实际进入过战斗的旧记录可作确认。
            state.setdefault('boss_confirmed', state['phase'] == 'boss' and state['fighting']
                             and state['active'] in (1, 2, 3, 4))
            if isinstance(state['resume_used'], bool) and isinstance(state['boss_confirmed'], bool):
                return state
        logger.info('[大世界-深渊续接] 断点已失效，按当前画面继续')
        self._clear_abyssal_resume()
        return None

    def _save_abyssal_resume(self, state):
        """在操作前落盘，避免进程重启后丢失探路舰队或出战位置。"""
        self.config.cross_set(ABYSSAL_RESUME_KEY, dict(state, completed=list(state['completed'])))

    def _clear_abyssal_resume(self):
        """确认离开深渊后清除断点，不带入下一张坐标。"""
        if self.config.cross_get(ABYSSAL_RESUME_KEY, default=None) is not None:
            self.config.cross_set(ABYSSAL_RESUME_KEY, None)

    def _new_abyssal_resume(self):
        """记住进入第一阶段时的实际舰队，而非 Boss 筛选器的第一项。"""
        state = {
            'server': self.config.SERVER,
            'reset': get_os_next_reset().isoformat(),
            'zone': self.zone.zone_id,
            'entry_fleet': self.fleet_selector.get(),
            'phase': 'search',
            'active': 0,
            'fighting': False,
            'completed': [],
            'stage': 'entry1',
            'resume_used': False,
            'boss_confirmed': False,
        }
        self._save_abyssal_resume(state)
        return state

    def _set_abyssal_stage(self, state, stage):
        """阶段前进时机会重置为一次，不把上一阶段的剩余机会累计过来。"""
        if state['stage'] != stage:
            state.update(stage=stage, resume_used=False)
            logger.attr('深渊续接阶段', stage)
            self._save_abyssal_resume(state)

    def _refresh_abyssal_stage(self, state):
        """仅凭当前画面的正向特征更新阶段；雷达、视野由调用方先刷新。"""
        questions = self.radar.select(is_question=True)
        if self.appear(ABYSSAL_STAGE_2, offset=(20, 20)):
            state.update(phase='search', boss_confirmed=False, active=0, fighting=False, completed=[])
            self._set_abyssal_stage(state, 'entry2')
            return
        if questions:
            # 前两关的问号是门；未确认过 Boss 时不能把红色障碍误识别成战斗中。
            if not state['boss_confirmed'] or state['stage'] in ('entry1', 'entry2'):
                state.update(phase='search', boss_confirmed=False, active=0, fighting=False, completed=[])
                if state['stage'] not in ('entry1', 'entry2'):
                    self._set_abyssal_stage(state, 'entry1')
            return
        if self._abyssal_boss_appear():
            if (any(grid.predict_caught_by_siren() for grid in self.view)
                    and not any(grid.is_current_fleet for grid in self.view)):
                current = state['active'] or self.fleet_selector.get()
                state.update(phase='boss', boss_confirmed=True)
                self._set_abyssal_stage(state, f'fleet{current}' if current else 'boss')
            elif not state['boss_confirmed']:
                state.update(phase='boss', boss_confirmed=True)
                self._set_abyssal_stage(state, 'boss')

    def _abyssal_boss_appear(self):
        """正常战斗和续接共用的 Boss 关确认，入口问号和第二阶段画面优先。"""
        if self.is_in_map():
            if self.appear(ABYSSAL_STAGE_2, offset=(20, 20)) or self.radar.select(is_question=True):
                return False
            if (any(grid.predict_caught_by_siren() for grid in self.view)
                    and not any(grid.is_current_fleet for grid in self.view)):
                return True
            return bool(self.radar.select(is_enemy=True).filter(
                lambda grid: abs(grid.location[0]) <= abs(grid.location[1]) and grid.predict_boss()))
        return False

    def _abyssal_boss_cleared(self, state):
        """只有已正向确认进入 Boss 关，地图上的问号才可能表示清除后的出口。"""
        return (state['phase'] == 'boss' and state.get('boss_confirmed', False) and self.is_in_map()
                and not self.appear(ABYSSAL_STAGE_2, offset=(20, 20))
                and bool(self.radar.select(is_question=True)))

    def _abyssal_map_finished(self):
        """普通海域的全球地图入口确认深渊已消失，不以暂时识别不到深渊作判断。"""
        if self.is_in_map() and self.appear(MAP_GOTO_GLOBE, offset=(20, 20)):
            logger.info('[大世界-深渊续接] 已回到普通海域，清除全部续接标记并继续后续任务')
            self._clear_abyssal_resume()
            return True
        return False

    def run_abyssal_normal(self):
        """关闭续接时仍确认关卡，只保存本次运行的判断，不读写或恢复断点。

        Pages:
            in: 深渊地图。
            out: 成功时回到来源海域；舰队耗尽时按原返回值交回任务收尾。
        """
        state = {'phase': 'search', 'boss_confirmed': False}
        self._abyssal_normal_state = state
        try:
            while True:
                self.device.screenshot()
                if self.is_in_map():
                    self.question_goto(has_fleet_step=True)
                    if self._abyssal_boss_appear():
                        state.update(phase='boss', boss_confirmed=True)
                        break
                else:
                    self.handle_map_event()
            return self.boss_clear(has_fleet_step=True, allow_submarine_call=False, abyssal_check=state)
        finally:
            self._abyssal_normal_state = None

    def run_abyssal_resume(self, resume=False):
        """按当前阶段续接一次；阶段变化刷新机会，耗尽时沿原退出流程收尾。

        Pages:
            in: 深渊地图。
            out: 当前深渊处理完毕后的地图；实际战斗失败仍按原机制返回 False。
        """
        state = self._load_abyssal_resume() or self._new_abyssal_resume()
        self._abyssal_progress = state
        try:
            while True:
                self.device.screenshot()
                if self._abyssal_map_finished():
                    return True
                if self.is_in_map():
                    if not state['entry_fleet']:
                        state['entry_fleet'] = self.fleet_selector.get()
                        self._save_abyssal_resume(state)
                    self.update_os()
                    self.predict()
                    self.predict_radar()
                    self._refresh_abyssal_stage(state)
                    if resume:
                        if state['resume_used']:
                            logger.info('[大世界-深渊续接] 当前阶段已续接过一次，按原流程退出')
                            self.map_exit()
                            self._clear_abyssal_resume()
                            return True
                        state['resume_used'] = True
                        self._save_abyssal_resume(state)
                        resume = False
                    if state['phase'] == 'boss' and state['boss_confirmed']:
                        break
                    if state['entry_fleet'] and self.fleet_selector.get() != state['entry_fleet']:
                        self.fleet_set(state['entry_fleet'])
                        continue
                    self.question_goto(has_fleet_step=True)
                else:
                    self.handle_map_event()

            self._abyssal_battle_progress = state
            result = self.boss_clear(has_fleet_step=True, allow_submarine_call=False, abyssal_state=state)
            if result:
                self._clear_abyssal_resume()
            return result
        finally:
            self._abyssal_progress = None
            self._abyssal_battle_progress = None

    def _record_abyssal_combat(self):
        """确认进入战斗时才标记已出战，单纯行军中重启不会跳过该舰队。"""
        state = getattr(self, '_abyssal_battle_progress', None)
        if state is not None and state['active'] and not state['fighting']:
            state.update(fighting=True, boss_confirmed=True)
            self._save_abyssal_resume(state)

    def _resume_abyssal_fleet(self, state, fleets, has_fleet_step, drop):
        """先脱离中断的 Boss 战，再沿原筛选顺序继续后续舰队。

        Pages:
            in: 深渊地图，可能仍显示行动中和脱离按钮。
            out: 深渊地图，中断的舰队已脱离并回到原待命位置。
        """
        self.update_os()
        self.predict()
        caught = any(grid.predict_caught_by_siren() for grid in self.view)
        if not (state['fighting'] or caught):
            return
        current = state['active'] or self.fleet_selector.get()
        if current and self.fleet_selector.get() != current:
            self.fleet_set(current)
        state.update(phase='boss', active=current, fighting=True)
        # 没有旧记录时，当前行动中的舰队即本轮出战位置；之前的舰队也不重打。
        if any(fleet.fleet_index == current for fleet in fleets):
            for fleet in fleets:
                if fleet.fleet_index not in state['completed']:
                    state['completed'].append(fleet.fleet_index)
                if fleet.fleet_index == current:
                    break
        self._save_abyssal_resume(state)
        logger.info(f'[大世界-深渊续接] 舰队 {current} 的战斗中断，先脱离后继续下一队')
        self.boss_leave()
        if self._abyssal_map_finished():
            return
        for fleet in fleets:
            if fleet.fleet_index == current and fleet.standby_loca != (0, 0):
                self.boss_goto(location=fleet.standby_loca, has_fleet_step=has_fleet_step, drop=drop)
                break
        if self._abyssal_map_finished():
            return
        state.update(active=0, fighting=False)
        self._save_abyssal_resume(state)

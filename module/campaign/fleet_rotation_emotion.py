"""普通主线/活动换船的培养舰位心情；整队账本继续沿用原心情模块。"""

from copy import copy

from module.combat.emotion import Emotion
from module.combat.emotion_state import EmotionRecoveryState
from module.config.time_source import now
from module.exception import FleetManagementError
from module.runtime.fleet_rotation import ROTATION_PATH, minimum_morale
from module.runtime.fleet_training import goals, persist_context


def selected_morale(readings, slots):
    """只统计勾选舰位的在队舰船；占用舰位读数未知时不能用固定舰船代替。"""
    return minimum_morale({slot: readings[slot] for slot in slots if slot in readings})


class RotationEmotion(Emotion):
    """只由支持换船的出击前入口安装，不改变其他任务的心情策略。

    培养账本保留整数恢复相位与实际战斗扣减，跨任务启动恢复；没有有效账本时
    才先实测重建。整队 Value/Record/RecoveryState 始终记录全队最低值。
    """

    def __init__(self, config, context, rules, selected):
        super().__init__(config)
        self.context, self.rules, self.selected = context, rules, selected

    @property
    def rotation_enabled(self):
        return bool(self.selected) and (self.config.cross_get(ROTATION_PATH + '.Enabled', False) is True
                                        or bool(goals(self.config)))

    @property
    def selected_only(self):
        return (self.rotation_enabled
                and self.config.cross_get(ROTATION_PATH + '.SelectedOnly', False) is True)

    @property
    def is_calculate(self):
        # 新开关显式要求培养心情计算，不能被任务的 ignore 模式绕过。
        return self.rotation_enabled or super().is_calculate

    @property
    def is_ignore(self):
        # 新开关负责是否忽略固定红脸，不能忽略培养舰船自身的红脸。
        return False if self.rotation_enabled else super().is_ignore

    def tracker(self, role):
        return self.public_fleet if self.using_public else self.fleets[role - 1]

    def calibrate_selected(self, readings):
        states = self.context.setdefault('training', {})
        for role, actual in self.selected.items():
            if actual not in readings:
                continue
            slots = self.rules[str(actual)]['slots']
            value = selected_morale(readings[actual], slots)
            fleet = self.tracker(role)
            state = None if value is None else EmotionRecoveryState.calibrate(
                value, now(), fleet.recover, fleet.oath, fleet.onsen)
            states[role] = dict(actual=actual, slots=list(slots), state=state)

    def training_state(self, role):
        saved = self.context.get('training', {}).get(role, {})
        actual = self.selected.get(role)
        state = saved.get('state')
        fleet = self.tracker(role)
        if (actual is None or saved.get('actual') != actual
                or saved.get('slots') != self.rules[str(actual)]['slots'] or state is None
                or (state.recover, state.oath, state.onsen) != (fleet.recover, fleet.oath, fleet.onsen)):
            return None
        state.advance(now())
        return state

    def training_lower(self, role):
        state = self.training_state(role)
        return None if state is None else state.lower

    def _get_recovered(self, fleet, expected_reduce):
        if not self.selected_only:
            return super()._get_recovered(fleet, expected_reduce)
        selected_roles = self.selected if fleet.fleet == 'Public' else [fleet.fleet]
        recovered = now()
        for role in selected_roles:
            if role not in self.selected:
                continue
            state = self.training_state(role)
            if state is None:
                self.context['scanned'] = False
                raise FleetManagementError('培养舰位心情未确认，请重新扫描舰队后继续')
            # 复用原控制线、单图消耗、恢复预留和配置冲突检查，不改写整队账本。
            training = copy(fleet)
            training.state = state
            recovered = max(recovered, super()._get_recovered(training, expected_reduce))
        return recovered

    def reduce(self, fleet_index, shipwreck=False):
        calculate = self.is_calculate
        self.update()
        # 忽略固定角色时，固定角色未知不能阻止培养计算；整队未知账本仍保持未知。
        if not self.selected_only or self.tracker(fleet_index).state is not None:
            super().reduce(fleet_index, shipwreck=shipwreck)
        if not calculate or (shipwreck and self.config.Emotion_IgnoreShipwreck):
            return
        if fleet_index in self.selected:
            state = self.training_state(fleet_index)
            if state is not None:
                state.consume(self.reduce_shipwreck if shipwreck else self.reduce_per_battle)
                persist_context(self.config, self.context)

    def rotation_popup_allowed(self):
        """仅在培养舰位充足时确认固定红脸，不把固定低值算到培养账本。"""
        self.update()
        for role in self.selected:
            value = self.training_lower(role)
            fleet = self.tracker(role)
            if value is None or value < fleet.limit + self.reduce_per_battle:
                return False
        fleets = [self.public_fleet] if self.using_public else [self.fleets[role - 1] for role in self.selected]
        return all(self._get_recovered(fleet, self.reduce_per_battle) <= now() for fleet in fleets)

    def delay_rotation_popup(self, battle):
        """退出后重扫培养舰位；培养恢复预留仍按原调度延迟。"""
        needs_scan = any(self.training_lower(role) is None or
                         self.training_lower(role) < self.tracker(role).limit + self.reduce_per_battle
                         for role in self.selected)
        recovered = now() if needs_scan else self._check_reduce(battle)[0]
        self.context['scanned'] = False
        self.context.pop('training', None)
        persist_context(self.config, self.context)
        self.config.task_delay(target=recovered)

    def emergency_reset(self):
        super().emergency_reset()
        self.context['scanned'] = False
        self.context.pop('training', None)
        persist_context(self.config, self.context)

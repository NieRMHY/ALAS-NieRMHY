"""演习装备管理模块。

管理演习（PvP）中的装备编辑操作。
在演习准备界面中可以切换舰船的装备配置。

功能：
- 激活/关闭装备编辑模式
- 检测装备编辑按钮状态

继承自 Equipment 基类。
"""

from module.base.timer import Timer
from module.combat.assets import BATTLE_PREPARATION
from module.equipment.equipment import Equipment
from module.exercise.assets import *


class ExerciseEquipment(Equipment):
    """演习装备编辑器。

    管理演习准备界面中的装备编辑按钮状态切换。
    """
    def _active_edit(self):
        """激活装备编辑模式，展开装备编辑按钮。

        Pages:
            in: EQUIP_EDIT_INACTIVE
            out: EQUIP_EDIT_ACTIVE
        """
        timer = Timer(5)
        while 1:
            self.device.screenshot()

            if timer.reached() and self.appear_then_click(EQUIP_EDIT_INACTIVE):
                timer.reset()

            # 结束条件
            if self.appear(EQUIP_EDIT_ACTIVE):
                self.device.sleep((0.2, 0.3))
                break

    def _inactive_edit(self):
        """退出装备编辑模式，收起装备编辑按钮。

        Pages:
            in: EQUIP_EDIT_ACTIVE
            out: EQUIP_EDIT_INACTIVE
        """
        timer = Timer(5)
        while 1:
            self.device.screenshot()

            if timer.reached() and self.appear_then_click(EQUIP_EDIT_ACTIVE):
                timer.reset()

            # 结束条件
            if self.appear(EQUIP_EDIT_INACTIVE):
                self.device.sleep((0.2, 0.3))
                break

    def equipment_take_on(self):
        """在演习出击前为舰队穿戴预设装备。

        Returns:
            bool: 成功穿戴返回 True，未配置或已穿戴返回 False。
        """
        if self.config.EXERCISE_FLEET_EQUIPMENT is None:
            return False
        if self.equipment_has_take_on:
            return False

        self._active_edit()
        super().equipment_take_on(enter=EQUIP_ENTER, out=BATTLE_PREPARATION, fleet=self.config.EXERCISE_FLEET_EQUIPMENT)
        self._inactive_edit()
        return True

    def equipment_take_off(self):
        """在演习结束后卸下舰队预设装备。

        Returns:
            bool: 成功卸下返回 True，未配置或未穿戴返回 False。
        """
        if self.config.EXERCISE_FLEET_EQUIPMENT is None:
            return False
        if not self.equipment_has_take_on:
            return False

        self._active_edit()
        super().equipment_take_off(enter=EQUIP_ENTER, out=BATTLE_PREPARATION, fleet=self.config.EXERCISE_FLEET_EQUIPMENT)
        self._inactive_edit()
        return True

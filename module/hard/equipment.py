"""困难模式装备管理模块。

处理困难关卡中舰队装备的自动装卸。根据配置的舰队编号
选择对应的装备入口，继承通用装备管理逻辑，实现在进入
困难关卡前自动换装、通关后还原装备的流程。
"""

from module.equipment.equipment import Equipment
from module.hard.assets import *
from module.map.assets import *


class HardEquipment(Equipment):
    """困难模式装备穿脱管理类。

    继承通用装备管理逻辑，在困难模式舰队准备界面中根据配置穿上或脱下舰队装备。
    """

    def equipment_take_on(self):
        """为困难模式舰队穿上预设装备。

        Returns:
            bool: 成功执行换装返回 True，未配置装备或已穿戴返回 False。

        Pages:
            in: FLEET_PREPARATION
            out: FLEET_PREPARATION
        """
        if self.config.FLEET_HARD_EQUIPMENT is None:
            return False
        if self.equipment_has_take_on:
            return False

        enter = EQUIP_ENTER_1 if self.config.FLEET_HARD == 1 else EQUIP_ENTER_2
        super().equipment_take_on(enter=enter, out=FLEET_PREPARATION, fleet=self.config.FLEET_HARD_EQUIPMENT)
        return True

    def equipment_take_off(self):
        """脱下困难模式舰队的装备。

        Returns:
            bool: 成功脱下装备返回 True，未配置装备或尚未穿戴返回 False。

        Pages:
            in: FLEET_PREPARATION
            out: FLEET_PREPARATION
        """
        if self.config.FLEET_HARD_EQUIPMENT is None:
            return False
        if not self.equipment_has_take_on:
            return False

        enter = EQUIP_ENTER_1 if self.config.FLEET_HARD == 1 else EQUIP_ENTER_2
        super().equipment_take_off(enter=enter, out=FLEET_PREPARATION, fleet=self.config.FLEET_HARD_EQUIPMENT)
        return True

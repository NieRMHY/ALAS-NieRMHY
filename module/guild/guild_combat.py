"""大舰队战斗处理器，继承战斗基类并适配大舰队特有的战斗结算画面。
处理大世界风格的战斗状态和获取物品界面。
"""

from module.combat.combat import Combat
from module.guild.assets import BATTLE_STATUS_CF, EXP_INFO_CF


class GuildCombat(Combat):
    """大舰队战斗处理类。

    继承通用战斗类，适配大舰队作战特有的结算画面、经验信息与掉落物品弹窗。
    """

    def handle_battle_status(self, drop=None):
        """处理战斗评价/结算画面，包括大舰队特有的结算标记。

        Args:
            drop (DropImage, optional): 掉落统计对象。

        Returns:
            bool: 处于结算画面并已点击确认返回 True，否则返回 False。
        """
        if self.is_combat_executing():
            return False
        if super().handle_battle_status(drop=drop):
            return True
        if self.appear(BATTLE_STATUS_CF, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(BATTLE_STATUS_CF)
            return True

        return False

    def handle_get_items(self, drop=None):
        """处理战斗结算后的获得物资/道具弹窗。

        Args:
            drop (DropImage, optional): 掉落统计对象。

        Returns:
            bool: 检测到道具获得弹窗并已点击确认返回 True，否则返回 False。
        """
        if super().handle_get_items(drop=drop):
            self.interval_reset(BATTLE_STATUS_CF)
            return True
        else:
            return False

    def handle_exp_info(self):
        """处理战斗后的经验值获得提示画面。

        Returns:
            bool: 检测到经验信息并已点击跳过返回 True，否则返回 False。
        """
        if self.is_combat_executing():
            return False
        if super().handle_exp_info():
            return True
        if self.appear_then_click(EXP_INFO_CF):
            self.device.sleep((0.25, 0.5))
            return True

        return False

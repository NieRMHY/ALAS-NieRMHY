"""弃船突袭处理器，处理弃船突袭特有的战斗结算逻辑。

共斗每次出击仅扣一次基础心情（通常为 2 点），
非 S 评价及 C/D 战败不额外扣减心情。不再自动替换牺牲舰船，
战斗循环由 RunCount 等停止条件控制。
"""

from module.guild.assets import BATTLE_STATUS_CF
from module.raid.combat import RaidCombat
from module.raid.run import RaidRun


class RaidScuttleCombat(RaidCombat):
    # Modify by MHY, 复用公共失败结算与单场结果，仅豁免额外心情扣减。
    combat_shipwreck_emotion = False
    # Add by MHY, 共斗好感的石油复核仍需要正常结算信号。
    triggered_normal_end = False

    def combat_result_reset(self, emotion_reduce=False, fleet_index=1):
        super().combat_result_reset(emotion_reduce=emotion_reduce, fleet_index=fleet_index)
        self.triggered_normal_end = False

    def handle_battle_status(self, drop=None):
        handled = super().handle_battle_status(drop=drop)
        # Add by MHY, 共斗专用成功布局没有通用评价字母，仍保留正常结算的油耗复核信号。
        if handled and not self.combat_result.defeated and self.appear(BATTLE_STATUS_CF):
            self.triggered_normal_end = True
        return handled

    def combat_result_record(self, rank=None, defeated=False, fleet_unavailable=False):
        super().combat_result_record(rank=rank, defeated=defeated, fleet_unavailable=fleet_unavailable)
        # Add by MHY, 仅正向 S/A/B 结算触发油耗复核，C/D 过渡帧不能当作胜利。
        self.triggered_normal_end = self.combat_result.rank in ('S', 'A', 'B') and not self.combat_result.defeated


class RaidScuttleRun(RaidRun, RaidScuttleCombat):
    """弃船突袭主循环。

    共斗沉船沿用单场心情政策：
    - 每次出击仅扣一次基础心情，非 S 评价及战败不额外扣减 10 点心情
    - 不自动替换牺牲舰船，战斗循环由 RunCount 等停止条件控制
    """

    def handle_combat_low_emotion(self):
        """重写红脸出击警告弹窗处理。

        沉船任务中牺牲舰必然低心情，红脸弹窗出现时点击确认继续出击，
        不触发计算模式下的心情清零保底。

        Returns:
            bool: 是否处理了弹窗确认。
        """
        return self.handle_popup_confirm('IGNORE_LOW_EMOTION')

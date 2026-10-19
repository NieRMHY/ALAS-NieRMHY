"""单场战斗的评价、战败与心情记账上下文。"""

from dataclasses import dataclass


@dataclass
class CombatResult:
    """结果识别与任务恢复分开，重复结算画面共用一次心情扣减。"""

    fleet_index: int = 1
    emotion_reduce: bool = False
    rank: str | None = None
    defeated: bool = False
    fleet_unavailable: bool = False
    shipwreck_reduced: bool = False
    # Add by MHY, 评价页与经验页共用一次主线好感事件。
    affection_recorded: bool = False

    @property
    def needs_shipwreck_penalty(self):
        """只有确认的 S 评价豁免；A 包含无法从评价区分的慢速胜利。"""
        return self.defeated or self.rank in ('A', 'B', 'C', 'D')

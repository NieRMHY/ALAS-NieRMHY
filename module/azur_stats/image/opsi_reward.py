"""
大世界奖励截图识别。

继承 AutoSearchReward，添加大世界（Operation Siren）奖励画面的
判断逻辑，通过按钮模板匹配区分大世界与普通奖励界面。
"""

from module.azur_stats.image.auto_search_reward import AutoSearchReward
from module.os_handler.assets import AUTO_SEARCH_REWARD


class OpsiReward(AutoSearchReward):
    """大型作战（大世界）自律寻敌奖励截图识别器。"""

    def is_opsi_reward(self, image) -> bool:
        """判断是否为大型作战结算奖励界面。

        Args:
            image (np.ndarray): 待检测的截图。

        Returns:
            bool: 是否匹配大型作战奖励界面特征。
        """
        return bool(self.classify_server(AUTO_SEARCH_REWARD, image, offset=(50, 50)))

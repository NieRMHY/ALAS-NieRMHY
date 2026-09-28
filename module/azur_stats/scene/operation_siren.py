"""
大世界场景分析。

组合大世界奖励、物品识别和区域检测，对大世界（Operation Siren）
的截图进行完整的场景级分析，提取掉落物品和区域信息。
"""

import typing as t
from dataclasses import dataclass

from module.azur_stats.image.auto_search_reward import AutoSearchItem
from module.azur_stats.image.get_items import GetItems
from module.azur_stats.image.opsi_reward import OpsiReward
from module.azur_stats.image.opsi_zone import OpsiZone, DataOpsiZone
from module.azur_stats.scene.base import SceneBase
from module.logger import logger


@dataclass
class DataOpsiItems:
    """大型作战掉落物品详细数据结构。

    Attributes:
        imgid (str): 图像唯一标识 ID。
        server (str): 所属服务器标识。
        zone (str): 标准化英文海域名称。
        zone_type (str): 海域类型（如 SAFE, ABYSSAL 等）。
        zone_id (int): 海域数字编号。
        hazard_level (int): 海域危险等级（1 至 6）。
        item (str): 掉落物品名称标识。
        amount (int): 掉落物品数量。
        tag (str): 物品分类标签（如 'meow', 'log', 'scan' 等）。
    """
    imgid: str
    server: str

    zone: str
    zone_type: str
    zone_id: int
    hazard_level: int

    item: str
    amount: int
    tag: str


class SceneOperationSiren(SceneBase, OpsiReward, GetItems, OpsiZone):
    """大型作战（大世界）场景分析器。

    整合大世界海域检测与各类奖励物品识别，完成整套结算流程的数据提取与归纳。
    """

    AUTO_SEARCH_ITEM_TEMPLATE_FOLDER = './assets/stats/opsi_reward_items'
    ITEM_TEMPLATE_FOLDER = './assets/stats/opsi_items'

    def extract_assets(self):
        """提取大型作战掉落截图中的未知物品模板。"""
        zone = None
        for _, image in enumerate(self.images):
            if self.is_opsi_zone(image):
                zone = 1
                break
        if zone is None:
            return

        for image in self.images:
            if self.is_opsi_reward(image):
                self.extract_auto_search_item_template(image)
            if self.get_items_count(image):
                self.extract_item_template(image)

    def parse_scene(self):
        """解析大型作战截图序列，提取海域及所有产出的掉落道具列表。

        Yields:
            DataOpsiItems: 解析出的单项物品条目。
        """
        zone = None
        cleared = -1
        for index, image in enumerate(self.images):
            if self.is_opsi_zone(image):
                try:
                    zone = self.parse_opsi_zone(image)
                except Exception as e:
                    # 海域名读不出或不在 ZoneManager 里（新海域、活动图）时不再
                    # 整条丢弃：按未知区域记下奖励，侵蚀等级留空。按任务维度的
                    # 掉落统计照常工作，按侵蚀等级的短猫收益会自动跳过这些行。
                    logger.warning(f'[统计-大世界] 海域识别失败，按未知区域解析: {e}')
                cleared = index
                break
        if zone is None:
            # 整包都没有海域页（例如只在战斗结算里抓到的掉落）也照样解析奖励帧。
            logger.info('[统计-大世界] 掉落记录里没有海域页，按未知区域解析')
            zone = DataOpsiZone(zone='', zone_type='UNKNOWN', zone_id=0, hazard_level=0)
            cleared = -1

        for index, image in enumerate(self.images):
            if index == cleared:
                continue
            elif index < cleared:
                if self.is_get_items(image):
                    items = self.parse_get_items(image)
                    for item in self._operation_siren_product(zone, items):
                        yield item
                if self.is_opsi_reward(image):
                    items = self.parse_auto_search_reward(image)
                    for item in self._operation_siren_product(zone, items):
                        yield item
            elif index > cleared:
                if self.is_get_items(image):
                    items = self.parse_get_items(image)
                    for item in self._operation_siren_product(zone, items, tag='log'):
                        yield item
                if self.is_opsi_reward(image):
                    items = self.parse_auto_search_reward(image)
                    for item in self._operation_siren_product(zone, items, tag='scan'):
                        yield item

    def _operation_siren_product(self, zone: DataOpsiZone, items: t.Iterable[AutoSearchItem], tag: str = None) \
            -> t.Iterable[DataOpsiItems]:
        """将海域信息与掉落物品合并封装为 DataOpsiItems 数据对象。

        Args:
            zone (DataOpsiZone): 当前海域信息对象。
            items (Iterable[AutoSearchItem]): 掉落物品集合。
            tag (str, optional): 覆盖物品标签，若未提供则使用物品自身标签。

        Yields:
            DataOpsiItems: 封装后的物品数据条目。
        """
        for item in items:
            yield DataOpsiItems(
                imgid=self.imgid,
                server=self.server,
                zone=zone.zone,
                zone_type=zone.zone_type,
                zone_id=zone.zone_id,
                hazard_level=zone.hazard_level,
                item=item.name,
                amount=item.amount,
                tag=tag if tag else item.tag,
            )

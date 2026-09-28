"""
大世界区域截图识别。

从大世界地图截图中识别当前区域名称和类型，使用 OCR 读取地图名称，
并通过 ZoneManager 将显示名称映射为标准化的英文区域标识。
"""

from dataclasses import dataclass

from module.azur_stats.image.base import ImageBase
from module.base.decorator import cached_property
from module.exception import ScriptError
from module.ocr.ocr import Ocr
from module.os.assets import MAP_NAME
from module.os.globe_zone import ZoneManager
from module.os_handler.assets import IN_MAP
from module.statistics.utils import ImageError

OCR_OPSI_ZONE = Ocr(MAP_NAME, lang='cnocr', letter=(214, 231, 255), threshold=127, name='OCR_OS_MAP_NAME')


@dataclass
class DataOpsiZone:
    """大世界海域信息数据类。

    Attributes:
        zone (str): 标准化英文海域名称。
        zone_type (str): 海域类型（UNKNOWN, DANGEROUS, SAFE, OBSCURE, ABYSSAL, STRONGHOLD, ARCHIVE）。
        zone_id (int): 游戏内海域数字编号。
        hazard_level (int): 海域危险等级（1 至 6）。
    """
    zone: str
    zone_type: str
    zone_id: int
    hazard_level: int


class OpsiZoneInvalid(ImageError):
    """未知的大世界海域名称。"""
    pass


class OpsiZone(ImageBase):
    """大世界海域截图识别器。

    负责识别大世界地图中的海域名称、类型及危险等级。
    """

    def is_opsi_zone(self, image) -> bool:
        """判断是否位于大世界海域地图界面。

        Args:
            image (np.ndarray): 待检测的截图。

        Returns:
            bool: 是否在大世界海域中。
        """
        return bool(self.classify_server(IN_MAP, image, offset=(200, 5)))

    def parse_opsi_zone(self, image) -> DataOpsiZone:
        """从截图解析大世界海域信息。

        Args:
            image (np.ndarray): 包含海域名称的截图。

        Returns:
            DataOpsiZone: 解析出的海域数据。
        """
        name = OCR_OPSI_ZONE.ocr(image)
        return self._opsi_zone_name_convert(name)

    @cached_property
    def _opsi_zone_manager(self) -> ZoneManager:
        """获取海域管理器单例实例。

        Returns:
            ZoneManager: 海域管理器对象。
        """
        return ZoneManager()

    def _opsi_zone_name_convert(self, name: str) -> DataOpsiZone:
        """将 OCR 识别到的海域文本转换为标准化海域数据对象。

        Args:
            name (str): OCR 识别到的原始海域字符串。

        Returns:
            DataOpsiZone: 转换后的海域数据对象。

        Raises:
            OpsiZoneInvalid: 无法匹配到已知海域。
        """
        types = 'UNKNOWN'
        if '安全' in name:
            types = 'SAFE'
        elif '隐秘' in name:
            types = 'OBSCURE'
        elif '深渊' in name:
            types = 'ABYSSAL'
        elif '要塞' in name:
            types = 'STRONGHOLD'
        elif '档案' in name:
            types = 'ARCHIVE'
        elif name.endswith('-'):
            pass
        else:
            types = 'DANGEROUS'

        if '-' in name:
            prefix = name.split('-')[0]
        else:
            prefix = name.rstrip('安全隐秘塞壬要塞深渊海域-')
        try:
            zone = self._opsi_zone_manager.name_to_zone(prefix)
        except ScriptError:
            raise OpsiZoneInvalid(f'Unknown zone name: {name}')

        return DataOpsiZone(
            zone=zone.en,
            zone_type=types,
            zone_id=zone.zone_id,
            hazard_level=zone.hazard_level,
        )

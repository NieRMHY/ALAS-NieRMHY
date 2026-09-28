from dataclasses import dataclass

from module.ocr.ocr import Ocr
from module.secretary.ocr import SecretaryDigit, SecretaryFavorabilityDigit
from module.secretary.assets import (
    SECRETARY_NAME,
    SECRETARY_LEVEL,
    SECRETARY_FAVORABILITY,
)


@dataclass
class SecretaryInfo:
    """秘书舰信息数据类。

    Attributes:
        name (str): 舰船名称。
        level (int): 舰船等级。
        favorability (int): 舰船好感度。
    """
    name: str
    level: int
    favorability: int


OCR_SECRETARY_NAME = Ocr(
    [SECRETARY_NAME],
    lang="ppocr_v6",
    name="SECRETARY_NAME",
)

OCR_SECRETARY_LEVEL = SecretaryDigit(
    [SECRETARY_LEVEL],
    lang="ppocr_v6",
    name="SECRETARY_LEVEL",
)

OCR_SECRETARY_FAVORABILITY = SecretaryFavorabilityDigit(
    [SECRETARY_FAVORABILITY],
    name="SECRETARY_FAVORABILITY",
)


class SecretaryScanner:
    """单个秘书舰信息扫描器。"""

    def scan(self, image):
        """扫描当前界面的秘书舰名称、等级与好感度。

        Args:
            image (np.ndarray): 当前游戏截图。

        Returns:
            SecretaryInfo: 识别出的秘书舰信息。
        """
        name = OCR_SECRETARY_NAME.ocr(image)

        level = OCR_SECRETARY_LEVEL.ocr(image)

        favorability = OCR_SECRETARY_FAVORABILITY.ocr(image)

        return SecretaryInfo(
            name=name,
            level=level,
            favorability=favorability,
        )
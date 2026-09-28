from dataclasses import dataclass
from module.ocr.ocr import Ocr
from module.secretary.ocr import SecretaryDigit, SecretaryFavorabilityDigit
from module.secretary.assets import (
    SECRETARY_NAME,
    SECRETARY_LEVEL,
    SECRETARY_FAVORABILITY,
)
from module.secretary.slot import (
    SECRETARY_SLOT,
    SECRETARY_SLOT_OFFSET,
    move_button
)

@dataclass
class SecretaryGroupInfo:
    """秘书舰槽位分组信息数据类。

    Attributes:
        index (int): 槽位索引（0-4）。
        name (str): 舰船名称。
        level (int): 舰船等级。
        favorability (int): 舰船好感度。
        button (object): 槽位对应按钮。
        is_main (bool): 是否为主秘书舰（索引为 0）。
    """
    index: int
    name: str
    level: int
    favorability: int
    button: object
    is_main: bool


class SecretaryGroupScanner:
    """秘书舰组扫描器，用于识别 5 个秘书舰槽位的舰船信息。"""

    def __init__(self):
        """初始化 5 个槽位的名称、等级和好感度 OCR 识别器。"""
        self.name_ocr = []
        self.level_ocr = []
        self.favorability_ocr = []

        for index in range(5):

            offset_x, offset_y = SECRETARY_SLOT_OFFSET[index]

            name_btn = move_button(
                SECRETARY_NAME,
                offset_x,
                offset_y,
            )

            level_btn = move_button(
                SECRETARY_LEVEL,
                offset_x,
                offset_y,
            )

            favor_btn = move_button(
                SECRETARY_FAVORABILITY,
                offset_x,
                offset_y,
            )

            self.name_ocr.append(
                Ocr(
                    name_btn,
                    lang="ppocr_v6",
                    name=f"SECRETARY_NAME_{index}",
                )
            )

            self.level_ocr.append(
                SecretaryDigit(
                    level_btn,
                    lang="ppocr_v6",
                    name=f"SECRETARY_LEVEL_{index}",
                )
            )

            self.favorability_ocr.append(
                SecretaryFavorabilityDigit(
                    favor_btn,
                    name=f"SECRETARY_FAVORABILITY_{index}",
                )
            )

    def scan(self, image):
        """扫描当前界面的 5 个秘书舰槽位并解析出信息。

        Args:
            image (np.ndarray): 当前游戏截图。

        Returns:
            list[SecretaryGroupInfo]: 包含 5 个槽位信息的列表。
        """
        ships = []

        for index in range(5):
            name = self.name_ocr[index].ocr(image)
            level = self.level_ocr[index].ocr(image)
            favorability = self.favorability_ocr[index].ocr(image)

            try:
                level = int(level)
            except (ValueError, TypeError):
                level = 0

            try:
                favorability = int(favorability)
            except (ValueError, TypeError):
                favorability = 0
            ships.append(
                SecretaryGroupInfo(
                    index=index,
                    name=name,
                    level=level,
                    favorability=favorability,
                    button=SECRETARY_SLOT[index],
                    is_main=index == 0,
                )
            )

        return ships

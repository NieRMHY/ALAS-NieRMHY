"""舰船经验识别模块。

通过 OCR 识别舰船的等级和经验值，用于大世界中的经验监控。

ShipLevel: 识别舰船等级（1-125），超出范围时返回 0。
ShipExp: 识别舰船经验值，格式为 "当前经验/升级所需经验"。

OCR 修正规则：
- I -> 1, D -> 0, S -> 5, B -> 8（常见 OCR 误识别）

继承自 Digit/Ocr，复用 OCR 基础设施。
"""

import re

from module.awaken.assets import OCR_SHIP_LEVEL, OCR_SHIP_EXP
from module.base.timer import Timer
from module.logger import logger
from module.ocr.ocr import Ocr, Digit


class ShipLevel(Digit):
    """舰船等级 OCR 识别器。

    识别舰船等级，范围为 1-125。
    """

    def after_process(self, result):
        """后处理校验舰船等级数值。

        Args:
            result (str): 识别结果字符串。

        Returns:
            int: 校验后的等级数值，超出 1-125 时返回 0。
        """
        result = super().after_process(result)
        if result < 1 or result > 125:
            logger.warning('[大世界-经验] 意外的舰船等级')
            result = 0
        return result


class ShipExp(Ocr):
    """舰船经验值 OCR 识别器。

    识别舰船经验值，格式为 "当前/所需"。
    """

    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=64, alphabet='0123456789IDSBM/',
                 name=None):
        """初始化经验值识别器。

        Args:
            buttons: 识别区域。
            lang (str): 语言模型标识。
            letter (tuple[int, int, int]): 字符目标颜色 RGB 值。
            threshold (int): 颜色二值化阈值。
            alphabet (str): 字符白名单。
            name (str | None): 识别器标识名称。
        """
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet, name=name)

    def after_process(self, result):
        """修正易混淆字符。

        Args:
            result (str): 原始识别字符串。

        Returns:
            str: 修正后的字符串。
        """
        result = super().after_process(result)
        result = result.replace('I', '1').replace('D', '0').replace('S', '5')
        result = result.replace('B', '8')
        return result

    def ocr(self, image, direct_ocr=False):
        """识别经验文本，形如 `100000/205000` 或 `3000000/Max`。

        Args:
            image (np.ndarray): 输入图像。
            direct_ocr (bool): 是否跳过区域裁剪直接识别。默认 False。

        Returns:
            int: 当前经验值数值，解析失败返回 0。
        """
        result_list = super().ocr(image, direct_ocr=direct_ocr)
        result = result_list[0] if isinstance(result_list, list) else result_list

        result = re.search(r'(\d+)/', result)
        if result:
            result = [int(s) for s in result.groups()]
            current = int(result[0])
            return current
        else:
            logger.warning(f'[大世界-经验] 意外的OCR结果: {result_list}')
            return 0

def ship_info_get_level_exp(main, skip_first_screenshot=True):
    """从舰船详情截图中识别舰船等级与当前经验值。

    Args:
        main: 宿主操作模块对象。
        skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

    Returns:
        tuple[int, int]: (舰船等级, 当前经验值)。
    """
    ocr_exp = ShipExp(OCR_SHIP_EXP, name='ShipExp')
    ocr_level = ShipLevel(OCR_SHIP_LEVEL, name='ShipLevel')
    timeout = Timer(2, count=4).start()
    level = 0
    exp = 0
    while 1:
        if skip_first_screenshot:
            skip_first_screenshot = False
        else:
            main.device.screenshot()
        
        level = ocr_level.ocr(main.device.image)
        exp = ocr_exp.ocr(main.device.image)
        
        if timeout.reached():
            logger.warning('ship_info_get_level_exp timeout')
            return level, exp
        if level > 0:
            if exp > 0:
                return level, exp
            else:
                continue

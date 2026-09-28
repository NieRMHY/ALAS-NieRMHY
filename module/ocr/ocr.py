"""OCR 文字识别模块。提供 Ocr、Digit、DigitCounter、Duration 等识别器类，
支持多种 OCR 后端（ONNX/NCNN/远程服务器），用于识别游戏中的文字和数字。"""

import time
from datetime import timedelta
from typing import TYPE_CHECKING

import module.config.server as server
from module.base.button import Button
from module.base.decorator import cached_property
from module.base.utils import *
from module.logger import logger
from module.ocr.rpc import ModelProxyFactory
from module.runtime.setting import State

if TYPE_CHECKING:
    from module.ocr.al_ocr import AlOcr

if not State.deploy_config.UseOcrServer:
    from module.ocr.models import OCR_MODEL
else:
    OCR_MODEL = ModelProxyFactory()


class Ocr:
    """通用 OCR 识别器基类。

    提供基于图像裁剪、颜色通道提取、字符白名单过滤的统一文字识别流程。

    Attributes:
        name (str): 识别器标识名称。
        letter (tuple[int, int, int]): 字符目标颜色 RGB 值。
        threshold (int): 颜色提取容差二值化阈值。
        alphabet (str | None): 字符过滤白名单。
        lang (str): 语言模型标识。
    """

    SHOW_LOG = True
    SHOW_REVISE_WARNING = False

    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet=None, name=None):
        """初始化 OCR 识别器。

        Args:
            buttons (Button | tuple | list): OCR 区域，支持 Button、坐标元组、Button 列表或坐标元组列表。
            lang (str): 语言模型标识，如 'azur_lane'、'ppocr_v6'、'cnocr'、'jp'、'tw'。
            letter (tuple[int, int, int]): 字符目标 RGB 颜色元组。
            threshold (int): 字符颜色二值化阈值。
            alphabet (str | None): 字符过滤白名单。
            name (str | None): 识别器名称。
        """
        self.name = str(buttons) if isinstance(buttons, Button) else name
        self._buttons = buttons
        self.letter = letter
        self.threshold = threshold
        self.alphabet = alphabet
        self.lang = lang
        if lang == 'azur_lane' and server.server in ['jp']:
            self.lang = 'azur_lane_' + server.server

    @property
    def cnocr(self) -> "AlOcr":
        """获取底层 OCR 识别模型实例。

        Returns:
            AlOcr: 识别模型实例。
        """
        return OCR_MODEL.__getattribute__(self.lang)

    @property
    def buttons(self):
        """获取识别区域列表。

        Returns:
            list[tuple[int, int, int, int]]: 矩形区域坐标列表。
        """
        buttons = self._buttons
        buttons = buttons if isinstance(buttons, list) else [buttons]
        buttons = [button.area if isinstance(button, Button) else button for button in buttons]
        return buttons

    @buttons.setter
    def buttons(self, value):
        """设置识别区域。

        Args:
            value: Button、坐标元组或其列表。
        """
        self._buttons = value

    def pre_process(self, image):
        """图像预处理，提取指定字符颜色通道。

        Args:
            image (np.ndarray): 输入图像，形状为 (height, width, channel)。

        Returns:
            np.ndarray: 处理后的二值化灰度图像。
        """
        image = extract_letters(image, letter=self.letter, threshold=self.threshold)

        return image.astype(np.uint8)

    def after_process(self, result):
        """OCR 识别结果后处理。

        Args:
            result (str): OCR 识别出的原始字符串。

        Returns:
            str: 修正或清洗后的结果字符串。
        """
        return result

    def ocr(self, image, direct_ocr=False):
        """执行 OCR 文字识别。

        Args:
            image: 输入图像（ndarray）或图像列表。
            direct_ocr (bool): 为 True 时跳过区域裁剪，直接对整图预处理。默认 False。

        Returns:
            str | list[str]: 识别结果文本或文本列表。
        """
        start_time = time.time()

        if direct_ocr:
            image_list = [self.pre_process(i) for i in image]
        else:
            image_list = [self.pre_process(crop(image, area)) for area in self.buttons]
        
        image_list = [crop_to_text(i) for i in image_list]

        # 调试用：显示送入 OCR 模型的图像
        # self.cnocr.debug(image_list)

        result_list = self.cnocr.atomic_ocr_for_single_lines(image_list, self.alphabet)
        result_list = [''.join(result) for result in result_list]
        result_list = [self.after_process(result) for result in result_list]

        if len(self.buttons) == 1:
            result_list = result_list[0]
        if self.SHOW_LOG:
            logger.attr(name='%s %ss' % (self.name, float2str(time.time() - start_time)),
                        text=str(result_list))

        return result_list


class OcrYuv(Ocr):
    """在 YUV 色彩空间的 Y 通道中执行 OCR 识别。"""

    @cached_property
    def letter_y(self):
        """计算目标字符颜色在 YUV 空间的亮度 Y 分量。

        Returns:
            int: 亮度分量值。
        """
        arr = np.array([[self.letter]], dtype=np.uint8)
        y = rgb2luma(arr)[0][0]
        return y

    def pre_process(self, image):
        """在 YUV 色彩空间中预处理图像，提取 Y 通道差异。

        Args:
            image (np.ndarray): 输入图像，形状为 (height, width, channel)。

        Returns:
            np.ndarray: Y 通道差异图像。
        """
        y = rgb2luma(image)
        letter_y = (np.ones(y.shape) * self.letter_y).astype(np.uint8)
        diff = cv2.absdiff(y, letter_y)
        diff = cv2.multiply(diff, 255.0 / self.threshold)
        return diff


class Digit(Ocr):
    """数字 OCR 识别器，识别如 `45` 这样的纯数字。

    ocr() 方法返回 int 或 int 列表。
    """

    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet='0123456789IDSB',
                 name=None):
        """初始化数字识别器。

        Args:
            buttons: 识别区域。
            lang (str): 语言模型标识。
            letter (tuple[int, int, int]): 字符目标 RGB 颜色元组。
            threshold (int): 颜色二值化阈值。
            alphabet (str): 候选数字及常见易混淆字母白名单。
            name (str | None): 识别器名称。
        """
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet, name=name)

    def after_process(self, result):
        """将易混淆字符替换修正并转换为整数。

        Args:
            result (str): 原始识别字符串。

        Returns:
            int: 转换后的整数结果，为空或解析失败时返回 0。
        """
        result = super().after_process(result)
        result = result.replace('I', '1').replace('D', '0').replace('S', '5')
        result = result.replace('B', '8')

        prev = result
        result = int(result) if result else 0
        if self.SHOW_REVISE_WARNING:
            if str(result) != prev:
                logger.warning(f'[OCR] {self.name}: 结果 "{prev}" 修正为 "{result}"')

        return result


class DigitYuv(Digit, OcrYuv):
    """基于 YUV 色彩空间亮度通道的数字 OCR 识别器。"""
    pass


class DigitCounter(Ocr):
    """计数器格式数字 OCR 识别器，识别如 `14/15` 格式。"""

    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet='0123456789/IDSB',
                 name=None):
        """初始化计数器数字识别器。

        Args:
            buttons: 识别区域。
            lang (str): 语言模型标识。
            letter (tuple[int, int, int]): 字符目标 RGB 颜色元组。
            threshold (int): 颜色二值化阈值。
            alphabet (str): 包含斜杠的候选字符白名单。
            name (str | None): 识别器名称。
        """
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet, name=name)

    def after_process(self, result):
        """修正易混淆字符。

        Args:
            result (str): 原始识别字符串。

        Returns:
            str: 修正后的字符文本。
        """
        result = super().after_process(result)
        result = result.replace('I', '1').replace('D', '0').replace('S', '5')
        result = result.replace('B', '8')
        return result

    def ocr(self, image, direct_ocr=False):
        """识别计数器格式的数字，如 `14/15`，返回当前值、剩余值和总数。

        注意：DigitCounter 仅支持对单个按钮区域执行 OCR。

        Args:
            image: 输入图像。
            direct_ocr (bool): 为 True 时跳过区域裁剪，直接对整图预处理。

        Returns:
            tuple[int, int, int]: 三元组 (current, remain, total)，分别为当前值、剩余值和总数。
        """
        result_list = super().ocr(image, direct_ocr=direct_ocr)
        result = result_list[0] if isinstance(result_list, list) else result_list

        result = re.search(r'(\d+)/(\d+)', result)
        if result:
            result = [int(s) for s in result.groups()]
            current, total = int(result[0]), int(result[1])
            current = min(current, total)
            return current, total - current, total
        else:
            logger.warning(f'[OCR] 意外的OCR结果: {result_list}')
            return 0, 0, 0


class DigitCounterYuv(DigitCounter, OcrYuv):
    """基于 YUV 色彩空间亮度通道的计数器数字 OCR 识别器。"""
    pass


class Duration(Ocr):
    """时长 OCR 识别器，识别如 `01:30:00` 格式的时间文本。"""

    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet='0123456789:IDSB',
                 name=None):
        """初始化时长识别器。

        Args:
            buttons: 识别区域。
            lang (str): 语言模型标识。
            letter (tuple[int, int, int]): 字符目标 RGB 颜色元组。
            threshold (int): 颜色二值化阈值。
            alphabet (str): 包含冒号的候选字符白名单。
            name (str | None): 识别器名称。
        """
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet, name=name)

    def after_process(self, result):
        """修正易混淆字符。

        Args:
            result (str): 原始识别字符串。

        Returns:
            str: 修正后的字符文本。
        """
        result = super().after_process(result)
        result = result.replace('I', '1').replace('D', '0').replace('S', '5')
        result = result.replace('B', '8')
        return result

    def ocr(self, image, direct_ocr=False):
        """识别时长格式的文本，如 `01:30:00`。

        Args:
            image: 输入图像。
            direct_ocr (bool): 为 True 时跳过区域裁剪，直接对整图预处理。

        Returns:
            timedelta | list[timedelta]: timedelta 对象或 timedelta 列表。
        """
        result_list = super().ocr(image, direct_ocr=direct_ocr)
        if not isinstance(result_list, list):
            result_list = [result_list]
        result_list = [self.parse_time(result) for result in result_list]
        if len(self.buttons) == 1:
            result_list = result_list[0]
        return result_list

    @staticmethod
    def parse_time(string):
        """解析时长字符串为 timedelta 对象。

        Args:
            string (str): 时长字符串，如 `01:30:00`。

        Returns:
            timedelta: 解析后的 timedelta 对象，解析失败时返回 0 时长。
        """
        result = re.search(r'(\d{1,2}):?(\d{2}):?(\d{2})', string)
        if result:
            result = [int(s) for s in result.groups()]
            return timedelta(hours=result[0], minutes=result[1], seconds=result[2])
        else:
            logger.warning(f'[OCR] 无效的时长: {string}')
            return timedelta(hours=0, minutes=0, seconds=0)


class DurationYuv(Duration, OcrYuv):
    """基于 YUV 色彩空间亮度通道的时长 OCR 识别器。"""
    pass

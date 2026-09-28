"""
截图识别基类。

提供 ImageBase 基类用于单张截图的检测分析。包含服务器分类、
按钮缓存和通用图像处理方法，是所有截图识别器的父类。
"""

import typing as t

import numpy as np

from module.base.button import Button
from module.base.utils import color_similarity_2d, crop
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_3, GET_ITEMS_3_CHECK
from module.base.template import Template
from module.exception import ScriptError

# 缓存按钮按服务器拆分后的映射
# 键: 原始 Button 对象
# 值: dict
#     键: str, 服务器名称 ('cn', 'en', 'jp', 'tw')
#     值: 对应服务器的 Button 对象
CLASSIFY_CACHE: t.Dict[Button, t.Dict[str, Button]] = {}


class ImageBase:
    """单张截图分析基类。

    提供通用的服务器分类、颜色统计与结算行数识别能力。
    """

    # 当前识别出的服务器 ('cn', 'en', 'jp', 'tw')，未识别时为空字符串
    # 在首次调用 classify_server() 成功匹配后记录
    server: str = ''

    def classify_server(self, button, image, offset=(20, 20), scaling=1.0, threshold=0.85):
        """检测指定按钮在截图中出现并获取其所属服务器。

        Args:
            button (Button | Template): 待匹配的按钮或模板对象。
            image (np.ndarray): 待检测的截图。
            offset (tuple[int, int]): Button 匹配允许的偏移量，默认为 (20, 20)。
            scaling (float): Template 匹配缩放比例，默认为 1.0。
            threshold (float): 相似度匹配阈值，默认为 0.85。

        Returns:
            str: 匹配到的服务器标识 ('cn', 'en', 'jp', 'tw')，未匹配则返回空字符串。

        Raises:
            ScriptError: 传入了不支持的按钮对象类型。
        """
        if button not in CLASSIFY_CACHE:
            CLASSIFY_CACHE[button] = button.split_server()

        for server, server_button in CLASSIFY_CACHE[button].items():
            if isinstance(server_button, Button):
                if server_button.match(image, offset=offset, similarity=threshold):
                    if not self.server:
                        self.server = server
                    return server
            elif isinstance(server_button, Template):
                if server_button.match(image, scaling=scaling, similarity=threshold):
                    if not self.server:
                        self.server = server
                    return server
            else:
                raise ScriptError(f'classify_server() gets unknown button: {button}')

        # 未匹配
        if not self.server:
            self.server = ''
        return ''

    def clear_cache(self):
        """清空缓存的服务器识别状态，在加载新截图时调用。"""
        self.server = ''

    def image_color_count(self, image, button, color, threshold=221, count=50):
        """统计指定区域内接近目标颜色的像素点数是否达到阈值。

        Args:
            image (np.ndarray): 待检测图像。
            button (Button | tuple[int, int, int, int]): Button 对象或坐标区域 (x1, y1, x2, y2)。
            color (tuple[int, int, int]): 目标 RGB 颜色。
            threshold (int): 颜色相似度阈值（255 表示完全相同，默认 221）。
            count (int): 满足条件的像素数量阈值，默认 50。

        Returns:
            bool: 匹配像素数是否大于指定阈值。
        """
        if isinstance(button, Button):
            image = crop(image, button.area)
        else:
            image = crop(image, button)
        mask = color_similarity_2d(image, color=color) > threshold
        return np.sum(mask) > count

    def get_items_count(self, image):
        """判断获得物品弹窗的行数（1 至 3 行）。

        Args:
            image (np.ndarray): 包含获得物资或道具弹窗的截图。

        Returns:
            int: 获得的物品行数（1 到 3），若非获得物品弹窗则返回 0。
        """
        if self.classify_server(GET_ITEMS_3, image, offset=(5, 5)):
            if self.image_color_count(image, GET_ITEMS_3_CHECK, color=(255, 255, 255), threshold=221, count=100):
                return 3
            else:
                return 2
        if self.classify_server(GET_ITEMS_1, image, offset=(5, 5)):
            return 1
        return 0

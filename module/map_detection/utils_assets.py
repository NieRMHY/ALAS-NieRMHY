"""地图检测资源加载模块。预加载地图检测所需的蒙版图像和模板资源，
包括 UI 蒙版、网格中心/角落模板等。"""

import cv2
import numpy as np

from module.base.decorator import cached_property
from module.base.mask import Mask
from module.base.utils import crop

UI_MASK = Mask(file='./assets/mask/MASK_MAP_UI.png')
UI_MASK_OS = Mask(file='./assets/mask/MASK_OS_MAP_UI.png')
TILE_CENTER = Mask(file='./assets/map_detection/TILE_CENTER.png')
TILE_CORNER = Mask(file='./assets/map_detection/TILE_CORNER.png')
DETECTING_AREA = (123, 55, 1280, 720)


class Assets:
    """地图检测资源容器类。

    提供蒙版、地块中心与角点模板图像的惰性加载与缓存。
    """
    @cached_property
    def ui_mask(self):
        """主线地图 UI 蒙版图像。"""
        return UI_MASK.image

    @cached_property
    def ui_mask_os(self):
        """大世界地图 UI 蒙版图像。"""
        return UI_MASK_OS.image

    @cached_property
    def ui_mask_stroke(self):
        """经腐蚀后的 UI 蒙版边缘描边图像。"""
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        image = cv2.erode(self.ui_mask, kernel).astype('uint8')
        return image

    @cached_property
    def ui_mask_in_map(self):
        """地图检测区域对齐后的主线 UI 蒙版图像。"""
        area = np.append(np.subtract(0, DETECTING_AREA[:2]), self.ui_mask.shape[::-1])
        # area = (-123, -55, 1157, 665)
        return crop(self.ui_mask, area)

    @cached_property
    def ui_mask_os_in_map(self):
        """地图检测区域对齐后的大世界 UI 蒙版图像。"""
        area = np.append(np.subtract(0, DETECTING_AREA[:2]), self.ui_mask.shape[::-1])
        # area = (-123, -55, 1157, 665)
        return crop(self.ui_mask_os, area)

    @cached_property
    def tile_center_image(self):
        """网格中心特征模板图像。"""
        return TILE_CENTER.image

    @cached_property
    def tile_corner_image(self):
        """网格角点特征模板图像。"""
        return TILE_CORNER.image

    @cached_property
    def tile_corner_image_list(self):
        """四个方向的网格角点模板列表 [左上, 右上, 左下, 右下]。"""
        return [cv2.flip(self.tile_corner_image, -1),
                cv2.flip(self.tile_corner_image, 0),
                cv2.flip(self.tile_corner_image, 1),
                self.tile_corner_image]


ASSETS = Assets()

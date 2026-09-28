"""统计工具函数。

提供模板图像加载、物品网格（ItemGrid）管理和图像匹配等基础功能，
为掉落统计模块提供底层图像处理支持。
"""

import os

import cv2
import numpy as np

from module.base.utils import crop, image_size


class ImageError(Exception):
    """解析图像时的通用异常。"""
    pass


class ImageInvalidResolution(ImageError):
    """图像分辨率异常（非 1280x720 基准尺寸）。"""
    pass


def load_folder(folder, ext='.png'):
    """加载文件夹下的模板图像映射表。

    Args:
        folder (str): 包含模板图像的文件夹路径。
            图像规范：通常为 96x96 尺寸、3 通道 PNG。
            文件命名：大驼峰命名（如 'PlateGeneralT3'），下划线后缀会被视作同一物品的不同变体（如 'Javelin' 与 'Javelin_2'）。
        ext (str | list[str]): 匹配的文件扩展名。默认为 '.png'。

    Returns:
        dict[str, str]: 键为不带扩展名的文件名，值为完整文件路径。
    """
    if not os.path.exists(folder):
        return {}

    out = {}
    for file in os.listdir(folder):
        name, extension = os.path.splitext(file)
        if (isinstance(ext, str) and extension == ext) \
                or (isinstance(ext, list) and extension in ext):
            out[name] = os.path.join(folder, file)

    return out


def pack(img_list):
    """将多个截图垂直拼接（竖向堆叠）成单张长图。

    Args:
        img_list (list[np.ndarray]): 待拼接的图像列表。

    Returns:
        np.ndarray: 垂直拼接后的图像。
    """
    image = cv2.vconcat(img_list)
    return image


def unpack(image):
    """将垂直拼接的长图按 720 高度还原为单张 1280x720 截图列表。

    Args:
        image (np.ndarray): 垂直拼接后的长图或单张截图。

    Returns:
        list[np.ndarray]: 拆分后的 1280x720 图像列表。

    Raises:
        ImageInvalidResolution: 图像宽度不是 1280 或高度不是 720 的整数倍。
    """
    size = image_size(image)
    if size == (1280, 720):
        return [image]
    else:
        if size[0] != 1280 or size[1] % 720 != 0:
            raise ImageInvalidResolution(f'Unexpected image size: {size}')
        return [crop(image, (0, n * 720, 1280, (n + 1) * 720)) for n in range(size[1] // 720)]

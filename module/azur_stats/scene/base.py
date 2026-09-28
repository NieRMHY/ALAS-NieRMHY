"""
截图场景分析基类。

提供 SceneBase 基类，将截图文件加载、随机 ID 生成和批量处理
抽象为统一接口。是所有场景级截图分析器的父类。
"""

import os
import random
import typing as t

import numpy as np
from tqdm import tqdm

from module.azur_stats.image.base import ImageBase
from module.base.decorator import cached_property
from module.base.resource import del_cached_property
from module.base.utils import load_image
from module.config.utils import iter_folder
from module.statistics.utils import unpack, ImageError


def random_imgid():
    """生成 16 位的十六进制随机图片标识 ID。

    Returns:
        str: 随机图像 ID 字符串。
    """
    return ''.join(random.sample('0123456789abcdef', 16))


class SceneBase(ImageBase):
    """场景分析基类。

    封装掉落记录的多图序列加载、图片属性访问与批量处理逻辑。
    """

    # load_file() 的原始输入
    file = None
    # 掉落记录图像序列
    images: t.List[np.ndarray] = []

    def load_file(self, file):
        """加载图片文件、图像数组或图像列表。

        Args:
            file (str | list[np.ndarray] | np.ndarray): 文件路径或图像数据。

        Raises:
            ImageError: 无法解析或不支持的图像文件格式。
        """
        self.file = file
        self.clear_cache()

        if isinstance(file, str):
            self.images = unpack(load_image(file))
        elif isinstance(file, list):
            self.images = file
        elif isinstance(file, np.ndarray):
            self.images = unpack(file)
        else:
            raise ImageError(f'Unknown image file: {file}')

    def clear_cache(self):
        """清空缓存的属性与计算结果。"""
        super().clear_cache()
        del_cached_property(self, 'first')
        del_cached_property(self, 'followings')
        del_cached_property(self, 'last')
        del_cached_property(self, 'imgid')

    def parse_scene(self):
        """解析场景中的掉落数据。

        子类应重写此方法以实现具体场景的解析逻辑。

        Returns:
            list: 解析出的掉落或场景数据列表。
        """
        return []

    def extract_assets(self):
        """提取未知物品的新模板素材。

        包含掉落物体的场景类可重写此方法。
        """
        return

    @cached_property
    def first(self) -> np.ndarray:
        """获取掉落记录序列的第一张截图。

        Returns:
            np.ndarray: 首张截图。
        """
        return self.images[0]

    @cached_property
    def followings(self) -> t.List[np.ndarray]:
        """获取掉落记录序列中除第一张外的后续截图列表。

        Returns:
            list[np.ndarray]: 后续截图列表。
        """
        return self.images[1:]

    @cached_property
    def last(self) -> np.ndarray:
        """获取掉落记录序列的最后一张截图。

        Returns:
            np.ndarray: 末张截图。
        """
        return self.images[-1]

    @cached_property
    def imgid(self) -> str:
        """获取当前图片的唯一标识 ID。

        Returns:
            str: 来自文件名的 ID 或生成的随机 ID。
        """
        if isinstance(self.file, str):
            return os.path.splitext(os.path.basename(self.file))[0]
        else:
            return random_imgid()

    def apply_to_folder(self, folder, method):
        """对指定目录下的所有 PNG 截图执行给定的处理方法。

        Args:
            folder (str): 图像文件目录路径。
            method (callable): 对每个加载图像调用的无参可调用对象。
        """
        files = list(iter_folder(folder, ext='.png'))
        for file in tqdm(files):
            self.load_file(file)
            method()

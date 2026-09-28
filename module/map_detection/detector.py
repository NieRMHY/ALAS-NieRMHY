"""地图检测器封装模块。提供 MapDetector 类作为地图检测的统一入口，
整合单应性变换（Homography）和透视检测（Perspective）两种后端。"""

import numpy as np

from module.config.config import AzurLaneConfig
from module.map_detection.homography import Homography
from module.map_detection.perspective import Perspective


class MapDetector:
    """地图检测器封装类。

    统一封装单应性变换（Homography）与透视检测（Perspective）后端，
    提供地图网格识别与边缘状态维护。

    Attributes:
        image (np.ndarray): 当前输入的地图截图。
        config (AzurLaneConfig): 配置对象。
        left_edge (bool): 视野是否已到达地图左边缘。
        right_edge (bool): 视野是否已到达地图右边缘。
        lower_edge (bool): 视野是否已到达地图下边缘。
        upper_edge (bool): 视野是否已到达地图上边缘。
        generate (callable): 后端网格生成函数。
    """
    image: np.ndarray
    config: AzurLaneConfig

    left_edge: bool
    right_edge: bool
    lower_edge: bool
    upper_edge: bool

    generate: callable

    def __init__(self, config):
        """初始化地图检测器。

        Args:
            config (AzurLaneConfig): 配置对象。
        """
        self.config = config
        self.backend = None
        self.detector_set_backend()

    def detector_set_backend(self, name=''):
        """设置地图检测后端。

        Args:
            name (str, optional): 后端名称，'homography' 或 'perspective'。
                为空时读取配置中的 DETECTION_BACKEND。默认为 ''。
        """
        if not name:
            name = self.config.DETECTION_BACKEND

        if name == 'homography':
            self.backend = Homography(config=self.config)
        else:
            self.backend = Perspective(config=self.config)

    def load(self, image):
        """加载地图图像并执行后端检测。

        更新边缘状态与网格生成函数。

        Args:
            image (np.ndarray): 形状为 (720, 1280, 3) 的地图截图。
        """
        self.backend.load(image)

        self.left_edge = bool(self.backend.left_edge)
        self.right_edge = bool(self.backend.right_edge)
        self.lower_edge = bool(self.backend.lower_edge)
        self.upper_edge = bool(self.backend.upper_edge)
        self.generate = self.backend.generate

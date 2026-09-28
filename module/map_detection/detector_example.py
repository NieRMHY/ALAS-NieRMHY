"""地图检测后端示例模块。展示如何实现自定义地图检测后端，
定义 load/detect/set_backend 等接口供 MapDetector 调用。"""

import numpy as np

from module.config.config import AzurLaneConfig


class DetectionBackendExample:
    """地图检测后端参考示例类。

    展示自定义地图检测后端所需实现的接口与属性规范。

    Attributes:
        image (np.ndarray): 输入的地图图像。
        config (AzurLaneConfig): 配置对象。
        left_edge (bool): 左边缘状态标志。
        right_edge (bool): 右边缘状态标志。
        lower_edge (bool): 下边缘状态标志。
        upper_edge (bool): 上边缘状态标志。
    """

    def __init__(self, config):
        """初始化检测后端。

        Args:
            config (AzurLaneConfig): 配置对象。
        """
        self.config = config

    # 输入接口
    def load(self, image):
        """加载地图图像并执行检测。

        Args:
            image (np.ndarray): 形状为 (720, 1280, 3) 的地图截图。
        """
        self.image = image
        pass  # 在此处执行地图检测逻辑。

    # 输出属性与方法
    image: np.ndarray
    config: AzurLaneConfig
    # 四条边缘的布尔状态（或具备 __bool__ 属性的对象）
    left_edge: bool
    right_edge: bool
    lower_edge: bool
    upper_edge: bool

    # 生成网格坐标与顶点的方法
    def generate(self):
        """生成视野中各网格的坐标及四个角点坐标。

        Yields:
            tuple[tuple[int, int], list[tuple[int, int]]]:
                包含网格相对坐标与四角点序列的元组 ((x, y), [左上, 右上, 左下, 右下])。
        """
        for x in range(8):
            for y in range(5):
                yield (x, y), [(0, 0), (100, 0), (0, 100), (100, 100)]

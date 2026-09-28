"""地图网格单元模块。定义 Grid 类，组合 GridInfo（网格属性）和 GridPredictor（网格预测），
表示地图中的单个网格及其几何信息。"""

from module.base.decorator import cached_property
from module.map_detection.grid_info import GridInfo
from module.map_detection.grid_predictor import GridPredictor
from module.map_detection.utils import trapezoid2area


class Grid(GridInfo, GridPredictor):
    """地图网格单元类。

    组合网格基础信息与图像预测能力，表示视野中的单个网格。
    包含网格在屏幕上的梯形几何区域及对应的内接/外切矩形。

    Attributes:
        location (tuple[int, int]): 网格相对坐标 (x, y)。
    """

    def __init__(self, location, image, corner, config):
        """初始化地图网格单元。

        Args:
            location (tuple[int, int]): 网格相对坐标 (x, y)。
            image (np.ndarray): 包含该网格的当前屏幕截图。
            corner (list[tuple[int, int]]): 网格在屏幕上的四个梯形角点坐标：
                (x0, y0)  +-------+  (x1, y1)
                         /         \
                        /           \
             (x2, y2)  +-------------+  (x3, y3)
            config (AzurLaneConfig): 配置对象。
        """
        self.location = location
        super().__init__(location, image, corner, config)

    @cached_property
    def inner(self):
        """梯形网格的最大内接矩形区域。

        Returns:
            tuple[int, int, int, int]: (左上X, 左上Y, 右下X, 右下Y)。
        """
        return trapezoid2area(self.corner, pad=5)

    @cached_property
    def outer(self):
        """梯形网格的最小外切矩形区域。

        Returns:
            tuple[int, int, int, int]: (左上X, 左上Y, 右下X, 右下Y)。
        """
        return trapezoid2area(self.corner, pad=-5)

    @cached_property
    def button(self):
        """暴露 button 属性，使 Grid 对象可直接作为点击目标。

        Returns:
            tuple[int, int, int, int]: 内接矩形区域坐标。
        """
        return self.inner

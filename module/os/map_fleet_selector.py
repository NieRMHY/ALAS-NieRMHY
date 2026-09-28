"""大世界舰队选择器模块。

管理大世界地图中的舰队选择操作。
大世界支持 4 支舰队（而非主线的 2 支），
通过下拉菜单在舰队间切换。

FleetOperator 的大世界版本，适配大世界特有的 UI 布局。
"""

from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import *
from module.logger import logger
from module.os.assets import *
from module.os_handler.assets import *
from module.os_handler.map_event import MapEventHandler


class FleetSelector:
    """大世界舰队选择器。

    管理大世界地图中的舰队切换操作。

    Attributes:
        FLEET_BAR_SHAPE_Y (int): 舰队选择条的高度像素。
        FLEET_BAR_MARGIN_Y (int): 舰队选择条的间距像素。
        FLEET_BAR_ACTIVE_STD (int): 活跃状态的标准差阈值。
        FLEET_LIST (list): 可选舰队列表（FLEET_1 到 FLEET_4）。
    """
    FLEET_BAR_SHAPE_Y = 42
    FLEET_BAR_MARGIN_Y = 11
    FLEET_BAR_ACTIVE_STD = 45  # 激活状态标准差约 67，未激活约 12
    FLEET_LIST = [FLEET_1, FLEET_2, FLEET_3, FLEET_4]

    def __init__(self, main):
        """初始化舰队选择器。

        Args:
            main (OSFleetSelector): 宿主执行模块对象。
        """
        self._choose = FLEET_CHOOSE
        self._bar = FLEET_BAR
        self.main = main

    def get(self):
        """获取当前选中的舰队编号。

        Returns:
            int: 当前舰队索引 (1-4)；未识别时返回 0。
        """
        for index, button in enumerate(self.FLEET_LIST):
            if self.main.appear(button, offset=(20, 20), similarity=0.75):
                return index + 1

        logger.info('[大世界-舰队选择] 未知的大世界舰队')
        return 0

    def bar_opened(self):
        """检查舰队选择下拉栏是否处于展开状态。

        Returns:
            bool: 展开返回 True，否则返回 False。
        """
        # 检查 3-13 列像素颜色
        area = self._bar.area
        area = (area[0] + 3, area[1], area[0] + 13, area[3])
        # 应当包含至少 2 个灰色选项和 1 个蓝色选项
        return self.main.image_color_count(area, color=(239, 243, 247), threshold=30, count=400) \
               and self.main.image_color_count(area, color=(66, 125, 231), threshold=30, count=150)

    def parse_fleet_bar(self, image):
        """解析下拉菜单图像中处于激活状态的舰队项。

        Args:
            image (np.ndarray): 下拉菜单图像。

        Returns:
            list[int]: 当前选中的舰队编号列表 (1-4)。
        """
        width, height = image_size(image)
        result = []
        for index, y in enumerate(range(0, height, self.FLEET_BAR_SHAPE_Y + self.FLEET_BAR_MARGIN_Y)):
            area = (0, y, width, y + self.FLEET_BAR_SHAPE_Y)
            mean = get_color(image, area)
            if np.std(mean, ddof=1) > self.FLEET_BAR_ACTIVE_STD:
                result.append(4 - index)

        logger.info(f'[大世界-舰队选择] 当前选择: {result}')
        return result

    def selected(self):
        """获取下拉栏当前选中的舰队列表。

        Returns:
            list[int]: 选中的舰队编号列表。
        """
        data = self.parse_fleet_bar(self.main.image_crop(self._bar, copy=False))
        return data

    def get_button(self, index, numbers=5):
        """将舰队索引转换为下拉菜单中的点击按钮对象。

        Args:
            index (int): 舰队索引 (1-4)。
            numbers (int): 选项总数偏移参考值。默认 5。

        Returns:
            Button: 对应的按钮对象。
        """
        index = numbers - index
        area = area_offset(area=(
            0,
            (self.FLEET_BAR_SHAPE_Y + self.FLEET_BAR_MARGIN_Y) * (index - 1),
            self._bar.area[2] - self._bar.area[0],
            (self.FLEET_BAR_SHAPE_Y + self.FLEET_BAR_MARGIN_Y) * (index - 1) + self.FLEET_BAR_SHAPE_Y
        ), offset=(self._bar.area[0:2]))
        area = area_pad(area, pad=3)
        index = numbers - index
        return Button(area=(), color=(), button=area, name=f'{self._bar}_INDEX_{index}')

    def open(self):
        """展开舰队选择下拉菜单。"""
        main = self.main
        click_timer = Timer(3, count=6)
        for _ in main.loop():
            if main.handle_map_event():
                click_timer.reset()
                continue

            # 结束条件
            if self.bar_opened():
                break

            # 点击展开
            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def close(self):
        """收起舰队选择下拉菜单。"""
        main = self.main
        click_timer = Timer(3, count=6)
        for _ in main.loop():
            # 结束条件
            if not self.bar_opened():
                break

            # 点击收起
            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def click(self, index):
        """在下拉菜单中点击选择目标舰队。

        Args:
            index (int): 目标舰队编号 (1-4)。
        """
        main = self.main
        button = self.get_button(index)
        click_timer = Timer(3, count=6)
        for _ in main.loop():
            if main.handle_map_event():
                click_timer.reset()
                continue

            if not self.bar_opened():
                # 结束条件
                if self.get() == index:
                    break
                # 游戏响应延迟重试展开
                elif click_timer.reached():
                    self.open()

            # 点击目标项
            if click_timer.reached():
                main.device.click(button)
                click_timer.reset()

    def ensure_to_be(self, index):
        """确保切换到指定的舰队。

        Args:
            index (int): 目标舰队编号 (1-4)。

        Returns:
            bool: 是否执行了舰队切换操作。
        """
        confirm_timer = Timer(1.5, count=5).start()
        main = self.main
        for _ in main.loop():
            if confirm_timer.reached():
                break

            if main.handle_map_event():
                confirm_timer.reset()
                continue

            current = self.get()
            if current == index:
                logger.info(f'[大世界-舰队选择] 当前已是舰队 {index}')
                return False
            elif current > 0:
                logger.info(f'[大世界-舰队选择] 切换到舰队 {index}')
                self.open()
                self.click(index)
                return True

        logger.warning('[大世界-舰队选择] 未知的大世界舰队, 使用当前舰队')
        return False

class StorageFleetSelector(FleetSelector):
    """仓库界面中的舰队选择器。

    支持 1-4 号水面舰队及 5 号潜艇舰队。
    """
    FLEET_LIST = [STORAGE_FLEET_1, STORAGE_FLEET_2, STORAGE_FLEET_3, STORAGE_FLEET_4, STORAGE_FLEET_5]
    SUBMARINE_FLEET = 5

    def __init__(self, main):
        """初始化仓库舰队选择器。

        Args:
            main (OSFleetSelector): 宿主执行模块对象。
        """
        self._choose = STORAGE_FLEET_CHOOSE
        self._bar = STORAGE_FLEET_BAR
        self.main = main

    def bar_opened(self):
        """检查仓库舰队选择下拉栏是否展开。

        Returns:
            bool: 展开返回 True，否则返回 False。
        """
        # 检查 3-13 列像素颜色
        area = self._bar.area
        area = (area[0] + 3, area[1], area[0] + 13, area[3])
        # 应当包含至少 2 个灰色选项和 1 个橙色选项
        return self.main.image_color_count(area, color=(200, 207, 231), threshold=34, count=400) \
               and self.main.image_color_count(area, color=(214, 150, 96), threshold=34, count=150)

    def get_button(self, index):
        """获取仓库下拉菜单中对应舰队的按钮。

        Args:
            index (int): 舰队索引 (1-5)。

        Returns:
            Button: 按钮对象。
        """
        return super().get_button(index, 6)


class OSFleetSelector(MapEventHandler):
    """大世界舰队选择能力混入类。"""

    @cached_property
    def fleet_selector(self):
        """地图主界面的舰队选择器。

        Returns:
            FleetSelector: 舰队选择器实例。
        """
        return FleetSelector(main=self)

    @cached_property
    def storage_fleet_selector(self):
        """仓库界面的舰队选择器。

        Returns:
            StorageFleetSelector: 仓库舰队选择器实例。
        """
        return StorageFleetSelector(main=self)

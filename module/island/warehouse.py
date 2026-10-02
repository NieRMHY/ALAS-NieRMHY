"""岛屿仓库 OCR 模块。

提供岛屿仓库物品数量的 OCR 识别功能，基于网格布局遍历仓库槽位。
通过模板匹配定位目标物品，再对数量区域进行数字 OCR 读取，返回库存数量。
"""
from module.ocr.ocr import *
from module.base.button import *
from module.ui.ui import *


class WarehouseOCR:
    """岛屿仓库物品 OCR 识别基类。

    基于网格布局遍历仓库槽位，通过模板匹配定位目标物品，
    并提取对应数字区域进行 OCR 识别，获取物品库存数量。

    Attributes:
        warehouse_grid (ButtonGrid): 仓库槽位网格布局 (6x2)。
        number_area_relative (tuple[int, int, int, int]): 槽位相对于左上角的数字区域坐标偏移。
    """

    def __init__(self, *args, **kwargs):
        """初始化仓库网格和数字区域相对坐标。

        Args:
            *args: 可变位置参数。
            **kwargs: 可变关键字参数。
        """
        self.warehouse_grid = ButtonGrid(
            origin=(301, 150),
            delta=(142, 167),
            button_shape=(104, 110),
            grid_shape=(6, 2),
            name="WAREHOUSE_GRID"
        )
        self.number_area_relative = (45, 90, 99, 110)

    def ocr_item_quantity(self, screenshot, template):
        """在仓库网格中通过模板匹配定位物品并识别其库存数量。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            template (Template): 目标物品的图标模板。

        Returns:
            int: 物品库存数量，未找到返回 0。
        """
        for _, _, button in self.warehouse_grid.generate():
            cell_image = crop(screenshot, button.area)
            if template.match(cell_image, similarity=0.85):
                number_area = self._get_number_area(button)
                ocr_button = Button(
                    area=number_area,
                    color=(),
                    button=number_area,
                    name="ITEM_NUMBER"
                )
                ocr_instance = Digit(ocr_button,letter = (255, 255, 255), threshold = 200,
                alphabet = '0123456789')
                return ocr_instance.ocr(screenshot)
        return 0

    def _get_number_area(self, button):
        """计算指定仓库槽位中物品数量的绝对屏幕区域。

        Args:
            button (Button): 仓库槽位的按钮对象。

        Returns:
            tuple[int, int, int, int]: 物品数量的绝对坐标区域 (x1, y1, x2, y2)。
        """
        x1 = button.area[0] + self.number_area_relative[0]
        y1 = button.area[1] + self.number_area_relative[1]
        x2 = button.area[0] + self.number_area_relative[2]
        y2 = button.area[1] + self.number_area_relative[3]
        return (x1, y1, x2, y2)
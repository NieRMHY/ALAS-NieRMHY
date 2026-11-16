"""岛屿仓库 OCR 模块。

提供岛屿仓库物品数量的 OCR 识别功能，基于网格布局遍历仓库槽位。
通过模板匹配定位目标物品，再对数量区域进行数字 OCR 读取，返回库存数量。
ocr_item_quantity(..., strict=True) 只返回可核验的非负整数，识别失败返回 None，
供上层区分「库存确实是 0」与「没读到」。
"""
from module.ocr.ocr import *
from module.base.button import *
from module.ui.ui import *


class WarehouseQuantityDigit(Digit):
    """仓库槽位数量识别器，保留识别原文并给出可核验的数量。

    Add by MHY, 2026-11-09：Digit 把空文本和真实 0 都转成 0，只用 last_valid 区分；
    仓库读数要区分「确实读到 0」和「没读到」，所以额外保留原文，并把可核验结果
    放到 quantity（识别失败为 None）。
    """

    def __init__(self, *args, **kwargs):
        """初始化数字识别器，并复位原文与数量状态。

        Args:
            *args: 透传给 Digit 的位置参数。
            **kwargs: 透传给 Digit 的关键字参数。
        """
        super().__init__(*args, **kwargs)
        self.raw_text = ''
        self.quantity = None

    def after_process(self, result):
        """记录原始识别文本，并把可核验的数量与 0 兜底分开。

        Args:
            result (str): OCR 识别出的原始字符串。

        Returns:
            int: 与 Digit 一致的整数结果；原文为空或非数字时仍返回 0。
        """
        self.raw_text = result
        text = result if isinstance(result, str) else ''
        try:
            value = super().after_process(text)
        except ValueError:
            # 字母等非数字文本会让 Digit 的 int() 抛错，这里按识别失败处理而不是中断扫描
            self.last_valid = False
            self.quantity = None
            return 0
        # last_valid 由 Digit 在修正 I/D/S/B 之后判定：只有原文能还原成纯数字才为真
        self.quantity = value if self.last_valid else None
        return value


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

    def ocr_item_quantity(self, screenshot, template, strict=False):
        """在仓库网格中通过模板匹配定位物品并识别其库存数量。

        Modify by MHY, 2026-11-09：默认行为保持不变（失败仍返回 0，兼容旧调用）；
        strict=True 时只返回可核验的非负整数，当前 6x2 页未命中或识别失败返回 None，
        让上层能把「未知库存」和「确实是 0」分开，不再按 0 补产。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            template (Template): 目标物品的图标模板。
            strict (bool): 是否启用严格读数。默认 False。

        Returns:
            int | None: 物品库存数量；默认模式下未找到返回 0；
                strict 模式下模板未命中、数量为空或非数字时返回 None。
        """
        for _, _, button in self.warehouse_grid.generate():
            cell_image = crop(screenshot, button.area)
            if template.match(cell_image, similarity=0.85):
                ocr_instance = self._quantity_digit(button)
                value = ocr_instance.ocr(screenshot)
                if strict:
                    return self._validated_quantity(ocr_instance.quantity)
                return value
        return None if strict else 0

    def _quantity_digit(self, button):
        """构造槽位数量识别器。

        Args:
            button (Button): 仓库槽位的按钮对象。

        Returns:
            WarehouseQuantityDigit: 对应槽位数量区域的数字识别器。
        """
        number_area = self._get_number_area(button)
        ocr_button = Button(
            area=number_area,
            color=(),
            button=number_area,
            name="ITEM_NUMBER"
        )
        return WarehouseQuantityDigit(
            ocr_button, letter=(255, 255, 255), threshold=200, alphabet='0123456789')

    @staticmethod
    def _validated_quantity(value):
        """严格读数只接受非负整数，其余一律视为未知。

        Args:
            value (int | None): WarehouseQuantityDigit.quantity 的结果。

        Returns:
            int | None: 可核验的非负整数，否则 None。
        """
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

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
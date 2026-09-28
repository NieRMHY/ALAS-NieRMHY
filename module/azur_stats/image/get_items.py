"""
获得物品截图识别。

从战斗结算画面中识别获得的物品列表，支持单排/双排布局检测，
处理物品网格定位和数量 OCR，以及信息栏遮挡的异常情况。
"""

import cv2
import numpy as np
import typing as t

from module.azur_stats.image.base import ImageBase
from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.utils import crop, rgb2gray
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_ITEMS_3
from module.handler.assets import INFO_BAR_1
from module.logger import logger
from module.statistics.assets import GET_ITEMS_ODD
from module.statistics.item import AmountOcr, Item, ItemGrid
from module.statistics.utils import ImageError

ITEM_GRIDS_1_ODD = ButtonGrid(origin=(336, 298), delta=(128, 0), button_shape=(96, 96), grid_shape=(5, 1))
ITEM_GRIDS_1_EVEN = ButtonGrid(origin=(400, 298), delta=(128, 0), button_shape=(96, 96), grid_shape=(4, 1))
ITEM_GRIDS_2 = ButtonGrid(origin=(336, 227), delta=(128, 142), button_shape=(96, 96), grid_shape=(5, 2))
ITEM_GRIDS_3 = ButtonGrid(origin=(336, 223), delta=(128, 149), button_shape=(96, 96), grid_shape=(5, 2))


class AutoSearchAmount(AmountOcr):
    """结算奖励页与获得道具页共用的数量识别。

    两页的图标缩放不同（自律寻敌 64px 放大到 96、获得道具页原生 96），但数量
    都是浅色数字压深色底，取字规则一致。

    Attributes:
        remove_fragments (bool): 开启碎片过滤，避免图标笔触被读成数字。
        fragment_max_digit_gap (int): 右侧数字簇规则：数字之间水平间隙 ≤4px，
            图标竖笔触与数字的间隙 ≥19px，据此把图标笔触排除在数字之外
            （如 2 被读成 12）。
    """

    # 数量区域先放大 2.67 倍再提取文字：数字组件高度 24~27px，图标边缘碎片 ≤8px。
    remove_fragments = True
    fragment_min_height = 15
    fragment_min_area = 30
    fragment_max_digit_gap = 10

    def pre_process(self, image):
        # 自律寻敌页 group.amount_area = (35, 51, 63, 63)，目标高度 32
        scale = 32 / 12
        #     CV_INTER_NN       =0,
        #     CV_INTER_LINEAR   =1,
        #     CV_INTER_CUBIC    =2,
        #     CV_INTER_AREA     =3,
        #     CV_INTER_LANCZOS4 =4,
        image = cv2.resize(image, (0, 0), fx=scale, fy=scale, interpolation=2)

        image = super().pre_process(image)

        return image


class GetItemsCoveredByInfoBar(ImageError):
    """获得物品截图被信息栏遮挡。"""
    pass


class GetItemsInvalid(ImageError):
    """非获得道具结算界面截图。"""
    pass


class ZeroAmountError(ImageError):
    """物品数量识别为 0。"""
    pass


class TooManyNewTemplate(ImageError):
    """单次提取的新模板数量过多。"""
    pass


def merge_get_items(item_list_1: t.Iterable[Item], item_list_2: t.Iterable[Item]):
    """合并两个物品列表并去重。

    Args:
        item_list_1 (Iterable[Item]): 第一个物品迭代器。
        item_list_2 (Iterable[Item]): 第二个物品迭代器。

    Yields:
        Item: 合并去重后的物品对象。
    """
    items = set(list(item_list_1) + list(item_list_2))
    for item in items:
        yield item


def has_odd_items(image):
    """检测单行物品排布是否为奇数个（1/3/5）。

    Args:
        image (np.ndarray): 待检测截图。

    Returns:
        bool: 单行是否存在奇数个物品。
    """
    image = crop(image, GET_ITEMS_ODD.area)
    return np.mean(rgb2gray(image) > 127) > 0.1


class GetItems(ImageBase):
    """获得物品截图识别器。

    负责战斗与任务结算弹窗中掉落物品的排布检测、网格定位与物品识别。
    """

    ITEM_TEMPLATE_FOLDER = f'./assets/stats_basic'
    # 提取新场景模板时为 True，常规运行时为 False
    ALLOW_TOO_MANY_NEW_TEMPLATE = False

    # 数量区。获得道具页的数字贴着图标右下角、右对齐，位数多时左侧会超出这个区，
    # 于是四位数被切掉首位（作战补给凭证 1638 读成 638，实测 6/9 张吃亏）；
    # 而白纸类（图纸/实验计划）的数字压在右下角的灰色齿轮上，齿轮的齿在默认区里
    # 会被读成「7」（1 读成 71）。两者都不能靠调一个通用区解决，只能按物品换区。
    ITEM_AMOUNT_AREA = (60, 71, 91, 92)
    ITEM_AMOUNT_AREA_RULES = (
        # 数字在齿轮下方，下移一档避开齿轮的齿
        ('GearDesignPlan', (60, 76, 90, 94)),
        ('OrdnanceTestingReport', (60, 76, 90, 94)),
        # 只有这一格会到四位数，且右下角没有压住数字的装饰，可以整体左扩
        ('OperationCoin', (50, 71, 92, 92)),
    )

    @cached_property
    def item_grid(self) -> ItemGrid:
        """获取物品网格识别器实例。

        Returns:
            ItemGrid: 初始化的物品网格对象。
        """
        grid = ItemGrid(None, {}, template_area=(40, 21, 89, 70), amount_area=self.ITEM_AMOUNT_AREA)
        grid.item_class = Item
        grid.similarity = 0.92
        grid.amount_area = self.ITEM_AMOUNT_AREA
        grid.amount_area_rules = list(self.ITEM_AMOUNT_AREA_RULES)
        grid.amount_ocr = AutoSearchAmount([], threshold=96, name='Amount_ocr')
        grid.load_template_folder(self.ITEM_TEMPLATE_FOLDER)
        return grid

    def is_get_items(self, image):
        """判断是否为获得物品结算弹窗界面。

        Args:
            image (np.ndarray): 待检测图像。

        Returns:
            bool: 是否为获得物品弹窗。
        """
        return bool(self.classify_server(GET_ITEMS_1, image)) or bool(self.classify_server(GET_ITEMS_2, image))

    def parse_get_items(self, image, name=True, amount=True, tag=True) -> t.Iterator[Item]:
        """解析单张获得物品截图中的所有掉落道具。

        Args:
            image (np.ndarray): 结算截图。
            name (bool): 是否识别物品名称。
            amount (bool): 是否识别物品数量。
            tag (bool): 是否识别物品标签。

        Yields:
            Item: 解析出的物品对象。

        Raises:
            ZeroAmountError: 物品数量识别为 0 时抛出。
        """
        self._get_items_load(image)

        if self.item_grid.grids is None:
            return
        else:
            self.item_grid.predict(image, name=name, amount=amount, tag=tag)
            items = self.before_revise_items(self.item_grid.items)
            for item in items:
                before = str(item)
                item = self.revise_item(item)
                after = str(item)
                if before != after:
                    logger.info(f'[统计-物品] 物品 {before} 修正为 {after}')
                if item.amount == 0:
                    raise ZeroAmountError(f'Invalid item amount: {item}')
                yield item

    def extract_item_template(self, image, folder=None):
        """从结算截图中提取未知物品的新模板。

        Args:
            image (np.ndarray): 截图图像。
            folder (str, optional): 模板保存文件夹，默认使用 ITEM_TEMPLATE_FOLDER。

        Raises:
            TooManyNewTemplate: 提取的新模板数量过多时抛出。
        """
        if folder is None:
            folder = self.ITEM_TEMPLATE_FOLDER
        self._get_items_load(image)
        if self.item_grid.grids is not None:
            new = self.item_grid.extract_template(image, folder=folder)
            new = len(new.keys())
            if not GetItems.ALLOW_TOO_MANY_NEW_TEMPLATE and new >= 2:
                raise TooManyNewTemplate(f'Extracted {new} new templates')

    def before_revise_items(self, items: t.List[Item]) -> t.List[Item]:
        """物品修正前的预处理钩子方法。

        Args:
            items (list[Item]): 原始识别出的物品列表。

        Returns:
            list[Item]: 预处理后的物品列表。
        """
        return items

    def revise_item(self, item: Item) -> Item:
        """单项物品修正钩子方法。

        Args:
            item (Item): 待修正的物品。

        Returns:
            Item: 修正后的物品。
        """
        return item

    def _get_items_load(self, image):
        """检查截图并根据服务器和排布确定物品网格。

        Args:
            image (np.ndarray): 截图图像。

        Raises:
            GetItemsCoveredByInfoBar: 截图被通知横条遮挡。
            GetItemsInvalid: 截图不是获得物品界面。
        """
        self.item_grid.grids = None
        if INFO_BAR_1.appear_on(image):
            raise GetItemsCoveredByInfoBar('get_items image has info_bar')
        elif self.classify_server(GET_ITEMS_1, image, offset=(5, 0)):
            self.item_grid.grids = ITEM_GRIDS_1_ODD if has_odd_items(image) else ITEM_GRIDS_1_EVEN
        elif self.classify_server(GET_ITEMS_2, image, offset=(5, 0)):
            self.item_grid.grids = ITEM_GRIDS_2
        elif self.classify_server(GET_ITEMS_3, image, offset=(5, 0)):
            self.item_grid.grids = ITEM_GRIDS_3
        else:
            raise GetItemsInvalid('Stat image is not a get_items image')

    def drop_has_get_items(self, images):
        """检查给定的截图列表中是否包含至少一张获得物品截图。

        Args:
            images (list[np.ndarray]): 截图列表。

        Returns:
            bool: 是否包含获得物品截图。
        """
        for image in images:
            if self.is_get_items(image):
                return True
        return False

    def parse_get_items_chain(self, images) -> t.Iterator[t.Iterator[Item]]:
        """解析包含连续翻页的获得物品截图链，多页情况自动合并。

        Args:
            images (list[np.ndarray]): 连续截图序列。

        Yields:
            Iterator[Item]: 每次结算完整的物品迭代器。
        """
        page1 = None
        for image in images:
            count = self.get_items_count(image)
            if count == 1:
                yield self.parse_get_items(image)
                page1 = None
            elif count == 2:
                if page1 is None:
                    # 正常的两行物品
                    yield self.parse_get_items(image)
                else:
                    # 第二张图，与前一页合并
                    page1 = self.parse_get_items(page1)
                    page2 = self.parse_get_items(image)
                    yield merge_get_items(page1, page2)
                page1 = None
            elif count == 3:
                # 第一张图，暂存待合并
                page1 = image

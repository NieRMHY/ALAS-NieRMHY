"""商店购买执行器，提供商品选择、库存检测和购买确认的核心逻辑。
用于所有商店类型的商品购买流程，支持库存计数 OCR 和退役回收。
"""

import re

import cv2

from module.base.timer import Timer
from module.exception import ScriptError
from module.logger import logger
from module.ocr.ocr import Digit, DigitCounter
from module.retire.retirement import Retirement
from module.shop.assets import *
from module.shop.base import ShopBase
from module.shop.shop_select_globals import *
from module.ui.assets import SHOP_BACK_ARROW


class StockCounter(DigitCounter):
    def pre_process(self, image):
        """OCR 预处理：转为灰度并反转。

        Args:
            image: 输入图像

        Returns:
            np.array: 反转后的灰度图像
        """
        r, g, b = cv2.split(image)
        image = cv2.max(cv2.max(r, g), b)

        return 255 - image

    def after_process(self, result):
        """OCR 后处理：修正常见识别错误。

        将连续两位数字修正为 'X/Y' 格式（如 '55' -> '5/5'），
        将连续四位数字修正为 'XX/YY' 格式（如 '1515' -> '15/15'）。
        """
        result = super().after_process(result)

        if re.match(r'^\d\d$', result):
            # 55 -> 5/5
            new = f'{result[0]}/{result[1]}'
            logger.info(f'[商店-购买] 库存计数器结果 {result} 修正为 {new}')
            result = new
        if re.match(r'^\d{4,}$', result):
            # 1515 -> 15/15
            new = f'{result[0:2]}/{result[2:4]}'
            logger.info(f'[商店-购买] 库存计数器结果 {result} 修正为 {new}')
            result = new

        return result


SHOP_SELECT_PR = [SHOP_SELECT_PR1, SHOP_SELECT_PR2, SHOP_SELECT_PR3]
OCR_SHOP_SELECT_STOCK = StockCounter(SHOP_SELECT_STOCK)

OCR_SHOP_AMOUNT = Digit(SHOP_AMOUNT, letter=(239, 239, 239), name='OCR_SHOP_AMOUNT')


class ShopClerk(ShopBase, Retirement):
    def shop_get_choice(self, item):
        """获取商品的配置选择项。

        根据商品组（pr/equipment 等）和等级，从配置中读取
        对应的选择值（如 PR 系列编号、装备等级）。

        Args:
            item: 商品对象，包含 group 和 tier 属性

        Returns:
            str: 配置中的选择值

        Raises:
            ScriptError: 配置项不存在时抛出
        """
        group = item.group
        if group == 'pr':
            postfix = None
            for _ in range(3):
                if _:
                    self.device.sleep((0.3, 0.5))
                    self.device.screenshot()

                for idx, btn in enumerate(SHOP_SELECT_PR):
                    if self.appear(btn, offset=(20, 20)):
                        postfix = f'{idx + 1}'
                        break

                if postfix is not None:
                    break
                logger.warning('未能检测到PR系列，应用可能卡顿或冻结')
        else:
            postfix = f'_{item.tier.upper()}'

        ugroup = group.upper()
        # 2025-08-14 新商店 UI：购买 PlateT4 时，新 UI 类名为 XXXShop_250814，
        # 需要截取 "_" 前的类名
        class_name = self.__class__.__name__.split("_")[0]
        try:
            return getattr(self.config, f'{class_name}_{ugroup}{postfix}')
        except Exception:
            logger.critical(f"[商店] 配置项不存在: '{class_name}_{ugroup}{postfix}'")  # Modify by MHY, 去傲娇语
            raise

    def shop_get_select(self, item):
        """获取商品对应的选择网格按钮。

        根据商品组和配置选择项，定位到选择界面中对应的按钮位置。

        Args:
            item: 商品对象，包含 group 属性

        Returns:
            Button: 选择界面中的目标按钮

        Raises:
            ScriptError: 商品组不在 SELECT_ITEM_INFO_MAP 中时抛出
        """
        group = item.group
        if group not in SELECT_ITEM_INFO_MAP:
            logger.critical(f"[商店] 未知物品组: '{group}'")  # Modify by MHY, 去傲娇语
            raise ScriptError

        # 获取商品的配置选择项
        choice = self.shop_get_choice(item)

        # 获取选择界面中对应的按钮
        try:
            item_info = SELECT_ITEM_INFO_MAP[group]
            index = item_info['choices'][choice]
            if group == 'pr':
                for idx, btn in enumerate(SHOP_SELECT_PR):
                    if self.appear(btn, offset=(20, 20)):
                        series_key = f's{idx + 1}'
                        return item_info['grid'][series_key].buttons[index]
            else:
                return item_info['grid'].buttons[index]
        except Exception:
            logger.critical("[商店] SELECT_ITEM_INFO_MAP 配置异常，请检查资源文件")  # Modify by MHY, 去傲娇语
            raise ScriptError

    def shop_buy_select_execute(self, item):
        """执行选择式购买操作（如装备箱、蓝图等）。

        在选择界面中点击商品、读取库存限制、调整购买数量并确认。
        使用 ui_ensure_index 防止超出库存数量购买。

        Args:
            item: 待购买的商品对象

        Returns:
            bool: 是否成功执行购买
        """
        # Search for appropriate select grid button for item
        select = self.shop_get_select(item)

        # Get displayed stock limit; varies between shops
        # If read 0, then warn and exit as cannot safely buy
        timeout = Timer(5, count=10).start()
        skip_first_screenshot = True
        limit = 0
        while 1:
            if timeout.reached():
                break
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            _, _, limit = OCR_SHOP_SELECT_STOCK.ocr(self.device.image)
            if limit:
                break

        if not limit:
            logger.critical(f'{item.name}\'s stock count cannot be '
                            'extracted. Advised to re-cut the asset '
                            'OCR_SHOP_SELECT_STOCK')
            raise ScriptError

        # Click in intervals until plus/minus are onscreen
        click_timer = Timer(3, count=6)
        select_offset = (500, 400)
        while 1:
            if click_timer.reached():
                self.device.click(select)
                click_timer.reset()

            # Scan for plus/minus locations; searching within
            # offset will update the click position automatically
            self.device.screenshot()
            if self.appear(SELECT_MINUS, offset=select_offset) and self.appear(SELECT_PLUS, offset=select_offset):
                break
            else:
                continue

        # Total number to purchase altogether
        total = int(self._currency // item.price)
        diff = limit - total
        if diff > 0:
            limit = total

        # Alias OCR_SHOP_SELECT_STOCK to adapt with
        # ui_ensure_index; prevent overbuying when
        # out of stock; item.price may still evaluate
        # incorrectly
        def shop_buy_select_ensure_index(image):
            """读取自选商品库存并适配索引控制。

            Args:
                image: 截图区域。

            Returns:
                int: 剩余库存数或目标限制数。
            """
            current, remain, _ = OCR_SHOP_SELECT_STOCK.ocr(image)
            if not current:
                group_case = item.group.title() if len(item.group) > 2 else item.group.upper()
                logger.info(f'{group_case} 已售罄；退出以防止超买')
                return limit
            return remain

        self.ui_ensure_index(limit, letter=shop_buy_select_ensure_index, prev_button=SELECT_MINUS,
                             next_button=SELECT_PLUS,
                             skip_first_screenshot=True)
        item._resource_purchase_quantity = limit
        self.device.click(SHOP_BUY_CONFIRM_SELECT)
        return True

    def shop_buy_amount_execute(self, item):
        """执行数量式购买操作（如部件箱、教材等）。

        在数量输入界面中点击最大数量、读取限制值、调整购买数量并确认。

        Args:
            item: 待购买的商品对象

        Returns:
            bool: 是否成功执行购买

        Raises:
            ScriptError: OCR 识别数量为 0 时抛出
        """
        index_offset = (40, 20)

        # In case either -/+ shift position, use
        # shipyard ocr trick to accurately parse
        self.appear(AMOUNT_MINUS, offset=index_offset)
        self.appear(AMOUNT_PLUS, offset=index_offset)
        area = OCR_SHOP_AMOUNT.buttons[0]
        OCR_SHOP_AMOUNT.buttons = [(AMOUNT_MINUS.button[2] + 3, area[1], AMOUNT_PLUS.button[0] - 3, area[3])]

        # Total number that can be purchased
        # altogether based on clicking max
        # Needs small delay for stable image
        self.appear_then_click(AMOUNT_MAX, offset=(50, 50))
        self.device.sleep((0.3, 0.5))
        timeout = Timer(5, count=10).start()
        limit = 0
        while 1:
            if timeout.reached():
                break
            self.device.screenshot()
            limit = OCR_SHOP_AMOUNT.ocr(self.device.image)
            if limit:
                break

        if not limit:
            logger.critical('OCR_SHOP_AMOUNT resulted in zero (0); '
                            'asset may be compromised')
            raise ScriptError

        # Adjust purchase amount if needed
        total = int(self._currency // item.price)
        diff = limit - total
        if diff > 0:
            limit = total

        self.ui_ensure_index(limit, letter=OCR_SHOP_AMOUNT, prev_button=AMOUNT_MINUS, next_button=AMOUNT_PLUS,
                             skip_first_screenshot=True)
        item._resource_purchase_quantity = limit
        self.device.click(SHOP_BUY_CONFIRM_AMOUNT)
        return True

    def shop_interval_clear(self):
        """清除购买界面相关按钮的点击间隔。

        子类可重写此方法以清除特定资产的 interval 状态。
        """
        self.interval_clear(SHOP_BACK_ARROW)
        self.interval_clear(SHOP_BUY_CONFIRM)

    def shop_buy_handle(self, item):
        """处理购买界面（子类重写）。

        子类根据自身商店特性重写，处理选择、数量等购买界面。

        Args:
            item: 待购买的商品对象

        Returns:
            bool: 是否检测到购买界面并进行了处理
        """
        return False

    def shop_buy_execute(self, item, skip_first_screenshot=True):
        """执行购买操作的完整状态循环。

        通过状态循环完成从点击商品到购买确认的完整流程。
        处理退役、遮挡、信息栏等意外情况。

        Args:
            item: 待购买的商品对象
            skip_first_screenshot: 是否跳过首次截图
        """
        success = False
        confirmed_purchase = False
        from module.statistics.resource_tracking import receipt_totals
        receipts = receipt_totals(self.config)
        # 每次成交独立记录；数量选择框确认后再覆盖默认的一次购买。
        item._resource_purchase_quantity = 1
        self.shop_interval_clear()

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(SHOP_BACK_ARROW, offset=(30, 30), interval=3):
                self.device.click(item)
                continue
            if self.appear_then_click(SHOP_BUY_CONFIRM, offset=(20, 20), interval=3):
                self.interval_reset(SHOP_BACK_ARROW)
                continue
            if self.shop_buy_handle(item):
                self.interval_reset(SHOP_BACK_ARROW)
                continue
            if self.handle_retirement():
                self.interval_reset(SHOP_BACK_ARROW)
                continue
            if self.shop_purchase_result_handle():
                self.interval_reset(SHOP_BACK_ARROW)
                success = confirmed_purchase = True
                continue
            if self.shop_obstruct_handle():
                self.interval_reset(SHOP_BACK_ARROW)
                success = True
                continue
            if self.info_bar_count():
                self.interval_reset(SHOP_BACK_ARROW)
                success = True
                continue

            # End
            if success and self.appear(SHOP_BACK_ARROW, offset=(30, 30)):
                if confirmed_purchase:
                    from module.statistics.resource_tracking import record_purchase
                    record_purchase(self.config, item, item._resource_purchase_quantity, receipts)
                break

    def shop_buy(self):
        """执行商店购买主循环。

        获取商品列表、OCR 货币余额，逐个购买直到无可用商品或余额不足。
        最多迭代 12 次防止无限循环。

        Returns:
            bool: 是否成功（True 表示购买完成或余额不足，False 表示余额为 0）
        """
        for _ in range(12):
            logger.hr('Shop buy', level=2)
            # Get first for innate delay to ocr
            # shop currency for accurate parse
            items = self.shop_get_items()
            self.shop_currency()
            if self._currency <= 0:
                logger.warning(f'Current funds: {self._currency}, stopped')
                return False

            item = self.shop_get_item_to_buy(items)
            if item is None:
                logger.info('Shop buy finished')
                return True
            else:
                self.shop_buy_execute(item)
                continue

        logger.warning('Too many items to buy, stopped')
        return True

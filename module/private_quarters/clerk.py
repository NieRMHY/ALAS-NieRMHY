"""
私人休息室商店店员逻辑。

封装私人宿舍商店的购买流程，继承通用 ShopClerk 和 PQShopUI，
提供商品购买执行、间隔计时器清除等操作。
支持最大数量购买和确认弹窗处理。

Pages: in: PRIVATE_QUARTERS_SHOP
"""

from module.base.timer import Timer
from module.logger import logger
from module.private_quarters.assets import *
from module.private_quarters.ui import PQShopUI
from module.shop.clerk import ShopClerk


class PQShopClerk(ShopClerk, PQShopUI):
    def shop_interval_clear(self):
        """
        清除私人宿舍商店相关的按钮间隔计时器。

        子类可覆写此方法以清除特定资产的间隔。
        """
        self.interval_clear([
            PRIVATE_QUARTERS_SHOP_CHECK,
            PRIVATE_QUARTERS_SHOP_AMOUNT_MAX,
            PRIVATE_QUARTERS_SHOP_CONFIRM_AMOUNT
        ])

    def shop_buy_execute(self, item, skip_first_screenshot=True):
        """执行单个商品的购买流程。

        点击商品 -> 最大数量 -> 确认购买 -> 等待购买完成。

        Args:
            item: 要购买的商品按钮对象。
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 成功完成购买返回 True。

        Pages:
            in: 私人宿舍商店
            out: 私人宿舍商店
        """

        # Helper funcs to ensure the appearance for pre and post
        # conditions for after confirm of purchase
        def after_confirm_state():
            return (self.appear(PRIVATE_QUARTERS_SHOP_WEEKLY_ROSES_GET, offset=(20, 20)) or
                    self.appear(PRIVATE_QUARTERS_SHOP_WEEKLY_CAKES_GET, offset=(20, 20)))

        def after_purchase_state():
            return (not self.appear(PRIVATE_QUARTERS_SHOP_WEEKLY_ROSES_GET, offset=(20, 20)) and
                    not self.appear(PRIVATE_QUARTERS_SHOP_WEEKLY_CAKES_GET, offset=(20, 20)) and
                    self.appear(PRIVATE_QUARTERS_SHOP_CHECK))

        self.shop_interval_clear()
        PRIVATE_QUARTERS_SHOP_CHECK.clear_offset()

        for _ in self.loop():

            # End
            if after_confirm_state():
                break

            if self.appear(PRIVATE_QUARTERS_SHOP_CHECK, interval=3):
                self.device.click(item)
                continue
            if self.appear_then_click(PRIVATE_QUARTERS_SHOP_AMOUNT_MAX, offset=(20, 20), interval=1):
                continue
            if self.appear_then_click(PRIVATE_QUARTERS_SHOP_CONFIRM_AMOUNT, offset=(20, 20), interval=1):
                continue

        click_timer = Timer(3, count=6)
        for _ in self.loop():
            # End
            if after_purchase_state():
                break

            if click_timer.reached() and after_confirm_state():
                self.device.click(PRIVATE_QUARTERS_SHOP_CHECK)
                click_timer.reset()
                continue

    def shop_buy(self):
        """
        循环扫描并购买商店中的可购物品。

        最多循环 12 次，每次扫描商品列表、检查余额、购买第一个匹配项。

        Returns:
            bool: 是否成功完成（True=全部买完或无可买项，False=余额不足）

        Pages:
            in: 私人宿舍商店
            out: 私人宿舍商店
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

                # After purchase, navbars are weirdly
                # reset to default positions
                # So move back for next scan
                self.shop_left_navbar_ensure(2)
                self.shop_bottom_navbar_ensure(2)

                continue

        logger.warning('Too many items to buy, stopped')
        return True

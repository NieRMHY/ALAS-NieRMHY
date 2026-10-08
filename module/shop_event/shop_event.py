"""活动商店模块。

提供碧蓝航线活动商店的自动化购买功能，包括：
- 活动点数（pt/URpt）的获取与余额管理
- UR 舰船购买逻辑（含 URpt 不足时的自动兑换）
- 未获取物品（unobtained）的优先购买
- 基于预设或自定义过滤器的批量购买策略

支持多个活动商店标签页的自动切换与遍历。
"""

from typing import List, Tuple

from module.base.decorator import del_cached_property
from module.base.timer import Timer
from module.logger import logger
from module.shop.assets import NAV_GENERAL, NAV_EVENT
from module.shop_event.assets import NO_NAV_EVENT_CHECK
from module.shop_event.clerk import EventShopClerk, ItemNotFoundError
from module.shop_event.item import EventShopItem, UR_SHIP_PRICES_IN_URPT, COIN_PRICE_IN_URPT, URPT_PRICE_IN_PT
from module.shop_event.selector import EVENT_SHOP_PRESET_FILTER, FILTER
from module.ui.assets import SHOP_GOTO_MUNITIONS
from module.ui.page import page_shop, page_munitions


class EventShop(EventShopClerk):
    """
    Class for Event Shop operations with backend operations.
    """
    pt = 0
    urpt = 0
    pt_preserved = 0

    def get_current_pts(self):
        """刷新并更新当前 PT 和 URpt 余额。"""
        self.pt = self.event_shop_get_pt()
        if self.event_shop_has_urpt:
            self.urpt = self.event_shop_get_urpt()

    def preserve_pt(self, amount: int):
        """为后续购买预留指定数量的活动 PT。

        Args:
            amount (int): 需预留的 PT 数量。
        """
        self.pt_preserved += amount
        logger.info(f"[活动商店] 保留 {amount} PT点数供后续使用。总保留PT: {self.pt_preserved}")

    def handle_items_related_with_urpt(self, items: List[EventShopItem], num_of_ships_to_buy: int = 2) \
            -> Tuple[List[EventShopItem], List[EventShopItem]]:
        """使用 URpt 购买相关商品（主要是 UR 舰船），必要时兑换 URpt。

        应在购买普通物品前优先调用。

        Args:
            items (List[EventShopItem]): 扫描到的所有商品列表。
            num_of_ships_to_buy (int): 计划购买的舰船数量。默认为 2。

        Returns:
            Tuple[List[EventShopItem], List[EventShopItem]]: 包含两个列表的元组：
                - 第一个列表为与 URpt 无关的普通物品；
                - 第二个列表为与 URpt 相关的特殊物品（URpt、金币等），留在最后处理。
        """
        if not self.event_shop_has_urpt:
            logger.info("[活动商店] 活动商店没有UR点数，跳过UR点数相关物品处理")
            return items, []

        ship_items = []
        urpt_items = []
        coin_items = []
        other_items = []

        for item in items:
            if item.price in UR_SHIP_PRICES_IN_URPT and item.cost == "URpt":
                ship_items.append(item)
            elif item.price == COIN_PRICE_IN_URPT and item.cost == "URpt":
                coin_items.append(item)
            elif item.price == URPT_PRICE_IN_PT and item.cost == "pt":
                urpt_items.append(item)
            else:
                other_items.append(item)

        # 优先购买舰船
        urpt_preserve = False
        ship_items.sort(key=lambda item: item.price)
        if ship_items and num_of_ships_to_buy > 0:
            if len(ship_items) == 1 and num_of_ships_to_buy == 1:
                logger.info("[活动商店] 只有一个舰船物品且购买数量为1，跳过购买舰船")
            else:
                ships_to_buy = ship_items[:num_of_ships_to_buy]
                logger.info(f"[活动商店] 尝试购买舰船物品: {[str(item) for item in ships_to_buy]}")
                current_urpt = self.event_shop_get_urpt()
                while ships_to_buy:
                    urpt_needed = sum([item.price for item in ships_to_buy])
                    if current_urpt >= urpt_needed:
                        for item in ships_to_buy:
                            self.event_shop_buy_item(item)
                        logger.info(f"[活动商店] 成功购买舰船物品: {[str(item) for item in ships_to_buy]}")
                        break
                    else:
                        if self.is_event_ended:
                            urpt_in_stock = urpt_items[0].count if urpt_items else 0
                            if current_urpt + urpt_in_stock >= urpt_needed:
                                if urpt_in_stock > 0:
                                    self.event_shop_buy_item(urpt_items[0], amount=urpt_needed - current_urpt)
                                    urpt_items[0].count -= (urpt_needed - current_urpt)
                                for item in ships_to_buy:
                                    self.event_shop_buy_item(item)
                                logger.info(f"[活动商店] 成功购买舰船物品: {[str(item) for item in ships_to_buy]}")
                                break
                            else:
                                logger.warning(
                                    f"[活动商店] UR点数不足以购买舰船: {[str(item) for item in ships_to_buy]}，"
                                    f"跳过最贵的并重试")
                                ships_to_buy.pop()
                        else:
                            urpt_in_stock = urpt_items[0].count if urpt_items else 0
                            if current_urpt + urpt_in_stock >= urpt_needed:
                                pt_needed = (urpt_needed - current_urpt) * URPT_PRICE_IN_PT
                                self.preserve_pt(pt_needed)
                                logger.info(f"[活动商店] 保留 {pt_needed} PT点数用于购买舰船的UR点数")
                                urpt_preserve = True
                                while ships_to_buy and sum([item.price for item in ships_to_buy]) > current_urpt:
                                    ships_to_buy.pop()
                                if ships_to_buy:
                                    for item in ships_to_buy:
                                        self.event_shop_buy_item(item)
                                    logger.info(
                                        f"[活动商店] 成功购买舰船物品: {[str(item) for item in ships_to_buy]}")
                                    break
                                else:
                                    logger.warning("[活动商店] 当前UR点数无法购买舰船，跳过购买舰船")
                                    break
                            else:
                                logger.warning("[活动商店] 购买所有UR点数后仍不足，跳过购买最贵的舰船")
                                ships_to_buy.pop()

        if urpt_preserve:
            logger.info("[活动商店] 因保留UR点数购买舰船，跳过购买UR点数和物资")
            return other_items, []
        else:
            logger.info("[活动商店] 最后购买UR点数和UR点数定价的物资")
            return other_items, urpt_items + coin_items

    def handle_unobtained_items(self, items: List[EventShopItem], buy_unobtained_items=False) \
            -> Tuple[List[EventShopItem], List[EventShopItem]]:
        """购买活动商店中带有 'unobtained'（未获得）角标的物品（通常为舰船）。

        在处理完 URpt 相关物品后、购买其他物品之前执行。
        对于库存大于 1 的商品仅购买 1 件，后续由过滤器决定是否继续购买。

        Args:
            items (List[EventShopItem]): 待筛选的商品列表。
            buy_unobtained_items (bool): 是否启用未获得商品购买。默认为 False。

        Returns:
            Tuple[List[EventShopItem], List[EventShopItem]]: 包含两个列表的元组：
                - 第一个列表为保留给后续过滤器处理的商品；
                - 第二个列表为已购 1 件且仍有剩余库存的商品列表。
        """
        if not buy_unobtained_items:
            return items, []
        unobtained_items = []
        other_items = []
        for item in items:
            if item.tag == "unobtained":
                unobtained_items.append(item)
            else:
                other_items.append(item)
        if not unobtained_items:
            return other_items, []
        if not self.is_event_ended:
            logger.info("[活动商店] 活动未结束，为未获取物品保留PT点数。也可等待活动地图掉落")
            self.preserve_pt(sum(item.price for item in unobtained_items))
            return other_items, []

        multiple_items = []
        logger.info(f"[活动商店] 尝试购买未获取物品: {[str(item) for item in unobtained_items]}")
        for item in unobtained_items:
            self.event_shop_buy_item(item)
            logger.info(f"[活动商店] 成功购买未获取物品: {str(item)}")
            if item.count > 1:
                item.count -= 1
                multiple_items.append(item)
            else:
                # 若商品库存仅为 1，重新扫描时不会再次出现
                pass

        return items, multiple_items

    def calculate_affordable_amount(self, item: EventShopItem) -> int:
        """计算在当前货币余额和预留限制下该商品的最大可购买数量。

        针对石油等有上限的资源会额外检查容量限制。

        Args:
            item (EventShopItem): 待计算商品。

        Returns:
            int: 可购买的数量。
        """
        if item.name == "Oil":
            current_oil = self.get_oil()
            return min(item.count, (self.pt - self.pt_preserved) // item.price, (25000 - current_oil) // 1000)
        if item.cost == 'URpt':
            return min(item.count, self.urpt // item.price)
        elif item.cost == 'pt':
            return min(item.count, (self.pt - self.pt_preserved) // item.price)
        else:
            logger.error(f"[活动商店] 未知的消耗类型: {item.cost}，物品: {str(item)}")
            return 0

    def _run(self):
        """
        Pages:
            in: shop_event
        """
        self.event_shop_load_ensure()
        items = self.scan_all()
        if not len(items):
            logger.warning("No items found in event shop.")
            return True
        logger.hr("Event Shop buy", level=2)
        self.get_current_pts()
        items, urpt_related_items = self.handle_items_related_with_urpt(items, self.config.EventShop_BuyURShip)
        self.get_current_pts()
        items, unobtained_multiple_stock_items = self.handle_unobtained_items(items, self.config.EventShop_UnlockSSRShip)
        items += unobtained_multiple_stock_items

        if self.config.EventShop_PresetFilter == 'custom':
            filter = self.config.EventShop_CustomFilter
        else:
            filter = EVENT_SHOP_PRESET_FILTER[self.config.EventShop_PresetFilter]
        FILTER.load(filter)
        items = FILTER.apply(items)
        items += urpt_related_items
        if not len(items):
            logger.info("No items to buy after filtering.")
            return True
        logger.attr('Item_sort', ' > '.join([str(item) for item in items]))
        self.get_current_pts()
        logger.attr("Pt_preserved", self.pt_preserved)
        for item in items:
            logger.hr(f"Attempting to buy item: {str(item)}", level=3)
            affordable_amount = self.calculate_affordable_amount(item)
            if affordable_amount <= 0:
                logger.warning(f"Cannot afford to buy any of item: {str(item)}.")
                if self.is_event_ended:
                    logger.info("Event is ended, skip this item and continue to try buying other items.")
                    continue
                else:
                    logger.info("Event is not ended, stopping further purchases to avoid overspending.")
                    break
            elif affordable_amount < item.count:
                logger.warning(f"Can only afford to buy {affordable_amount} of item: {str(item)}.")
                self.event_shop_buy_item(item, amount=affordable_amount)
                if self.is_event_ended:
                    logger.info("Event is ended, continue to try buying other items.")
                    self.get_current_pts()
                    continue
                else:
                    logger.info("Event is not ended, stopping further purchases to avoid overspending.")
                    break
            else:
                self.event_shop_buy_item(item)
                logger.info(f"Successfully bought item: {str(item)}")
                self.get_current_pts()
        return True

    def run(self):
        """运行活动商店购买主流程。

        支持多活动标签页切换，依次扫描并执行购买策略。
        """
        self.ui_goto_main()
        self.ui_ensure(page_shop)
        timeout = Timer(2, count=4)
        for _ in self.loop():
            if self.appear(page_munitions.check_button, threshold=20):
                break
            if timeout.reached():
                self.device.click(SHOP_GOTO_MUNITIONS)
                timeout.reset()

        if self.appear(NAV_GENERAL, offset=(5, 5)):
            if self.appear(NO_NAV_EVENT_CHECK, offset=(5, 5)):
                logger.info("There is no event shop currently. End the task.")
                self.config.task_delay(server_update=True)
                return False
            else:
                self.ui_click(NAV_EVENT, check_button=NAV_EVENT, appear_button=NAV_GENERAL)

        count, navbar = self.event_shop_tab_count_and_navbar
        logger.info(f"Detected {count} event shop(s). Start processing.")
        for i in range(count):
            navbar.set(main=self, left=i + 1)
            for _ in range(7):  # Refresh up to 7 times to deal with buying failures
                try:
                    self.pt_preserved = 0
                    self._run()
                    if self.config.task_switched():
                        return True
                    break
                except ItemNotFoundError:
                    if count >= 2:
                        navbar.set(main=self, left=((i + 1) % count) + 1)
                        navbar.set(main=self, left=i + 1)
                    else:
                        self.ui_click(NAV_GENERAL, check_button=NAV_GENERAL, appear_button=NAV_EVENT)
                        self.ui_click(NAV_EVENT, check_button=NAV_EVENT, appear_button=NAV_GENERAL)
                    continue
            del_cached_property(self, 'is_event_ended')
            del_cached_property(self, 'event_shop_has_urpt')
            del_cached_property(self, 'is_pt_reversed')
            if self.config.task_switched():
                return True
        self.config.task_delay(server_update=True)
        return True

"""大世界商店+物品筛选与选择逻辑。

基于正则表达式解析商品类型，并根据用户配置的过滤器决定购买行为。
支持明石商店过滤和 OS 商店预设两种过滤模式。
"""
import re
from contextlib import contextmanager
from typing import List
from module.config.config_generated import GeneratedConfig
from module.logger import logger
from module.os_shop.preset import OS_SHOP
from module.os_shop.item import OSShopItem as Item
from module.base.filter import Filter

# 物品名称正则匹配规则
FILTER_REGEX = re.compile(
    '^(actionpoint|crystallizedheatresistantsteel|developmentmaterial'
    '|energystoragedevice|geardesignplan|gearpart|logger|metaredbook'
    '|nanoceramicalloy|neuroplasticprostheticarm|ordnancetestingreport'
    '|platerandom|purplecoins|repairpack|supercavitationgenerator|tuningsample'
    '|tuning)'

    '(20|50|100|prototype|specialized|abyssal|obscure|full2|full|triple2|triple|2'
    '|combat|offence|survival)?'

    '(t[1-6])?$',
    flags=re.IGNORECASE)
FILTER_ATTR = ('group', 'sub_genre', 'tier')
FILTER = Filter(FILTER_REGEX, FILTER_ATTR)


class Selector():
    """商店物品选择器基类。

    提供物品预处理、金币检查、物品计数验证和过滤功能。
    """

    def pretreatment(self, items) -> List[Item]:
        """预处理物品列表，解析物品名称中的类型信息。

        通过正则表达式提取物品的 group、sub_genre 和 tier 属性。

        Args:
            items: 待预处理的物品列表。

        Returns:
            list[Item]: 预处理后的物品列表，仅包含可解析的物品。
        """
        _items = []
        for item in items:
            item.group, item.sub_genre, item.tier = None, None, None
            result = re.search(FILTER_REGEX, item.name.lower())
            if result:
                item.group, item.sub_genre, item.tier = [group.lower()
                                                         if group is not None else None
                                                         for group in result.groups()]
                _items.append(item)

        return _items

    def enough_coins_in_akashi(self, item) -> bool:
        """检查明石商店是否有足够金币购买物品。

        Args:
            item: 待检查的物品。

        Returns:
            bool: 金币足够返回 True，否则返回 False。
        """
        if item.cost == 'YellowCoins' and item.price <= self._shop_yellow_coins:
            return True
        if item.cost == 'PurpleCoins' and item.price <= self._shop_purple_coins:
            return True

        return False

    def check_cl1_purple_coins(self, item) -> bool:
        """检查 CL1 模式下是否允许购买紫币。

        Args:
            item: 待检查的物品。

        Returns:
            bool: 允许购买返回 True，CL1 模式下购买紫币返回 False。
        """
        return not (self.is_cl1_mode_enabled and item.name == 'PurpleCoins')

    def check_item_count(self, item) -> bool:
        """检查物品计数是否有效。

        Args:
            item: 待检查的物品。

        Returns:
            bool: 计数有效（当前数量 >= 1，总数量 >= 1，当前不超过总数）返回 True。
        """
        return item.count >= 1 and item.total_count >= 1 and item.count <= item.total_count

    def _opsi_shop_strategy_enabled(self):
        """仅在 OpsiShop 的港口购买作用域内启用高级策略。"""
        task = getattr(getattr(self.config, 'task', None), 'command', None)
        return (
            getattr(self, '_opsi_shop_strategy_scope_active', False)
            and task == 'OpsiShop'
            and getattr(self.config, 'ShopAdvanced_Mode', 'legacy') == 'advanced'
        )

    @contextmanager
    def opsi_shop_strategy_scope(self):
        """将高级策略限制在 OpsiShop 明确拥有的港口商店流程。"""
        previous = getattr(self, '_opsi_shop_strategy_scope_active', False)
        self._opsi_shop_strategy_scope_active = True
        try:
            yield
        finally:
            self._opsi_shop_strategy_scope_active = previous

    def _opsi_shop_strategy_state(self):
        """保存明石商店多次刷新间的策略会话记录。"""
        state = getattr(self, '_opsi_shop_strategy_session', None)
        if state is None:
            state = {'spent': {}, 'purchased': {}, 'inventory_purchased': {}, 'cap_usage': {}}
            self._opsi_shop_strategy_session = state
        return state

    def _opsi_shop_strategy_currency(self, items):
        """以现有保留币规则计算脚本可支配的黄币和紫币。"""
        currencies = {}
        for item in items:
            cost = getattr(item, 'cost', None)
            if not isinstance(cost, str) or not cost or cost in currencies:
                continue
            try:
                currencies[cost] = max(0, int(self.get_currency_coins(item)))
            except (TypeError, ValueError):
                currencies[cost] = 0
        return currencies

    def _opsi_shop_strategy_max_quantity(self, item):
        """用实际库存和保留后的币量限制单个大世界商品数量。"""
        if item.price <= 0:
            return 0
        try:
            currency = max(0, int(self.get_currency_coins(item)))
        except (TypeError, ValueError):
            return 0
        stock = max(1, int(getattr(item, 'count', 0)))
        return min(stock, currency // item.price)

    def _opsi_shop_strategy_actions(self, items, eligible):
        """将大世界商品投影给策略，并将已校验的动作绑定回原商品。"""
        from module.shop_strategy.adapter import run_shop_strategy

        self._opsi_shop_strategy_failed = False
        state = self._opsi_shop_strategy_state()
        result = run_shop_strategy(
            self.config.ShopAdvanced_Script,
            items,
            domain='opsi',
            currency=self._opsi_shop_strategy_currency(items),
            eligible=eligible,
            # 明石商店不读取计数器，count 会保持 -1；此时以单件作为安全上限。
            stock=lambda item: max(1, int(getattr(item, 'count', 0))),
            max_quantity=self._opsi_shop_strategy_max_quantity,
            spent=state['spent'],
            purchased=state['purchased'],
            inventory_purchased=state['inventory_purchased'],
            cap_usage=state['cap_usage'],
        )
        if not result.success:
            self._opsi_shop_strategy_failed = True
            diagnostic = result.diagnostic
            location = ''
            if diagnostic is not None and diagnostic.line is not None:
                location = f'（第 {diagnostic.line} 行，第 {diagnostic.column or 1} 列）'
            message = diagnostic.message if diagnostic is not None else '未知策略错误'
            logger.warning(f'[高级商店策略] {message}{location}；本轮不购买')
            return None

        for action in result.actions:
            action.item._shop_strategy_candidate_id = action.candidate.id
            action.item._shop_strategy_quantity = action.quantity
            action.item._shop_strategy_cost = action.cost
            action.item._shop_strategy_cap_usage_keys = action.cap_usage_keys
        logger.attr('高级策略计划', ' > '.join(
            f'{action.candidate.name} x{action.quantity}' for action in result.actions
        ))
        return result.actions

    def _opsi_shop_strategy_record_purchase(self, item):
        """将大世界商店实际购买量加入当前高级策略会话。"""
        if not self._opsi_shop_strategy_enabled():
            return
        candidate_id = getattr(item, '_shop_strategy_candidate_id', None)
        cost = getattr(item, '_shop_strategy_cost', None)
        quantity = getattr(item, '_shop_strategy_executed_quantity',
                           getattr(item, '_shop_strategy_quantity', None))
        if not isinstance(candidate_id, str) or not isinstance(cost, str):
            return
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            return
        state = self._opsi_shop_strategy_state()
        state['spent'][cost] = state['spent'].get(cost, 0) + item.price * quantity
        state['purchased'][candidate_id] = state['purchased'].get(candidate_id, 0) + quantity
        state['inventory_purchased'][candidate_id] = state['inventory_purchased'].get(candidate_id, 0) + quantity
        for key in getattr(item, '_shop_strategy_cap_usage_keys', ()):
            state['cap_usage'][key] = state['cap_usage'].get(key, 0) + quantity

    def items_filter_in_akashi_shop(self, items) -> List[Item]:
        """过滤明石商店中可购买的物品。

        根据 CL1 模式或通用配置过滤物品，并检查金币是否充足。

        Args:
            items: 待过滤的物品列表。

        Returns:
            list[Item]: 可购买的物品列表。
        """
        items = self.pretreatment(items)
        if self._opsi_shop_strategy_enabled():
            actions = self._opsi_shop_strategy_actions(
                items,
                eligible=lambda item: (
                    self.enough_coins_in_akashi(item)
                    and item.price <= max(0, self.get_currency_coins(item))
                ),
            )
            if actions is None:
                return []
            # 旧调用方使用 pop() 取候选；只返回下一项以便每次购买后重新 OCR 规划。
            return [actions[0].item] if actions else []
        if getattr(self, 'is_running_cl1_leveling', False):
            parser = self.config.OpsiHazard1Leveling_Cl1Filter
            if not parser:
                parser = 'ActionPoint'
        else:
            parser = self.config.OpsiGeneral_AkashiShopFilter
            if not parser.strip():
                parser = GeneratedConfig.OpsiGeneral_AkashiShopFilter
        FILTER.load(parser)
        return FILTER.applys(items, funcs=[self.enough_coins_in_akashi])

    def items_filter_in_os_shop(self, items) -> List[Item]:
        """过滤 OS 商店中可购买的物品。

        根据预设或自定义过滤器筛选物品，并检查 CL1 紫币限制和物品计数。

        Args:
            items: 待过滤的物品列表。

        Returns:
            list[Item]: 可购买的物品列表。
        """
        items = self.pretreatment(items)
        if self._opsi_shop_strategy_enabled():
            actions = self._opsi_shop_strategy_actions(
                items,
                eligible=lambda item: (
                    self.check_cl1_purple_coins(item)
                    and self.check_item_count(item)
                    and item.price <= max(0, self.get_currency_coins(item))
                ),
            )
            if actions is None:
                return []
            return [action.item for action in actions]
        preset = self.config.OpsiShop_PresetFilter
        parser = ''
        if preset == 'custom':
            parser = self.config.OpsiShop_CustomFilter
            if not parser.strip():
                parser = OS_SHOP[GeneratedConfig.OpsiShop_PresetFilter]
        else:
            parser = OS_SHOP[preset]
        FILTER.load(parser)
        return FILTER.applys(items, funcs=[self.check_cl1_purple_coins, self.check_item_count])

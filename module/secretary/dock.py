from module.ui.setting import Setting
from module.logger import logger
from module.equipment.assets import EQUIP_CONFIRM
from module.combat.assets import GET_ITEMS_1
from module.retire.assets import *
from module.base.timer import Timer
import module.config.server as server

from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.ui.switch import Switch


DOCK_SORTING = Switch('Dork_sorting')
DOCK_SORTING.add_state('Ascending', check_button=SORT_ASC, click_button=SORTING_CLICK)
DOCK_SORTING.add_state('Descending', check_button=SORT_DESC, click_button=SORTING_CLICK)

DOCK_FAVOURITE = Switch('Favourite_filter')
DOCK_FAVOURITE.add_state('on', check_button=COMMON_SHIP_FILTER_ENABLE)
DOCK_FAVOURITE.add_state('off', check_button=COMMON_SHIP_FILTER_DISABLE)

CARD_GRIDS = ButtonGrid(
    origin=(93, 76), delta=(164 + 2 / 3, 227), button_shape=(138, 204), grid_shape=(7, 2), name='CARD')
CARD_RARITY_GRIDS = CARD_GRIDS.crop(area=(0, 0, 138, 5), name='RARITY')
if server.server != 'jp':
    CARD_LEVEL_GRIDS = CARD_GRIDS.crop(area=(77, 5, 132, 27), name='LEVEL')
    CARD_FAVORABILITY_GRIDS = CARD_GRIDS.crop(area=(23, 29, 48, 52), name='FAVORABILITY')
else:
    CARD_LEVEL_GRIDS = CARD_GRIDS.crop(area=(74, 5, 136, 27), name='LEVEL')
    CARD_FAVORABILITY_GRIDS = CARD_GRIDS.crop(area=(21, 29, 71, 48), name='FAVORABILITY')

class SecretaryDockMixin:
    """秘书舰船坞筛选与排序混入类。"""

    def handle_dock_cards_loading(self, skip_first_screenshot=True):
        """等待船坞卡片加载完成。

        通过哈希比对连续两帧截图判断画面是否稳定，若船坞为空则立即退出。
        使用 Timer(1.2s) 作为兜底超时，无法使用 confirm_timer 方法。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图，复用上一状态循环的截图。
        """
        from module.retire.scanner import HashGenerator
        scanner = HashGenerator()
        old_result = None
        if not skip_first_screenshot:
            self.device.screenshot()
            skip_first_screenshot = True
        new_result = scanner.scan(self.device.image)
        timeout = Timer(1.2, count=1).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                old_result = new_result
                self.device.screenshot()
                new_result = scanner.scan(self.device.image)

            if self.appear(DOCK_EMPTY):
                logger.info('Dock empty')
                break
            if timeout.reached():
                break
            if old_result == new_result:
                break

    def dock_favourite_set(self, enable=False, wait_loading=True):
        """设置船坞是否仅筛选收藏舰船。

        Args:
            enable (bool): 是否启用收藏过滤。
            wait_loading (bool): 是否等待卡片加载完成。
        """
        if DOCK_FAVOURITE.set('on' if enable else 'off', main=self):
            if wait_loading:
                self.handle_dock_cards_loading()

    def secretary_filter_enter(self):
        """进入船坞筛选面板。"""
        logger.info('Dock filter enter')
        self.interval_clear(DOCK_CHECK)
        for _ in self.loop():
            if self.appear(DOCK_FILTER_CONFIRM, offset=(20, 60)):
                break
            if self.appear(DOCK_CHECK, offset=(20, 20), interval=5):
                self.device.click(DOCK_FILTER)
                continue
            # 处理上次退役遗留的慢速弹窗
            # 装备确认
            if self.appear_then_click(EQUIP_CONFIRM, offset=(30, 30), interval=2):
                continue
            if self.appear_then_click(EQUIP_CONFIRM_2, offset=(30, 30), interval=2):
                self.interval_clear(GET_ITEMS_1)
                continue
            # 获得物品
            if self.appear(GET_ITEMS_1, offset=(30, 30), interval=2):
                self.device.click(GET_ITEMS_1_RETIREMENT_SAVE)
                continue

    def secretary_filter_confirm(self, wait_loading=True, skip_first_screenshot=True):
        """确认并关闭船坞筛选面板。

        Args:
            wait_loading (bool): 是否等待卡片加载完成。
            skip_first_screenshot (bool): 是否跳过首次截图。
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件
            # 偶发无黑色模糊背景的筛选状态，需同时判断 DOCK_FILTER_CONFIRM 消失且 DOCK_CHECK 出现
            if not self.appear(DOCK_FILTER_CONFIRM, offset=(20, 60)):
                if self.appear(DOCK_CHECK, offset=(20, 20)):
                    break
            if self.appear_then_click(DOCK_FILTER_CONFIRM, offset=(20, 60), interval=3):
                continue

        if wait_loading:
            self.handle_dock_cards_loading()

    @cached_property
    def secretary_filter(self) -> Setting:
        """船坞筛选设置实例。

        Returns:
            Setting: 配置好的筛选设置对象。
        """
        delta = (147 + 1 / 3, 57)
        button_shape = (139, 42)
        setting = Setting(name='SECRETARY_DOCK', main=self)
        setting.add_setting(
            setting='sort',
            option_buttons=ButtonGrid(
                origin=(218, 36), delta=delta, button_shape=button_shape, grid_shape=(7, 1), name='FILTER_SORT'),
            # stat 有额外网格，不作处理
            option_names=['rarity', 'level', 'total', 'join', 'intimacy', 'mood', 'stat'],
            option_default='level'
        )
        setting.add_setting(
            setting='index',
            option_buttons=ButtonGrid(
                origin=(218, 109), delta=delta, button_shape=button_shape, grid_shape=(7, 2), name='FILTER_INDEX'),
            option_names=['all', 'vanguard', 'main', 'dd', 'cl', 'ca', 'bb',
                            'cv', 'repair', 'ss', 'others', 'not_available', 'not_available', 'not_available'],
            option_default='all'
        )
        setting.add_setting(
            setting='faction',
            option_buttons=ButtonGrid(
                origin=(218, 239), delta=delta, button_shape=button_shape, grid_shape=(7, 3), name='FILTER_FACTION'),
            option_names=['all', 'eagle', 'royal', 'sakura', 'iron', 'dragon', 'sardegna',
                            'northern', 'iris', 'vichya', 'tulipa', 'pedreria', 'meta', 'tempesta',
                            'other', 'not_available', 'not_available', 'not_available', 'not_available', 'not_available', 'not_available'],
            option_default='all'
        )
        setting.add_setting(
            setting='rarity',
            option_buttons=ButtonGrid(
                origin=(218, 427), delta=delta, button_shape=button_shape, grid_shape=(7, 1), name='FILTER_RARITY'),
            option_names=['all', 'common', 'rare', 'elite', 'super_rare', 'ultra', 'not_available'],
            option_default='all'
        )
        setting.add_setting(
            setting='extra',
            option_buttons=ButtonGrid(
                origin=(218, 499), delta=delta, button_shape=button_shape, grid_shape=(7, 2), name='FILTER_EXTRA'),
            option_names=['no_limit', 'has_skin', 'can_retrofit', 'enhanceable', 'can_limit_break', 'not_level_max', 'can_awaken',
                            'can_awaken_plus', 'special', 'oath_skin', 'unique_augment_module', 'wear_skin', 'oathed', 'not_available'],
            option_default='no_limit'
        )
        return setting

    def secretary_filter_set(
            self,
            sort='level',
            index='all',
            faction='all',
            rarity='all',
            extra='no_limit',
            wait_loading=True
    ):
        """设置船坞筛选参数。

        Args:
            sort (str | list): 排序依据，可选 ['rarity', 'level', 'total', 'join', 'intimacy', 'mood', 'stat']。
            index (str | list): 舰种分类，可选 ['all', 'vanguard', 'main', 'dd', 'cl', 'ca', 'bb', 'cv', 'repair', 'ss', 'others']。
            faction (str | list): 阵营分类，可选 ['all', 'eagle', 'royal', 'sakura', 'iron', 'dragon', 'sardegna', 'northern', 'iris', 'vichya', 'tulipa', 'pedreria', 'meta', 'tempesta', 'other']。
            rarity (str | list): 稀有度分类，可选 ['all', 'common', 'rare', 'elite', 'super_rare', 'ultra']。
            extra (str | list): 特殊标签，可选 ['no_limit', 'has_skin', 'can_retrofit', 'enhanceable', 'can_limit_break', 'not_level_max', 'can_awaken', 'can_awaken_plus', 'special', 'oath_skin', 'unique_augment_module', 'wear_skin', 'oathed']。
            wait_loading (bool): 是否等待卡片加载完成。

        Pages:
            in: page_dock
        """
        self.secretary_filter_enter()
        self.secretary_filter.set(sort=sort, index=index, faction=faction, rarity=rarity, extra=extra)
        self.secretary_filter_confirm(wait_loading=wait_loading)

    def dock_sort_method_dsc_set(self, enable=True, wait_loading=True):
        """设置船坞是否降序排序。

        Args:
            enable (bool): True 为降序，False 为升序。
            wait_loading (bool): 是否等待卡片加载完成。
        """
        if DOCK_SORTING.set(
            'Descending' if enable else 'Ascending',
            main=self
        ):
            if wait_loading:
                self.handle_dock_cards_loading()

    def dock_reset(self):
        """重置船坞的收藏过滤、排序方式及筛选选项为默认状态。"""
        self.dock_favourite_set(False, wait_loading=False)
        self.dock_sort_method_dsc_set(False, wait_loading=False)
        self.secretary_filter_set()
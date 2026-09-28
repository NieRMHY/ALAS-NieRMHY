"""仓库 UI 导航模块，处理仓库页面的页面切换和筛选设置。
包括装备栏和材料栏的切换导航，
以及稀有度等筛选条件的配置。"""

from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.logger import logger
from module.storage.assets import DISASSEMBLE, DISASSEMBLE_CANCEL, DISASSEMBLE_CONFIRM, EQUIPMENT_ENTER, \
    EQUIPMENT_FILTER, EQUIPMENT_FILTER_CONFIRM, MATERIAL_CHECK, MATERIAL_ENTER, MATERIAL_STABLE_CHECK
from module.ui.assets import STORAGE_CHECK
from module.ui.page import page_storage
from module.ui.setting import Setting
from module.ui.ui import UI


class StorageUI(UI):
    """仓库 UI 导航与筛选控制器。"""

    @cached_property
    def storage_filter(self) -> Setting:
        """仓库筛选设置对象。

        Returns:
            Setting: 配置好的仓库筛选设置实例。
        """
        delta = (147 + 1 / 3, 57)
        button_shape = (139, 42)
        setting = Setting(name='STORAGE', main=self)
        setting.add_setting(
            setting='rarity',
            option_buttons=ButtonGrid(
                origin=(219, 444), delta=delta, button_shape=button_shape, grid_shape=(7, 1), name='FILTER_RARITY'),
            option_names=['all', 'common', 'rare', 'elite', 'super_rare', 'ultra_rare', 'not_available'],
            option_default='all'
        )
        return setting

    def ui_goto_storage(self):
        """导航至仓库页面。

        Returns:
            bool: 是否成功到达仓库页面。
        """
        return self.ui_ensure(destination=page_storage)

    def _wait_until_storage_stable(self):
        """等待仓库界面稳定并清除通知栏。"""
        self.wait_until_stable(MATERIAL_STABLE_CHECK)
        self.handle_info_bar()

    def _storage_in_material(self, interval=0):
        """检测当前是否处于材料仓库界面。

        Args:
            interval (int, optional): 识别间隔，默认为 0。

        Returns:
            bool: 处于材料仓库界面返回 True，否则返回 False。
        """
        return self.match_template_color(MATERIAL_CHECK, offset=(20, 20), interval=interval)

    def _storage_enter_material(self, skip_first_screenshot=True):
        """从任意仓库子页面切换至材料栏。

        Pages:
            in: page_storage, any
            out: page_storage, material, MATERIAL_CHECK

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。
        """
        logger.info('仓库进入材料')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._storage_in_material():
                break

            # disassemble -> equipment
            if self.appear_then_click(DISASSEMBLE_CANCEL, offset=(20, 20), interval=3):
                self.interval_reset(STORAGE_CHECK)
                continue
            # equipment -> material
            if self.appear(DISASSEMBLE, offset=(20, 20), interval=3):
                logger.info('[存储-UI] 拆解 -> 材料进入')
                self.device.click(MATERIAL_ENTER)
                self.interval_reset(STORAGE_CHECK)
                continue
            # design -> material
            if self.appear(STORAGE_CHECK, offset=(20, 20), interval=3):
                logger.info('[存储-UI] 拆解 -> 材料进入')
                self.device.click(MATERIAL_ENTER)
                continue

        self.interval_clear(STORAGE_CHECK)

    def _storage_enter_equipment(self, skip_first_screenshot=True):
        """从任意仓库子页面切换至装备栏。

        Pages:
            in: page_storage, any
            out: page_storage, equipment, DISASSEMBLE

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。
        """
        logger.info('仓库进入装备')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(DISASSEMBLE, offset=(20, 20)):
                break

            # disassemble -> equipment
            if self.appear_then_click(DISASSEMBLE_CANCEL, offset=(20, 20), interval=3):
                self.interval_reset(STORAGE_CHECK)
                continue
            # material -> equipment
            if self._storage_in_material(interval=3):
                logger.info('_storage_in_material -> EQUIPMENT_ENTER')
                self.device.click(EQUIPMENT_ENTER)
                self.interval_reset(STORAGE_CHECK)
                continue
            # design -> equipment
            if self.appear(STORAGE_CHECK, offset=(20, 20), interval=3):
                logger.info('[存储-UI] 存储检查 -> 装备进入')
                self.device.click(EQUIPMENT_ENTER)
                continue

        self.interval_clear(STORAGE_CHECK)

    def _storage_enter_disassemble(self, skip_first_screenshot=True):
        """从任意仓库子页面切换至装备拆解面板。

        Pages:
            in: page_storage, any
            out: page_storage, disassemble, DISASSEMBLE_CANCEL

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。
        """
        logger.info('仓库进入拆解')
        self.appear(STORAGE_CHECK, interval=3)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(DISASSEMBLE_CANCEL, offset=(20, 20)):
                break

            # equipment -> disassemble
            if self.appear_then_click(DISASSEMBLE, offset=(20, 20), interval=3):
                self.interval_reset(STORAGE_CHECK)
                self.interval_reset(MATERIAL_CHECK)
                continue
            # material -> equipment
            if self._storage_in_material(interval=3):
                logger.info('_storage_in_material -> EQUIPMENT_ENTER')
                self.device.click(EQUIPMENT_ENTER)
                self.interval_reset(STORAGE_CHECK)
                continue
            # design -> equipment
            if self.appear(STORAGE_CHECK, offset=(20, 20), interval=3):
                logger.info('[存储-UI] 存储检查 -> 装备进入')
                self.device.click(EQUIPMENT_ENTER)
                continue

        self.interval_clear(STORAGE_CHECK)

    def _equipment_filter_enter(self):
        """打开装备筛选面板。"""
        logger.info('装备筛选进入')
        self.interval_clear(STORAGE_CHECK)
        for _ in self.loop():
            if self.appear(EQUIPMENT_FILTER_CONFIRM, offset=(20, 20)):
                break
            if self.appear(STORAGE_CHECK, offset=(20, 20), interval=3):
                self.device.click(EQUIPMENT_FILTER)
                continue
            if self.appear(GET_ITEMS_1, offset=(5, 5), interval=3):
                logger.info(f'{GET_ITEMS_1} -> {DISASSEMBLE_CONFIRM}')
                self.device.click(DISASSEMBLE_CONFIRM)
                continue
            if self.appear(GET_ITEMS_2, offset=(5, 5), interval=3):
                logger.info(f'{GET_ITEMS_2} -> {DISASSEMBLE_CONFIRM}')
                self.device.click(DISASSEMBLE_CONFIRM)
                continue

    def _equipment_filter_confirm(self):
        """确认并关闭装备筛选面板。"""
        logger.info('装备筛选确认')
        self.interval_clear(EQUIPMENT_FILTER_CONFIRM)
        self.ui_click(EQUIPMENT_FILTER_CONFIRM, check_button=STORAGE_CHECK, skip_first_screenshot=True)
        self._wait_until_storage_stable()

    def equipment_filter_set(self, rarity='all'):
        """设置装备稀有度筛选。

        Args:
            rarity (str | int): 稀有度筛选值，可选 ['all', 'common', 'rare', 'elite', 'super_rare', 'ultra_rare']，
                也支持数字映射：1=普通, 2=稀有, 3=精锐, 4=超稀有, 5=最高稀有。

        Pages:
            in: DISASSEMBLE
        """
        rarity_convert = {
            '1': 'common',
            '2': 'rare',
            '3': 'elite',
            '4': 'super_rare',
            '5': 'ultra_rare',
        }
        rarity = rarity_convert.get(str(rarity), rarity)
        self._equipment_filter_enter()
        self.storage_filter.set(rarity=rarity)
        self._equipment_filter_confirm()

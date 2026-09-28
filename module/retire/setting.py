"""退役设置管理模块。

管理快速退役的设置界面操作，包括进入/退出设置页面、
切换退役选项（如退役稀有度范围、保留规则等）。

QuickRetireSetting 扩展 Setting 类，适配退役设置的 UI 样式。
QuickRetireSettingHandler 提供设置页面的导航操作。

继承自 UI，利用页面导航能力。
"""

from module.base.decorator import cached_property
from module.retire.assets import *
from module.ui.setting import Setting
from module.ui.ui import UI


class QuickRetireSetting(Setting):
    """快速退役设置项。

    检测退役设置选项的激活状态。
    """

    def is_option_active(self, option: Button) -> bool:
        """检查快速退役设置项中的选项按钮是否处于激活状态。

        Args:
            option (Button): 待检测的选项按钮。

        Returns:
            bool: 激活返回 True，否则返回 False。
        """
        return self.main.image_color_count(option, color=(255, 255, 255), threshold=30, count=50)


class QuickRetireSettingHandler(UI):
    """退役设置页面导航处理器。

    提供退役设置页面的进入和退出操作。
    """

    def _retire_setting_enter(self):
        """进入一键退役设置界面。

        Pages:
            in: IN_RETIREMENT_CHECK, RETIRE_SETTING_ENTER
            out: RETIRE_SETTING_QUIT
        """
        self.ui_click(RETIRE_SETTING_ENTER, check_button=RETIRE_SETTING_QUIT,
                      offset=(30, 100), retry_wait=3, skip_first_screenshot=True)

    def _retire_setting_quit(self):
        """退出一键退役设置界面并保存。

        Pages:
            in: RETIRE_SETTING_QUIT
            out: IN_RETIREMENT_CHECK, RETIRE_SETTING_ENTER
        """
        self.ui_click(RETIRE_SETTING_QUIT, check_button=RETIRE_SETTING_ENTER,
                      offset=(30, 100), retry_wait=3, skip_first_screenshot=True)

    @cached_property
    def retire_setting(self) -> QuickRetireSetting:
        """快速退役设置项定义对象。"""
        setting = QuickRetireSetting(name='RETIRE', main=self)
        setting.reset_first = False
        setting.add_setting(
            setting='filter_1',
            option_buttons=[RETIRE_SETTING_1],
            option_names=['R'],
            option_default='R'
        )
        setting.add_setting(
            setting='filter_2',
            option_buttons=[RETIRE_SETTING_2],
            option_names=['E'],
            option_default='E'
        )
        setting.add_setting(
            setting='filter_3',
            option_buttons=[RETIRE_SETTING_3],
            option_names=['N'],
            option_default='N'
        )
        setting.add_setting(
            setting='filter_4',
            option_buttons=[RETIRE_SETTING_4],
            option_names=['all'],
            option_default='all'
        )
        setting.add_setting(
            setting='filter_5',
            option_buttons=[RETIRE_SETTING_5_PRESERVE, RETIRE_SETTING_5_ALL],
            option_names=['keep_limit_break', 'all'],
            option_default='all'
        )
        return setting

    def quick_retire_setting_set(self, filter_5='all'):
        """配置一键退役的各项过滤选项。

        前 4 项选项强制设置为：
        - 优先级稀有度 1: R（稀有）
        - 优先级稀有度 2: E（精锐）
        - 优先级稀有度 3: N（普通）
        - 已满破舰船同名船处理: 全部退役（不保留）

        Args:
            filter_5 (str, optional): 第 5 项设置（未满破舰船同名船处理规则）：
                'keep_limit_break': 保留满破所需数量；
                'all': 全部退役（不保留）；
                None: 不修改该项。默认为 'all'。

        Pages:
            in: IN_RETIREMENT_CHECK, RETIRE_SETTING_ENTER
            out: IN_RETIREMENT_CHECK, RETIRE_SETTING_ENTER
        """
        self._retire_setting_enter()
        self.retire_setting.set(filter_5=filter_5)
        self._retire_setting_quit()

    def server_support_quick_retire_setting_fallback(self):
        """检查当前服务器是否支持一键退役设置自动回退纠正。

        Returns:
            bool: 支持返回 True，否则返回 False。
        """
        return self.config.SERVER in ['cn', 'en', 'jp']

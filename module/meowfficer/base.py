"""指挥喵模块基类，提供指挥喵界面的等待和基础交互方法。
处理界面加载等待、信息弹窗关闭和每日重置时间计算。
"""

from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1
from module.config.utils import get_server_next_update
from module.logger import logger
from module.meowfficer.assets import *
from module.ui.assets import MEOWFFICER_CHECK, MEOWFFICER_INFO
from module.ui.ui import UI


class MeowfficerBase(UI):
    """指挥喵模块基类。

    提供指挥喵界面的加载等待、基础交互方法、菜单关闭与弹窗处理。
    """

    def wait_meowfficer_buttons(self, skip_first_screenshot=True):
        """等待指挥喵界面按钮加载完成。

        MEOWFFICER_INFO 和 MEOWFFICER_BUY_ENTER 加载比 MEOWFFICER_CHECK 慢，
        需要额外等待以确保界面完全加载。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

        Pages:
            in: page_meowfficer
            out: page_meowfficer（完全加载状态）
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(MEOWFFICER_BUY_ENTER, offset=(20, 20)):
                break

            # 处理指挥喵信息弹窗
            if self.ui_additional():
                continue

    def meow_additional(self):
        """处理界面切换过程中可能出现的额外弹窗（如 MEOWFFICER_INFO）。

        Returns:
            bool: 是否处理了弹窗。
        """
        if self.appear_then_click(MEOWFFICER_INFO, offset=(30, 30), interval=3):
            return True

        return False

    def meow_enter(self, click_button, check_button, skip_first_screenshot=True):
        """进入指挥喵子界面，处理 MEOWFFICER_INFO 弹窗和误触其他界面的情况。

        Args:
            click_button (Button): 进入子界面的点击按钮。
            check_button (Button): 目标子界面的确认判定按钮。
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

        Pages:
            in: page_meowfficer
            out: check_button
        """
        accident_page = [MEOWFFICER_TRAIN_START, MEOWFFICER_BUY, MEOWFFICER_FORT_CHECK]
        accident_page = [page for page in accident_page if page != check_button]
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 判定结束
            if self.appear(check_button, offset=(20, 20)):
                break
            # 点击进入按钮
            if self.appear_then_click(click_button, offset=(20, 20), interval=3):
                continue
            # 误触其他界面处理
            if self.meow_additional():
                continue
            for button in accident_page:
                if self.appear(button, offset=(20, 20), interval=3):
                    self.device.click(MEOWFFICER_CHECK)
                    self.interval_clear(click_button)
                    break

    def meow_menu_close(self, skip_first_screenshot=True):
        """关闭所有指挥喵菜单弹窗，返回指挥喵主界面。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

        Pages:
            in: MEOWFFICER_FORT_CHECK, MEOWFFICER_BUY, MEOWFFICER_TRAIN_START 等
            out: page_meowfficer
        """
        logger.hr('指挥喵-菜单关闭')
        click_timer = Timer(3)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 判定结束
            if self.match_template_color(MEOWFFICER_CHECK, offset=(20, 20)):
                break
            else:
                if click_timer.reached():
                    # MEOWFFICER_CHECK 是安全的点击位置
                    self.device.click(MEOWFFICER_CHECK)
                    click_timer.reset()
                    continue

            # 窝巢界面
            if self.appear(MEOWFFICER_FORT_CHECK, offset=(20, 20), interval=3):
                self.device.click(MEOWFFICER_CHECK)
                click_timer.reset()
                continue
            # 购买界面
            if self.appear(MEOWFFICER_BUY, offset=(20, 20), interval=3):
                self.device.click(MEOWFFICER_CHECK)
                click_timer.reset()
                continue
            # 训练界面
            if self.appear(MEOWFFICER_TRAIN_FILL_QUEUE, offset=(20, 20), interval=3):
                self.device.click(MEOWFFICER_CHECK)
                click_timer.reset()
                continue
            if self.appear(MEOWFFICER_TRAIN_FINISH_ALL, offset=(20, 20), interval=3):
                self.device.click(MEOWFFICER_CHECK)
                click_timer.reset()
                continue
            # 确认/取消及获得道具弹窗
            if self.appear(MEOWFFICER_CONFIRM, offset=(40, 20), interval=3):
                self.device.click(MEOWFFICER_CHECK)
                click_timer.reset()
                continue
            if self.appear(MEOWFFICER_CANCEL, offset=(40, 20), interval=3):
                self.device.click(MEOWFFICER_CHECK)
                click_timer.reset()
                continue
            if self.appear_then_click(GET_ITEMS_1, offset=5, interval=3):
                click_timer.reset()
                continue
            if self.meow_additional():
                click_timer.reset()
                continue

    def handle_meow_popup_confirm(self):
        """确认弹窗，允许并执行弹窗对应的操作。

        Returns:
            bool: 是否成功点击了确认按钮。
        """
        if self.appear_then_click(MEOWFFICER_CONFIRM, offset=(40, 20), interval=5):
            return True
        else:
            return False

    def handle_meow_popup_cancel(self):
        """取消弹窗，取消对应的操作并关闭弹窗。

        Returns:
            bool: 是否成功点击了取消按钮。
        """
        if self.appear_then_click(MEOWFFICER_CANCEL, offset=(40, 20), interval=5):
            return True
        else:
            return False

    def handle_meow_popup_dismiss(self):
        """关闭弹窗，点击安全空白区域退出弹窗（既不确认也不取消）。

        Returns:
            bool: 是否检测到弹窗并点击了空白安全区域。
        """
        if self.appear(MEOWFFICER_CONFIRM, offset=(40, 20), interval=5):
            self.device.click(MEOWFFICER_CHECK)
            return True
        elif self.appear(MEOWFFICER_CANCEL, offset=(40, 20), interval=5):
            self.device.click(MEOWFFICER_CHECK)
            return True
        else:
            return False

    def meow_is_sunday(self):
        """判断游戏服务器当前日期是否为周日。

        由于传入的基准时间是下一次服务器刷新时间，因此通过判断下次刷新是否为周一（weekday 值为 0）
        来确认当前运营日是否为周日。

        Returns:
            bool: 当前为周日返回 True，否则返回 False。
        """
        return get_server_next_update(self.config.Scheduler_ServerUpdate).weekday() == 0

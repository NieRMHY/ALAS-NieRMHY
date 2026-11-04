"""离线验证 B 站登录记录弹窗的识别、点击和登录流程。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import module.config.server as server

# 游戏资源须在导入前选定服务器。
server.server = 'cn'

from module.base.utils import load_image
from module.handler.assets import BILIBILI_LOGIN_BUTTON, BILIBILI_LOGIN_RECORD, LOGIN_CHECK
from module.handler.login import LoginHandler
from module.ui.page import page_main
from module.ui.ui import UI


RECORD_IMAGE = Path(__file__).parent / 'fixtures' / 'bilibili_login_record' / 'record.png'


def make_ui(cls=UI, image=None, package='com.bilibili.azurlane', server_name='cn'):
    ui = object.__new__(cls)
    ui.config = SimpleNamespace(
        SERVER=server_name,
        BUTTON_OFFSET=(30, 30),
        data={'Alas': {'Emulator': {'PackageName': package}}},
    )
    ui.device = Mock(image=load_image(str(RECORD_IMAGE)) if image is None else image.copy())
    ui.interval_timer = {}
    return ui


class BilibiliLoginRecordTests(unittest.TestCase):
    def test_record_and_login_button_match_redacted_screenshot(self):
        ui = make_ui()
        self.assertTrue(ui.match_template_color(BILIBILI_LOGIN_RECORD, offset=(5, 5)))
        self.assertTrue(ui.appear(BILIBILI_LOGIN_BUTTON, offset=(5, 5)))
        self.assertTrue(ui.handle_bilibili_login_record())
        ui.device.click.assert_called_once_with(BILIBILI_LOGIN_BUTTON)
        self.assertEqual(BILIBILI_LOGIN_BUTTON.button, (604, 383, 676, 425))

    def test_account_area_does_not_affect_detection(self):
        image = load_image(str(RECORD_IMAGE))
        image[258:338, 430:850] = 0
        ui = make_ui(image=image)
        self.assertTrue(ui.handle_bilibili_login_record())
        ui.device.click.assert_called_once_with(BILIBILI_LOGIN_BUTTON)

    def test_missing_title_or_button_does_not_click(self):
        image = load_image(str(RECORD_IMAGE))
        for area in ((140, 223, 563, 716), (383, 425, 604, 676)):
            with self.subTest(area=area):
                changed = image.copy()
                top, bottom, left, right = area
                changed[top:bottom, left:right] = 0
                ui = make_ui(image=changed)
                self.assertFalse(ui.handle_bilibili_login_record())
                ui.device.click.assert_not_called()

    def test_only_cn_bilibili_client_is_handled(self):
        for package, server_name in (('com.bilibili.blhx.m4399', 'cn'),
                                     ('com.bilibili.azurlane', 'en')):
            with self.subTest(package=package, server=server_name):
                ui = make_ui(package=package, server_name=server_name)
                self.assertFalse(ui.handle_bilibili_login_record())
                ui.device.click.assert_not_called()

    def test_normal_login_screen_is_untouched(self):
        ui = make_ui(image=load_image(LOGIN_CHECK.file))
        self.assertFalse(ui.handle_bilibili_login_record())
        ui.device.click.assert_not_called()

    def test_navigation_popup_chain_handles_record(self):
        ui = make_ui()
        ui.ui_page_os_popups = Mock(return_value=False)
        ui.handle_popup_confirm = Mock(return_value=False)
        ui.handle_urgent_commission = Mock(return_value=False)
        ui.ui_page_main_popups = Mock(return_value=False)
        ui.handle_story_skip = Mock(return_value=False)
        self.assertTrue(ui.ui_additional())
        ui.device.click.assert_called_once_with(BILIBILI_LOGIN_BUTTON)

    def test_login_loop_continues_to_main_page_after_record(self):
        login = make_ui(cls=LoginHandler)
        record_image = login.device.image.copy()
        login_image = load_image(LOGIN_CHECK.file)
        main_image = load_image(page_main.check_button.file)
        login.handle_cn_user_agreement = Mock(return_value=False)
        login.handle_popup_confirm = Mock(return_value=False)
        login.handle_urgent_commission = Mock(return_value=False)
        login.ui_page_main_popups = Mock(return_value=False)
        clock = [100.0]

        def screenshot():
            count = login.device.screenshot.call_count
            if count > 20:
                self.fail('登录循环没有在主界面确认后退出')
            clock[0] += 1
            if count == 1:
                login.device.image = record_image.copy()
            elif count == 2:
                login.device.image = login_image.copy()
            else:
                login.device.image = main_image.copy()

        login.device.screenshot.side_effect = screenshot
        with patch('module.base.timer.time', side_effect=lambda: clock[0]):
            self.assertTrue(login._handle_app_login())

        self.assertTrue(login.is_in_main())
        self.assertEqual(login.device.click.call_args_list,
                         [call(BILIBILI_LOGIN_BUTTON), call(LOGIN_CHECK)])
        login.device.app_stop.assert_not_called()
        login.device.app_start.assert_not_called()


if __name__ == '__main__':
    unittest.main()

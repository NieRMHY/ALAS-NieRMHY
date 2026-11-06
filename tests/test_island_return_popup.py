"""岛屿返回主界面时的弹窗处理回归测试。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import module.config.server as server
import numpy as np

server.server = 'cn'

from module.base.utils import load_image
from module.combat.assets import GET_SHIP
from module.handler.assets import GUILD_POPUP_CANCEL, GUILD_POPUP_CONFIRM
from module.ui.ui import UI


FIXTURES = Path(__file__).parent / 'fixtures' / 'island_return_popup'


class IslandReturnPopupTests(unittest.TestCase):
    def test_issue_screenshot_recognizes_and_dismisses_guild_popup(self):
        image = load_image(str(FIXTURES / 'guild_popup.png'))
        self.assertTrue(GUILD_POPUP_CANCEL.match(image, offset=(3, 30)))
        self.assertTrue(GUILD_POPUP_CONFIRM.match(image, offset=(3, 30)))

        ui = object.__new__(UI)
        ui.config = SimpleNamespace(SERVER='cn', BUTTON_OFFSET=(30, 30), data={})
        ui.device = Mock(image=image)
        ui.interval_timer = {}
        ui.ui_current = SimpleNamespace(name='page_island_phone')
        ui.ui_page_os_popups = Mock(return_value=False)
        ui.handle_popup_confirm = Mock(return_value=False)
        ui.handle_urgent_commission = Mock(return_value=False)

        self.assertTrue(ui.ui_additional())
        ui.device.click.assert_called_once_with(GUILD_POPUP_CANCEL)

    def test_guild_popup_is_handled_while_island_page_is_cached(self):
        ui = object.__new__(UI)
        ui.ui_current = SimpleNamespace(name='page_island_phone')
        ui.handle_guild_popup_cancel = Mock(return_value=True)
        ui.appear = Mock(return_value=False)
        ui.appear_then_click = Mock(return_value=False)

        self.assertTrue(ui.ui_page_main_popups())
        ui.handle_guild_popup_cancel.assert_called_once_with()
        clicked_buttons = [call.args[0] for call in ui.appear_then_click.call_args_list]
        self.assertNotIn(GET_SHIP, clicked_buttons)

    def test_island_page_skips_get_ship_but_main_page_handles_it(self):
        image = np.maximum(
            np.zeros((720, 1280, 3), dtype=np.uint8),
            load_image(GET_SHIP.file),
        )

        for page, expected in (('page_island_management', False), ('page_main', True)):
            with self.subTest(page=page):
                ui = object.__new__(UI)
                ui.config = SimpleNamespace(SERVER='cn', BUTTON_OFFSET=(30, 30), data={})
                ui.device = Mock(image=image)
                ui.interval_timer = {}
                ui.ui_current = SimpleNamespace(name=page)

                self.assertEqual(ui.ui_page_main_popups(), expected)
                if expected:
                    ui.device.click.assert_called_once_with(GET_SHIP)


if __name__ == '__main__':
    unittest.main()

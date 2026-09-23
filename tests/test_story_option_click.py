"""验证剧情选项的连点保护。

剧情选项按钮名按「第几个/共几个」生成（STORY_OPTION_2_OF_3），不同剧情段
共用同一个名字；装置 / 柱子较多的海域会因此被防连点机制误判为
「两个按钮交替点击次数过多」而报 GameTooManyClickError。

用例锁定两件事：
1. 连续处理大量柱子 / 装置（同名按钮复用）不再触发防连点机制；
2. 剧情真的卡在选项画面时，仍然会报 GameTooManyClickError。
"""

import collections
import unittest
from types import SimpleNamespace

from module.base.button import Button
from module.exception import GameTooManyClickError
from module.handler.assets import STORY_SKIP_3
from module.handler.info_handler import InfoHandler


def make_options(count=3):
    """构造与 _story_option_buttons_2 同名的选项按钮。"""
    return [
        Button(area=(330, 200 + n * 60, 980, 250 + n * 60), color=(247, 247, 247),
               button=(330, 200 + n * 60, 980, 250 + n * 60), name=f'STORY_OPTION_{n + 1}_OF_{count}')
        for n in range(count)
    ]


class FakeTimer:
    def __init__(self, reached=False, started=False):
        self._reached = reached
        self.started_ = started

    def reached(self):
        return self._reached

    def started(self):
        return self.started_

    def start(self):
        self.started_ = True
        return self

    def reset(self):
        pass

    def clear(self):
        pass


class FakeDevice:
    """复刻 device.click_record_check 的规则。

    最近 15 次点击中，同一个按钮 ≥12 次，或两个按钮各 ≥6 次即报错。
    """

    def __init__(self):
        self.click_record = collections.deque(maxlen=15)
        self.history = []
        self.clears = 0

    def click(self, button, **kwargs):
        self.history.append(str(button))
        self.click_record.append(str(button))
        self._check()

    def click_record_clear(self):
        self.clears += 1
        self.click_record.clear()

    def count_of(self, prefix):
        """某个按钮名（前缀）一共被点了多少次。"""
        return sum(1 for name in self.history if name.startswith(prefix))

    def _check(self):
        count = collections.Counter(self.click_record).most_common(2)
        if count and count[0][1] >= 12:
            raise GameTooManyClickError(f'[设备-点击] 按钮点击次数过多: {count[0][0]}')
        if len(count) >= 2 and count[0][1] >= 6 and count[1][1] >= 6:
            raise GameTooManyClickError(
                f'[设备-点击] 两个按钮交替点击次数过多: {count[0][0]}, {count[1][0]}')


class StoryHandlerStub(InfoHandler):
    """替换画面识别相关接口，保留真实的剧情选项选择与点击记录逻辑。"""

    def __init__(self, story_option=-2, options=None):
        self.config = SimpleNamespace(
            STORY_OPTION=story_option,
            STORY_ALLOW_SKIP=False,
            task=SimpleNamespace(command='OpsiHazard1Leveling'),
            cross_get=lambda keys, default=None: default,
        )
        self.device = FakeDevice()
        self._options = options if options is not None else make_options()
        self.story_present = True
        self.siren_device_mode = None
        self.interval_timer = {}
        self._story_option_timer = FakeTimer(reached=True)
        self._story_option_confirm = FakeTimer(reached=True)
        self.story_popup_timeout = FakeTimer(reached=False, started=False)

    # ---- 桩 ----
    def appear(self, button, **kwargs):
        if button is STORY_SKIP_3:
            return self.story_present
        return False

    def appear_then_click(self, button, **kwargs):
        return False

    def _is_story_black(self):
        return False

    def _story_option_buttons_2(self):
        return self._options

    def handle_popup_confirm(self, name='', **kwargs):
        """模拟确认弹窗点击：记录的名字带 name 后缀。"""
        button = Button(area=(754, 502, 825, 532), color=(153, 183, 222),
                        button=(754, 502, 825, 532), name=f'POPUP_CONFIRM_{name}')
        self.device.click(button)
        return True


class TestStoryOptionClickGuard(unittest.TestCase):
    def enter_option_screen(self, handler):
        """画面为剧情选项。"""
        handler.story_present = True
        handler.story_popup_timeout.started_ = False

    def enter_confirm_popup(self, handler):
        """画面为提交确认弹窗。"""
        handler.story_present = True
        handler.story_popup_timeout.started_ = True

    def leave_story(self, handler):
        """剧情结束，回到地图。"""
        handler.story_present = False
        handler.story_popup_timeout.started_ = False

    def click_until(self, handler, prefix, setup, limit=4):
        """模拟真实循环反复调用 story_skip，直到某个按钮被点击。"""
        before = handler.device.count_of(prefix)
        for _ in range(limit):
            setup(handler)
            handler.story_skip()
            if handler.device.count_of(prefix) > before:
                return True
        return False

    def submit_device(self, handler):
        """一个完整的柱子 / 装置提交：点选项 -> 点确认 -> 剧情结束。"""
        self.assertTrue(self.click_until(handler, 'STORY_OPTION_', self.enter_option_screen))
        self.assertTrue(self.click_until(handler, 'POPUP_CONFIRM_', self.enter_confirm_popup))
        self.leave_story(handler)
        handler.story_skip()

    def test_many_devices_do_not_trip_click_guard(self):
        """一张图里连续提交 30 次柱子 / 装置，不应报连点异常。"""
        handler = StoryHandlerStub(story_option=-2)
        for n in range(30):
            with self.subTest(device=n):
                self.submit_device(handler)
        self.assertEqual(handler.device.count_of('STORY_OPTION_2_OF_3'), 30)
        self.assertEqual(handler.device.count_of('POPUP_CONFIRM_STORY_SKIP'), 30)
        # 每次剧情点击都清空了点击记录
        self.assertGreaterEqual(handler.device.clears, 60)
        self.assertEqual(handler.siren_device_mode, 'collected')

    def test_special_zone_story_option_does_not_trip_click_guard(self):
        """深渊 / 隐秘等海域点第一项时同样不累积点击记录。"""
        handler = StoryHandlerStub(story_option=0)
        option = handler._options[0].name
        for n in range(30):
            with self.subTest(device=n):
                self.assertTrue(self.click_until(handler, option, self.enter_option_screen))
                self.leave_story(handler)
                handler.story_skip()
        self.assertEqual(handler.device.count_of(option), 30)
        self.assertIsNone(handler.siren_device_mode)

    def test_stuck_story_option_still_raises(self):
        """选项画面点不动（不出现确认弹窗、剧情不推进）时仍要报错。"""
        handler = StoryHandlerStub(story_option=-2)
        with self.assertRaises(GameTooManyClickError) as context:
            for _ in range(30):
                self.enter_option_screen(handler)
                handler.story_skip()
        self.assertIn('剧情', str(context.exception))

    def test_streak_resets_when_story_ends(self):
        """剧情结束后计数清零，历史点击不会误伤下一段剧情。"""
        handler = StoryHandlerStub(story_option=-2)
        for _ in range(11):
            self.assertTrue(self.click_until(handler, 'STORY_OPTION_', self.enter_option_screen))

        self.leave_story(handler)
        self.assertFalse(handler.story_skip())
        self.assertEqual(handler._story_option_click, 0)

        for _ in range(11):
            self.assertTrue(self.click_until(handler, 'STORY_OPTION_', self.enter_option_screen))


if __name__ == '__main__':
    unittest.main()

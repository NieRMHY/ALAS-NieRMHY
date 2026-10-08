"""用虚拟画面验证自律、任务中断及特殊海域退出的掉落采集。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.config.config import TaskEnd
from module.os.fleet import BossFleet, OSFleet
from module.os.map import OSMap
from module.os.map_operation import OSMapOperation
from module.os_handler.assets import AUTO_SEARCH_REWARD
from module.statistics.azurstats import DropImage


class TestOpsiDropCapture(unittest.TestCase):
    def test_auto_search_passes_collector_to_map_rewards(self):
        handler = OSMap.__new__(OSMap)
        handler.config = SimpleNamespace(
            task=SimpleNamespace(command='OpsiObscure'), OpsiGeneral_AutoSearchTimeLimit=10,
        )
        handler.device = Mock()
        handler.loop = Mock(return_value=range(1))
        handler.on_auto_search_battle_count_reset = Mock()
        handler.hp_reset = Mock()
        handler.is_in_map = Mock(return_value=False)
        handler.appear = Mock(return_value=True)
        handler.handle_os_auto_search_map_option = Mock(return_value=False)
        handler.handle_retirement = Mock(return_value=False)
        handler.combat_appear = Mock(return_value=False)
        handler.handle_map_event = Mock(return_value=True)
        drop = Mock()
        handler.os_auto_search_daemon(drop=drop)
        handler.handle_map_event.assert_called_once_with(drop=drop)

    def interrupt_handler(self):
        handler = OSMap.__new__(OSMap)
        handler.config = SimpleNamespace(task_stop=Mock(side_effect=TaskEnd))
        handler.device = Mock(image=object())
        handler.is_in_main = Mock(side_effect=[False, True])
        handler.is_combat_executing = Mock(return_value=False)
        handler.handle_combat_quit = Mock(return_value=False)
        handler.handle_combat_quit_reconfirm = Mock(return_value=False)
        handler.ui_additional = Mock(return_value=False)
        handler.handle_map_event = Mock(return_value=True)
        handler.interval_clear = Mock()
        handler.appear_then_click = Mock(return_value=False)
        return handler

    def test_interruption_keeps_summary_before_closing_it(self):
        handler = self.interrupt_handler()
        handler.appear = Mock(return_value=True)
        drop = Mock()
        with self.assertRaises(TaskEnd):
            handler.interrupt_auto_search(drop=drop)
        drop.add.assert_called_once_with(handler.device.image)
        handler.device.click.assert_called_once_with(AUTO_SEARCH_REWARD)

    def test_interruption_passes_collector_to_popup_handler(self):
        handler = self.interrupt_handler()
        handler.appear = Mock(return_value=False)
        drop = Mock()
        with self.assertRaises(TaskEnd):
            handler.interrupt_auto_search(drop=drop)
        handler.handle_map_event.assert_called_once_with(drop=drop)

    def test_map_exit_captures_summary_and_popup_rewards(self):
        handler = OSMapOperation.__new__(OSMapOperation)
        handler.device = Mock()
        handler.is_in_map = Mock(side_effect=lambda: handler.frame == 'map')
        handler.appear = Mock(side_effect=lambda button, **kwargs: button is AUTO_SEARCH_REWARD and handler.frame == 'reward')
        handler.appear_then_click = Mock(return_value=False)
        handler.handle_popup_confirm = Mock(return_value=False)
        handler.handle_map_event = Mock(side_effect=lambda **kwargs: handler.frame == 'popup')
        handler.interval_reset = Mock()
        handler.zone_init = Mock()

        def frames():
            for frame in ('reward', 'popup', 'map'):
                handler.frame = frame
                handler.device.image = frame
                yield frame

        handler.loop = frames
        drop = Mock()
        with patch('module.os.map_operation.Timer', return_value=Mock(reached=Mock(return_value=True))):
            handler.map_exit(drop=drop)
        drop.add.assert_called_once_with('reward')
        handler.handle_map_event.assert_called_once_with(drop=drop)
        handler.zone_init.assert_called_once()

    def test_obscure_exit_rewards_are_committed_with_auto_search(self):
        handler = OSMap.__new__(OSMap)
        handler.config = SimpleNamespace(
            task=SimpleNamespace(command='OpsiObscure'), DropRecord_OpsiObscure='upload',
        )
        handler.device = Mock(image='source-map')
        handler.stat = Mock()
        drop = DropImage(handler.stat, 'opsi_obscure', save=False, local=True)
        handler.stat.new.return_value = drop
        handler.handle_ash_beacon_attack = Mock()
        handler.hp_reset = Mock()
        handler.hp_get = Mock()
        handler._auto_search_battle_count = 1

        def search(collector, **kwargs):
            collector.add('search-reward')
            return 1

        handler.os_auto_search_run = search
        handler.map_exit = Mock(side_effect=lambda **kwargs: kwargs['drop'].add('exit-reward'))
        result = handler.run_auto_search(question=False, rescan=False, after_auto_search=False, exit_map=True)
        self.assertEqual(result, 1)
        handler.map_exit.assert_called_once_with(drop=drop)
        self.assertEqual(handler.stat.commit.call_args.kwargs['images'], ['search-reward', 'source-map', 'exit-reward'])

    def test_strategic_task_end_keeps_a_single_captured_reward(self):
        handler = OSMap.__new__(OSMap)
        handler.config = SimpleNamespace(
            task=SimpleNamespace(command='OpsiMeowfficerFarming'), DropRecord_OpsiMeowfficerFarming='upload',
        )
        handler.stat = Mock()
        drop = DropImage(handler.stat, 'opsi_meowfficer_farming', save=False, local=True)
        handler.stat.new.return_value = drop
        handler.handle_ash_beacon_attack = Mock()
        handler._auto_search_battle_count = 1

        def search(collector, **kwargs):
            collector.add('interrupt-reward')
            raise TaskEnd

        handler.os_auto_search_run = search
        with self.assertRaises(TaskEnd):
            handler.run_strategic_search()
        self.assertEqual(handler.stat.commit.call_args.kwargs['images'], ['interrupt-reward'])

    def test_boss_clear_passes_collector_through_map_exit(self):
        handler = OSFleet.__new__(OSFleet)
        handler.config = SimpleNamespace(
            task=SimpleNamespace(command='OpsiMonthBoss'), DropRecord_OpsiAbyssal='upload',
        )
        handler.stat = Mock()
        handler.device = Mock(image='boss-map')
        drop = DropImage(handler.stat, 'opsi_month_boss', save=False, local=True)
        handler.stat.new.return_value = drop
        handler.parse_fleet_filter = Mock(return_value=[BossFleet(1)])
        handler.fleet_set = Mock(return_value=True)
        handler.handle_os_map_fleet_lock = Mock()
        handler.fleet_low_resolve_appear = Mock(return_value=False)
        handler.radar = Mock(select=Mock(return_value=[True]))
        handler.predict_radar = Mock()
        handler.boss_goto = Mock(side_effect=lambda **kwargs: kwargs['drop'].add('boss-reward'))
        handler.map_exit = Mock(side_effect=lambda **kwargs: kwargs['drop'].add('boss-exit-reward'))
        self.assertTrue(handler.boss_clear(is_month=True))
        handler.map_exit.assert_called_once_with(drop=drop)
        self.assertEqual(handler.stat.commit.call_args.kwargs['images'], ['boss-reward', 'boss-map', 'boss-exit-reward'])


if __name__ == '__main__':
    unittest.main()

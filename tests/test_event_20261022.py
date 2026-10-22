"""飓风与雾霭回廊的跨服导航、关卡接入与固定 SP 敌人回归。"""

import copy
import importlib
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, call

from campaign.event_20261022_cn import sp, t1
from module.config.config import AzurLaneConfig
from module.exception import CampaignNameError


EVENT = 'event_20261022_cn'
ROOT = Path(__file__).resolve().parents[1]


class NavigationConfig(AzurLaneConfig):
    # 只替换导航配置的服务器名，不切换进程内已加载的游戏资源。
    SERVER = 'cn'


def make_campaign(map_module=t1, server='cn'):
    config = NavigationConfig('template')
    config.override(SERVER=server)
    config.merge(map_module.Config())
    campaign = map_module.Campaign(config=config, device=Mock())
    campaign.navigation = Mock()
    for name in ('ui_goto_sp', 'campaign_ensure_mode_20241219',
                 'campaign_ensure_aside_20241219', 'campaign_ensure_chapter'):
        method = Mock()
        campaign.navigation.attach_mock(method, name)
        setattr(campaign, name, method)
    return campaign


class WindFogCorridorTests(unittest.TestCase):
    def test_stage_routes_use_correct_part_on_all_supported_servers(self):
        for server in ('cn', 'en', 'jp'):
            for stage, aside in ((1, 'part1'), (2, 'part1'), (3, 'part1'),
                                 (4, 'part2'), (5, 'part2'), (6, 'part2')):
                with self.subTest(server=server, stage=stage):
                    module = importlib.import_module(f'campaign.{EVENT}.t{stage}')
                    campaign = make_campaign(module, server)
                    campaign.campaign_set_chapter(f't{stage}')
                    self.assertEqual(campaign.navigation.mock_calls, [
                        call.ui_goto_sp(),
                        call.campaign_ensure_mode_20241219('combat'),
                        call.campaign_ensure_aside_20241219(aside),
                        call.campaign_ensure_chapter('t'),
                    ])
                    self.assertFalse(campaign.config.MAP_HAS_MODE_SWITCH)
                    self.assertFalse(campaign.config.MAP_CHAPTER_SWITCH_20260326)
                    self.assertEqual(campaign.config.modified, {})
                    campaign.device.click.assert_not_called()

    def test_daily_sp_uses_sp_partition_without_difficulty_switch(self):
        for server in ('cn', 'en', 'jp'):
            with self.subTest(server=server):
                campaign = make_campaign(sp, server)
                campaign.campaign_set_chapter('sp')
                self.assertEqual(campaign.navigation.mock_calls, [
                    call.ui_goto_sp(),
                    call.campaign_ensure_mode_20241219('combat'),
                    call.campaign_ensure_aside_20241219('sp'),
                    call.campaign_ensure_chapter('ex_sp'),
                ])
                self.assertTrue(campaign.config.MAP_IS_ONE_TIME_STAGE)
                self.assertFalse(campaign.config.MAP_HAS_MODE_SWITCH)

    def test_invalid_t_stage_does_not_navigate(self):
        campaign = make_campaign()
        with self.assertRaises(CampaignNameError):
            campaign.campaign_set_chapter('t7')
        campaign.navigation.assert_not_called()
        self.assertEqual(campaign.navigation.mock_calls, [])
        campaign.device.click.assert_not_called()

    def test_sp_initialization_restores_only_fixed_sirens_each_sortie(self):
        campaign = make_campaign(sp)
        campaign.map_is_clear_mode = False
        map_ = copy.deepcopy(sp.MAP)
        expected = {(3, 1), (2, 2), (1, 3)}
        for _ in range(2):
            campaign.map_data_init(map_)
            self.assertEqual({grid.location for grid in map_.select(is_siren=True)}, expected)
            for grid in map_.select(is_siren=True):
                grid.wipe_out()
        self.assertFalse(campaign.config.MAP_HAS_MOVABLE_ENEMY)
        self.assertFalse(campaign.config.MAP_SIREN_HAS_BOSS_ICON_SMALL)
        self.assertEqual(campaign.config.MAP_SIREN_TEMPLATE, [])

    def test_registered_event_uses_shared_directory_for_cn_en_jp(self):
        args = json.loads((ROOT / 'module/config/argument/args.json').read_text(encoding='utf-8'))
        for task in ('Event', 'Event2', 'Event3', 'EventA', 'EventB', 'EventC', 'EventD', 'EventSp'):
            for server in ('cn', 'en', 'jp'):
                with self.subTest(task=task, server=server):
                    self.assertEqual(args[task]['Campaign']['Event'][f'option_{server}'], [EVENT])

    def test_localized_event_names_survive_config_generation(self):
        for language, expected in (
            ('zh-CN', '飓风与雾霭回廊'),
            ('en-US', 'Tempesta and the Corridor of Mist'),
            ('ja-JP', 'テンペスタと霧靄回廊'),
        ):
            with self.subTest(language=language):
                path = ROOT / f'module/config/i18n/{language}.json'
                translated = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(translated['Campaign']['Event'][EVENT], expected)


if __name__ == '__main__':
    unittest.main()

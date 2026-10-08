"""离线验证大世界各类领奖帧的接收及局部识别失败后的保留行为。"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from module.azur_stats.image.get_items import GetItems, GetItemsCoveredByInfoBar
from module.azur_stats.image.opsi_zone import DataOpsiZone
from module.azur_stats.scene.operation_siren import SceneOperationSiren
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_ITEMS_3


class SceneStub(SceneOperationSiren):
    def __init__(self, frames):
        self.images = frames
        self.server = 'cn'
        self.__dict__['imgid'] = 'scene-test'

    def is_opsi_zone(self, frame):
        return frame == 'map'

    def parse_opsi_zone(self, frame):
        return DataOpsiZone('Test zone', 'STRONGHOLD', 1, 6)

    def is_get_items(self, frame):
        return frame in ('popup', 'covered')

    def parse_get_items(self, frame):
        if frame == 'covered':
            raise GetItemsCoveredByInfoBar('get_items image has info_bar')
        yield SimpleNamespace(name='GearDesignPlanT5', amount=1, tag=None)

    def is_opsi_reward(self, frame):
        return frame == 'reward'

    def parse_auto_search_reward(self, frame):
        yield SimpleNamespace(name='PlateGeneralT4', amount=2, tag='meow')


class TestOpsiDropScene(unittest.TestCase):
    def test_each_supported_popup_is_classified(self):
        parser = GetItems()
        for target in (GET_ITEMS_1, GET_ITEMS_2, GET_ITEMS_3):
            with self.subTest(target=target.name), patch.object(
                parser, 'classify_server', side_effect=lambda button, image: 'cn' if button is target else ''
            ):
                self.assertTrue(parser.is_get_items(None))

    def test_non_reward_image_is_not_a_popup(self):
        parser = GetItems()
        with patch.object(parser, 'classify_server', return_value=''):
            self.assertFalse(parser.is_get_items(None))

    def test_bad_popup_preserves_other_rewards_in_the_same_record(self):
        rows = list(SceneStub(['popup', 'covered', 'reward', 'map']).parse_scene())
        self.assertEqual([(row.item, row.amount) for row in rows], [('GearDesignPlanT5', 1), ('PlateGeneralT4', 2)])
        self.assertTrue(all(row.zone_type == 'STRONGHOLD' for row in rows))

    def test_no_map_frame_still_records_rewards(self):
        rows = list(SceneStub(['covered', 'reward']).parse_scene())
        self.assertEqual([(row.item, row.amount, row.zone_type) for row in rows], [('PlateGeneralT4', 2, 'UNKNOWN')])

    def test_zone_failure_preserves_rewards_without_guessing_location(self):
        scene = SceneStub(['reward', 'map'])
        with patch.object(scene, 'parse_opsi_zone', side_effect=ValueError('unreadable zone')):
            rows = list(scene.parse_scene())
        self.assertEqual(rows[0].zone_id, 0)
        self.assertEqual(rows[0].hazard_level, 0)
        self.assertEqual(rows[0].amount, 2)

    def test_rewards_after_map_keep_existing_log_and_scan_tags(self):
        rows = list(SceneStub(['map', 'popup', 'reward']).parse_scene())
        self.assertEqual([row.tag for row in rows], ['log', 'scan'])


if __name__ == '__main__':
    unittest.main()

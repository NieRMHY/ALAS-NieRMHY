"""活动候选按实例地区隔离，旧值与运行器一致且读取不写盘。"""

import copy
import hashlib
import json
import tempfile
import unittest

from module.api.config_service import ConfigService
from module.api.protocol import ApiError, ConfigChange
from module.config.config_updater import COALITIONS, EVENTS, GEMS_FARMINGS, RAIDS, ConfigUpdater
from tests.test_api import fixture


class CampaignConfigOptionsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.configs = ConfigService(fixture(temporary.name))

    def legacy(self, package='com.bilibili.azurlane'):
        path = self.configs.path('testpilot')
        values = self.configs.read_json(path)
        values['Alas']['Emulator'].update(PackageName=package, ServerName='cn_android-0')
        for task in EVENTS + RAIDS + COALITIONS + GEMS_FARMINGS:
            values[task]['Campaign']['Event'] = 'event_20241219_cn'
        path.write_text(json.dumps(values), encoding='utf-8')
        return path, values

    def test_read_matches_runtime_for_each_region_without_writing(self):
        schema = copy.deepcopy(self.configs.args)
        for package, region in (
            ('com.bilibili.azurlane', 'cn'), ('com.bilibili.blhx.huawei', 'cn'),
            ('com.YoStarEN.AzurLane', 'en'), ('com.YoStarJP.AzurLane', 'jp'),
            ('com.hkmanjuu.azurlane.gp', 'tw'), ('com.hkmanjuu.azurlane.gp.mc', 'tw'),
            ('auto', 'cn'),
        ):
            with self.subTest(package=package):
                path, legacy = self.legacy(package)
                before = path.read_bytes(), path.stat().st_mtime_ns
                current = self.configs.get('testpilot')
                runtime = ConfigUpdater().config_update(legacy)
                for task in EVENTS + RAIDS + COALITIONS + GEMS_FARMINGS:
                    candidates = self.configs.args[task]['Campaign']['Event'][f'option_{region}']
                    self.assertEqual(candidates, current['options'][f'{task}.Campaign.Event'])
                    self.assertEqual(runtime[task]['Campaign']['Event'], current['values'][task]['Campaign']['Event'])
                self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
                self.assertEqual(hashlib.sha256(before[0]).hexdigest(), current['revision'])
        self.assertEqual(schema, self.configs.args)

    def test_each_current_event_is_preserved_when_multiple_events_are_open(self):
        path, values = self.legacy()
        self.configs.args['Event']['Campaign']['Event']['option_cn'] = ['first', 'second']
        values['Event']['Campaign']['Event'] = 'second'
        path.write_text(json.dumps(values), encoding='utf-8')
        current = self.configs.get('testpilot')
        self.assertEqual('second', current['values']['Event']['Campaign']['Event'])
        self.assertEqual(['first', 'second'], current['options']['Event.Campaign.Event'])

    def test_cross_region_choice_rejects_entire_transaction(self):
        path, _ = self.legacy()
        before = path.read_bytes()
        taiwan = self.configs.args['Event']['Campaign']['Event']['option_tw'][0]
        with self.assertRaises(ApiError) as caught:
            self.configs.patch('testpilot', None, [
                ConfigChange(path='Alas.Emulator.Serial', value='should-not-save'),
                ConfigChange(path='Event.Campaign.Event', value=taiwan),
            ])
        self.assertEqual('INVALID_PARAMS', caught.exception.code)
        self.assertEqual(before, path.read_bytes())

    def test_batch_uses_final_package_regardless_of_field_order(self):
        taiwan = self.configs.args['Event']['Campaign']['Event']['option_tw'][0]
        package = ConfigChange(path='Alas.Emulator.PackageName', value='com.hkmanjuu.azurlane.gp')
        event = ConfigChange(path='Event.Campaign.Event', value=taiwan)
        for changes in ([event, package], [package, event]):
            with self.subTest(changes=changes):
                self.legacy()
                current = self.configs.patch('testpilot', None, changes)
                self.assertEqual(taiwan, current['values']['Event']['Campaign']['Event'])
                self.assertEqual([taiwan], current['options']['Event.Campaign.Event'])

    def test_package_change_refreshes_options_and_other_instances_stay_isolated(self):
        self.legacy()
        self.configs.create('other')
        taiwan = self.configs.args['Event']['Campaign']['Event']['option_tw'][0]
        current = self.configs.patch('testpilot', None, [
            ConfigChange(path='Alas.Emulator.PackageName', value='com.hkmanjuu.azurlane.gp'),
        ])
        self.assertEqual(taiwan, current['values']['Event']['Campaign']['Event'])
        other = self.configs.get('other')
        self.assertNotIn(taiwan, other['options']['Event.Campaign.Event'])

    def test_archives_and_main_campaign_are_preserved(self):
        path, values = self.legacy()
        archive = self.configs.args['WarArchives']['Campaign']['Event']['option_cn'][-1]
        values['WarArchives']['Campaign']['Event'] = archive
        main = copy.deepcopy(values['Main']['Campaign'])
        path.write_text(json.dumps(values), encoding='utf-8')
        current = self.configs.get('testpilot')['values']
        self.assertEqual(archive, current['WarArchives']['Campaign']['Event'])
        self.assertEqual(main, current['Main']['Campaign'])


if __name__ == '__main__':
    unittest.main()

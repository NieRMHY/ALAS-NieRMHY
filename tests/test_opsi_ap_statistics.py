"""行动力曲线只使用完整总量；当前读数和海里数不能伪造总量。"""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.api.statistics_service import report
from module.log_res.log_res import LogRes
from module.os_handler.action_point import ActionPointHandler
from module.statistics.cl1_database import Cl1Database
from module.statistics.opsi_month import get_asset_timeline
from module.statistics.opsi_runtime import finish_meow_search_timer, record_ap_snapshot


class ActionPointObservationTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            config_name='isolated', task=SimpleNamespace(command='OpsiHazard1Leveling'),
            data={'Dashboard': {'ActionPoint': {'Value': 89, 'Total': 7289, 'Record': None}}},
            modified={}, _action_point_total_with_box=99999,
        )
        self.recorder = LogRes(self.config)
        self.recorder.__dict__['groups'] = {'ActionPoint': {}}
        self.recorder.__dict__['_observe'] = Mock()
        self.recorder.__dict__['_record_all_resource_snapshot'] = Mock()
        self.snapshot = self.enterContext(patch('module.statistics.opsi_runtime.record_ap_snapshot'))

    def test_current_only_updates_dashboard_without_a_total_snapshot(self):
        self.recorder.record('ActionPoint', {'Value': 123})
        self.assertEqual(self.config.modified['Dashboard.ActionPoint.Value'], 123)
        self.assertNotIn('Dashboard.ActionPoint.Total', self.config.modified)
        self.recorder._observe.assert_called_once_with('ActionPoint', {'Value': 123})
        self.snapshot.assert_not_called()

    def test_measured_total_uses_this_sample_instead_of_old_config(self):
        stamp = datetime(2026, 10, 16, 22, 49, 13)
        self.recorder.record('ActionPoint', {'Value': 189, 'Total': 7289}, observed_at=stamp)
        self.snapshot.assert_called_once_with(self.config, ap_current=189, ap_total=7289,
                                              source='OpsiHazard1Leveling', observed_at=stamp)

    def test_failed_measurement_does_not_create_a_snapshot(self):
        self.recorder.record('ActionPoint', {'Value': 51, 'Total': 7151}, observed=False)
        self.recorder._observe.assert_not_called()
        self.snapshot.assert_not_called()

    def test_small_and_zero_totals_are_valid_when_explicitly_measured(self):
        for value in (51, 0):
            with self.subTest(value=value):
                self.snapshot.reset_mock()
                self.recorder.record('ActionPoint', {'Value': value, 'Total': value})
                self.assertEqual(self.snapshot.call_args.kwargs['ap_total'], value)

    def test_current_only_domain_event_does_not_enter_the_write_queue(self):
        with patch('module.statistics.cl1_database.db.async_add_ap_snapshot') as queued:
            record_ap_snapshot(self.config, 123, source='OpsiHazard1Leveling')
            queued.assert_not_called()

    def test_meow_current_refresh_does_not_synthesize_a_total_from_cache(self):
        runner = SimpleNamespace(config=self.config, get_current_ap=Mock(),
                                 _action_point_current=123, _action_point_total_with_box=99999,
                                 zone=SimpleNamespace(hazard_level=3))
        with patch('module.os_handler.resource_state.resource_fast_path', return_value=False), \
                patch('module.statistics.opsi_runtime.time.time', return_value=110), \
                patch('module.statistics.cl1_database.db.async_add_meow_round_time'):
            self.assertEqual(finish_meow_search_timer(runner, 10, 2), 100)
        runner.get_current_ap.assert_called_once()
        self.snapshot.assert_not_called()


class ActionPointPanelStatisticsTests(unittest.TestCase):
    def test_unverified_box_inventory_does_not_claim_a_total(self):
        runner = ActionPointHandler.__new__(ActionPointHandler)
        runner.config = SimpleNamespace(OS_ACTION_POINT_BOX_USE=True, update=Mock(), override=Mock())
        runner.device = SimpleNamespace(image=object())
        with patch('module.os_handler.action_point.resource_fast_path', return_value=False), \
                patch('module.os_handler.action_point.OIL_ITEM') as oil, \
                patch('module.os_handler.action_point.ACTION_POINT_ITEMS') as boxes, \
                patch('module.os_handler.action_point.OCR_ACTION_POINT_REMAIN') as current, \
                patch('module.os_handler.action_point.LogRes') as recorder:
            oil.predict.return_value = [SimpleNamespace(amount=10000)]
            oil.amount_ocr.last_batch_validity = (True,)
            boxes.predict.return_value = [SimpleNamespace(amount=0), SimpleNamespace(amount=0),
                                         SimpleNamespace(amount=71)]
            boxes.amount_ocr.last_batch_validity = (False, True, True)
            current.ocr.return_value = 123
            current.last_valid = True
            runner.action_point_update()
            self.assertEqual(recorder.return_value.record.call_args.args,
                             ('ActionPoint', {'Value': 123}))


class ActionPointStatisticsIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.root = Path(directory)
        (self.root / 'config').mkdir()
        self.db = Cl1Database(self.root / 'config/cl1_data.db')
        self.enterContext(patch('module.statistics.cl1_database.db', self.db))
        self.enterContext(patch('module.statistics.opsi_month.cl1_db', self.db))
        self.stamp = datetime(2026, 10, 16, 22, 30)
        self.configs = SimpleNamespace(directory=self.root / 'config',
                                       path=lambda _: self.root / 'config/isolated.json')

    def action_report(self):
        return report(self.configs, 'isolated', 'action', '2026-10', 7, 'month')['series']

    def test_database_rejects_current_only_and_keeps_mileage_independent(self):
        self.db.add_ap_snapshot('isolated', 152, ap_total=7352, observed_at=self.stamp)
        self.db.add_ap_snapshot('isolated', 67, observed_at=self.stamp + timedelta(seconds=1))
        self.db.add_ap_snapshot('isolated', None, source='sea_miles', distance=120000,
                                observed_at=self.stamp + timedelta(seconds=2))
        for index, value in enumerate((51, 0), start=3):
            self.db.add_ap_snapshot('isolated', value, ap_total=value,
                                    observed_at=self.stamp + timedelta(seconds=index))
        snapshots = self.db.get_stats('isolated', '2026-10')['ap_snapshots']
        self.assertEqual(len(snapshots), 4)
        mileage = snapshots[1]
        self.assertEqual(mileage['distance'], 120000)
        for key in ('ap', 'ap_total', 'asset', 'yellow_coin'):
            self.assertNotIn(key, mileage)
        curves = self.action_report()
        self.assertEqual([point['v'] for point in curves[0]['points']], [7352, 51, 0])
        self.assertEqual(len(curves[1]['points']), 3)
        self.assertEqual([point['v'] for point in curves[2]['points']], [120000])

    def test_existing_partial_history_is_hidden_without_deletion_or_fake_totals(self):
        samples = [
            {'ap': 152, 'ap_total': 7352, 'asset': 416613.33},
            {'ap': 67, 'asset': 3796.67},
            {'ap': 123, 'asset': 6970},
            {'ap': 189, 'ap_total': 7289, 'asset': 413043.33},
            {'ap': 125, 'ap_total': 9125, 'asset': 517083.33,
             'source': 'hazard1_estimate', 'distance': 120000},
            {'ap': 0, 'asset': 0, 'source': 'sea_miles', 'distance': 120001},
            {'ap': 51, 'ap_total': 51, 'asset': 2890},
            {'ap': 0, 'ap_total': 0, 'asset': 0},
        ]
        samples = [dict(sample, ts=(self.stamp + timedelta(seconds=index)).isoformat(),
                        source=sample.get('source', 'OpsiHazard1Leveling'))
                   for index, sample in enumerate(samples)]
        self.db.save_stats('isolated', '2026-10', {'ap_snapshots': samples})
        before = self.db.get_stats('isolated', '2026-10')
        with patch.object(self.db, '_stats_transaction', side_effect=AssertionError('报表不能改写历史')):
            curves = self.action_report()
            assets = get_asset_timeline(2026, 10, 'isolated')
        self.assertEqual([point['v'] for point in curves[0]['points']], [7352, 7289, 51, 0])
        self.assertEqual([point['v'] for point in curves[1]['points']], [416613.33, 413043.33, 2890, 0])
        self.assertEqual([point['v'] for point in curves[2]['points']], [120000, 120001])
        self.assertEqual(len(assets), 4)
        self.assertEqual(self.db.get_stats('isolated', '2026-10'), before)


if __name__ == '__main__':
    unittest.main()

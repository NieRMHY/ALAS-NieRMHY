"""四个统计存储在明文语义下的集成测试。

覆盖：写入拆分为公共列与载荷列（载荷为明文 JSON）、读取透明合并、
旧版整体明文行可读并在下次写入时拆分；文件类存储读写一致。
"""

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np

from module.statistics import opsi_secure, resource_stats
from module.statistics.azurstats import AzurStats
from module.statistics.cl1_database import Cl1Database
from module.statistics.ship_exp_stats import ShipExpStats


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'config').mkdir()
        (self.root / 'log' / 'cl1' / 'inst').mkdir(parents=True)


class Cl1StoreIntegration(StoreCase):
    def make_db(self):
        return Cl1Database(db_path=self.root / 'config' / 'cl1_data.db')

    def raw(self, sql, params=()):
        conn = sqlite3.connect(self.root / 'config' / 'cl1_data.db')
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def month(self):
        return datetime.now().strftime('%Y-%m')

    def test_writes_split_public_and_secure_columns_as_plaintext(self):
        db = self.make_db()
        db.increment_battle_count('inst', 3)
        db.add_ap_snapshot('inst', 131, source='cl1')
        db.add_commission_income('inst', {'Gem': 5})
        raw_json, payload = self.raw('SELECT data_json, secure_json FROM cl1_data')[0]
        self.assertNotIn('battle_count', raw_json)
        self.assertNotIn('ap_snapshots', raw_json)
        self.assertIn('commission_income_entries', raw_json)
        self.assertFalse(payload.startswith('OPSIV'))
        secure = json.loads(payload)
        self.assertEqual(secure['battle_count'], 3)
        self.assertEqual(len(secure['ap_snapshots']), 1)
        data = db.get_stats('inst', self.month())
        self.assertEqual(data['battle_count'], 3)
        self.assertEqual(len(data['ap_snapshots']), 1)
        self.assertEqual(len(data['commission_income_entries']), 1)
        # 事务内读改写路径同样合并。
        db.increment_akashi_encounter('inst')
        self.assertEqual(db.get_stats('inst', self.month())['akashi_encounters'], 1)

    def test_legacy_whole_row_reads_and_splits_on_next_write(self):
        db = self.make_db()
        data = {'battle_count': 7, 'akashi_encounters': 0, 'akashi_ap': 0, 'akashi_ap_entries': [],
                'ap_snapshots': [], 'yellow_coin_snapshots': [], 'coins_snapshots': [],
                'meow_battle_raw_count': 0, 'meow_battle_count': 0.0, 'meow_round_times': [],
                'meow_hazard_stats': {}, 'siren_research_devices': {'cl1': 0, 'meow': {}},
                'siren_research_device_entries': [], 'commission_income_entries': [{'keep': True}]}
        with sqlite3.connect(self.root / 'config' / 'cl1_data.db') as conn:
            conn.execute("INSERT INTO cl1_data (instance, month, data_json, secure_json, encrypted_blob) "
                         "VALUES ('inst', ?, ?, NULL, NULL)", (self.month(), json.dumps(data)))
        loaded = db.get_stats('inst', self.month())
        self.assertEqual(loaded['battle_count'], 7)
        self.assertEqual(loaded['commission_income_entries'], [{'keep': True}])
        db.increment_battle_count('inst', 1)
        raw_json, payload = self.raw('SELECT data_json, secure_json FROM cl1_data')[0]
        self.assertNotIn('battle_count', raw_json)
        self.assertEqual(json.loads(payload)['battle_count'], 8)


class AzurstatsIntegration(StoreCase):
    ROW = {
        'imgid': 'img-1', 'server': 'cn', 'zone': 'NA海域', 'zone_type': 'abyssal',
        'zone_id': 5, 'hazard_level': 6, 'item': 'PlateGeneralT4', 'amount': 3,
        'tag': 'gold', 'device_id': 'dev-1', 'instance': 'inst',
        'genre': 'opsi_meowfficer_farming', 'combat_count': 2, 'created_at': 1_789_000_000,
    }

    def setUp(self):
        super().setUp()
        self.db_patch = patch.object(AzurStats, 'LOCAL_DB', str(self.root / 'config' / 'azurstats_local.db'))
        self.csv_patch = patch.object(
            AzurStats, 'LOCAL_MEOW_CSV', str(self.root / 'log' / 'azurstat_meowofficer_farming.csv'))
        self.db_patch.start()
        self.csv_patch.start()
        self.addCleanup(self.csv_patch.stop)
        self.addCleanup(self.db_patch.stop)
        AzurStats._ensure_local_db()

    def raw(self, sql, params=()):
        conn = sqlite3.connect(self.root / 'config' / 'azurstats_local.db')
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def test_insert_stores_plaintext_payload_and_load_merges(self):
        AzurStats._insert_local_opsi_items([dict(self.ROW), dict(self.ROW, imgid='img-2', amount=7)])
        rows = self.raw('SELECT item, secure_payload FROM opsi_items ORDER BY id')
        self.assertIsNone(rows[0][0])
        payload = json.loads(rows[1][1])
        self.assertEqual((payload['item'], payload['amount'], payload['hazard_level']),
                         ('PlateGeneralT4', 7, 6))
        loaded = AzurStats.load_opsi_drop_rows(instance='inst', device_id='dev-1')
        self.assertEqual([row['item'] for row in loaded], ['PlateGeneralT4', 'PlateGeneralT4'])
        self.assertEqual([row['amount'] for row in loaded], [3, 7])

    def test_monthly_totals_across_old_and_new_rows(self):
        # 旧行：物品字段写在普通列（没有载荷列）。
        with sqlite3.connect(self.root / 'config' / 'azurstats_local.db') as conn:
            conn.execute("INSERT INTO opsi_items (imgid, device_id, instance, genre, created_at, item, amount, hazard_level) "
                         "VALUES ('img-0', 'dev-1', 'inst', 'opsi_meowfficer_farming', ?, 'PlateT4', 3, 6)",
                         (int(datetime(2026, 9, 1).timestamp()),))
        AzurStats._insert_local_opsi_items([dict(self.ROW, item='PlateT4', amount=4)])
        totals = AzurStats.get_meow_loot_monthly_totals(year=2026, month=9, device_id='dev-1', instance='inst')
        self.assertEqual(totals[6]['Plate'], 7)

    def test_farming_csv_is_plaintext_and_readable(self):
        AzurStats._insert_local_opsi_items([dict(self.ROW)])
        data = AzurStats.get_meowofficer_farming(instance='inst')
        # 实例化文件名带设备哈希，直接找目录里的实际文件。
        files = list((self.root / 'log').glob('azurstat_meowofficer_farming*.csv'))
        self.assertEqual(len(files), 1)
        content = files[0].read_text(encoding='utf-8')
        self.assertFalse(content.startswith('OPSIV'))
        self.assertIn('侵蚀等级', content.splitlines()[0])
        cached = AzurStats.load_meowofficer_farming(instance='inst')
        np.testing.assert_allclose(cached, data)


class ResourceStatsIntegration(StoreCase):
    SNAPSHOT = {'Oil': 14000, 'Coin': 180000, 'ActionPoint': 131, 'YellowCoin': 500, 'PurpleCoin': 20}

    def setUp(self):
        super().setUp()
        self.db_patch = patch.object(resource_stats, '_LOCAL_DB', str(self.root / 'config' / 'azurstats_local.db'))
        self.ensured_patch = patch.object(resource_stats, '_table_ensured', False)
        self.db_patch.start()
        self.ensured_patch.start()
        self.addCleanup(self.ensured_patch.stop)
        self.addCleanup(self.db_patch.stop)

    def raw(self, sql):
        conn = sqlite3.connect(self.root / 'config' / 'azurstats_local.db')
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def test_snapshot_stores_only_opsi_columns_in_plaintext_payload(self):
        resource_stats.record_resource_snapshot('inst', dict(self.SNAPSHOT))
        resource_stats.record_resource_snapshot('inst', dict(self.SNAPSHOT, ActionPoint=160))
        rows = self.raw('SELECT oil, action_point, opsi_payload FROM resource_snapshots ORDER BY id')
        self.assertIsNone(rows[0][1])
        payload = json.loads(rows[0][2])
        self.assertEqual((payload['action_point'], payload['purple_coin']), (131, 20))
        self.assertEqual(rows[1][0], 14000)        # 非大世界列保持普通列
        timeline = resource_stats.get_resource_timeline('inst')
        self.assertEqual([row['action_point'] for row in timeline], [131, 160])
        self.assertEqual([row['oil'] for row in timeline], [14000, 14000])
        with patch.object(resource_stats, '_overlay_opsi_snapshot', side_effect=AssertionError('不得读取载荷')):
            public = resource_stats.get_resource_timeline('inst', include_opsi=False)
        self.assertEqual([row['oil'] for row in public], [14000, 14000])
        self.assertTrue(all('opsi_payload' not in row and row['action_point'] is None for row in public))

    def test_interval_summary_covers_opsi_currencies(self):
        resource_stats.record_resource_snapshot('inst', dict(self.SNAPSHOT))
        start = datetime.now()
        resource_stats.record_resource_snapshot('inst', dict(self.SNAPSHOT, ActionPoint=160))
        summary = resource_stats.get_resource_interval_summary('inst', start, datetime.now() + timedelta(minutes=1))
        self.assertEqual(summary['resources']['ActionPoint']['delta'], 29)
        self.assertEqual(summary['resources']['Oil']['delta'], 0)

    def test_legacy_columns_without_payload_stay_readable(self):
        resource_stats._ensure_table()
        with sqlite3.connect(self.root / 'config' / 'azurstats_local.db') as conn:
            conn.execute("INSERT INTO resource_snapshots (instance, ts, oil, action_point, yellow_coin, purple_coin) "
                         "VALUES ('inst', '2026-09-01T10:00:00', 12000, 100, 400, 15)")
        timeline = resource_stats.get_resource_timeline('inst')
        self.assertEqual(timeline[0]['action_point'], 100)
        self.assertEqual(timeline[0]['purple_coin'], 15)


class ShipExpIntegration(StoreCase):
    def make_stats(self):
        return ShipExpStats(path=self.root / 'log' / 'cl1' / 'inst' / 'ship_exp_data.json')

    def test_save_is_plain_json_and_reload_matches(self):
        stats = self.make_stats()
        stats.data = {'battle_times': {'samples': [52.0], 'average': 52.0}, 'target_level': 125}
        stats._save()
        raw = stats._path.read_text(encoding='utf-8')
        self.assertFalse(raw.startswith('{"__opsi_secure'))
        self.assertIn('battle_times', raw)
        fresh = self.make_stats()
        self.assertEqual(fresh.data['battle_times']['average'], 52.0)
        self.assertEqual(fresh.data['target_level'], 125)

    def test_legacy_wrapped_file_loads_and_rewrites_plain(self):
        import base64
        import os
        from tests.test_opsi_secure import seal_v2
        from module.statistics.opsi_secure import file_context
        key = os.urandom(32)
        directory = self.root / 'config' / 'opsi_secure'
        directory.mkdir(parents=True)
        (directory / 'keyring.json').write_bytes(json.dumps(
            {'version': 2, 'algorithm': opsi_secure.ALGORITHM, 'installation_id': 'inst-id',
             'provider': 'container-file'}).encode())
        (directory / 'state.json').write_bytes(json.dumps(
            {'slot': 'x', 'state': {'phase': 'ready', 'key': base64.b64encode(key).decode(),
                                    'installation_id': 'inst-id'}}).encode())
        path = self.root / 'log' / 'cl1' / 'inst' / 'ship_exp_data.json'
        blob = seal_v2(key, 'ships', {'target_level': 130}, file_context(self.root, 'ships', path), 'inst-id')
        path.write_bytes(json.dumps({opsi_secure.WRAPPER_KEY: True, 'payload': blob}).encode())
        previous = opsi_secure._STORE
        opsi_secure.set_store(opsi_secure.StatsStore(self.root))
        self.addCleanup(opsi_secure.set_store, previous)
        stats = self.make_stats()
        self.assertEqual(stats.data['target_level'], 130)
        stats._save()
        self.assertIn('target_level', json.loads(path.read_text(encoding='utf-8')))


if __name__ == '__main__':
    unittest.main()

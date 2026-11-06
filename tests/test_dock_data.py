"""共享船坞的副本、只读兼容及分析隔离回归。"""
import copy
import unittest

from module.api.protocol import MindShip
from module.runtime import dock_data as dock
from module.runtime import fleet_tech as tech


def ship(gid=10102, level=105, **extra):
    return dict(group_type=gid, name='测试舰', level=level, rarity='R', base_rarity='R',
                source='夹具', review=False, **extra)


def snapshot(rows, **extra):
    fields = dict(min_level=1, max_level=125, reached_bottom=True, filters_clear=True,
                  physical_count=len(rows), expected_count=len(rows), updated_at='2026-10-25T12:00:00')
    fields.update(extra)
    return dock.build_snapshot(rows, **fields)


class DockDataTests(unittest.TestCase):
    def test_物理副本保留且输入不变(self):
        rows = [ship(level=105), ship(level=120)]
        before = copy.deepcopy(rows)
        result = snapshot(rows)
        self.assertEqual(rows, before)
        self.assertEqual(len(result['ships']), 2)
        self.assertEqual([row['slot'] for row in result['ships']], [0, 1])
        self.assertTrue(result['complete'])
        self.assertEqual(result['review_count'], 0)
        self.assertNotIn('history', result)

    def test_完整扫描需要全范围无过滤无疑点且数量吻合(self):
        for extra in [dict(min_level=95), dict(filters_clear=False), dict(reached_bottom=False),
                      dict(expected_count=None), dict(physical_count=2)]:
            with self.subTest(extra=extra):
                result = snapshot([ship(level=105)], **extra)
                self.assertFalse(result['complete'])
                self.assertNotIn('history', result)
        for uncertain in [dict(ship(), review=True), ship(gid=None), dict(ship(), level=0)]:
            with self.subTest(uncertain=uncertain):
                result = snapshot([uncertain])
                self.assertFalse(result['complete'])
                self.assertEqual(result['review_count'], 1)
        self.assertTrue(snapshot([ship(level=105)])['complete'])

    def test_旧配置全部忽略且显式空快照有效(self):
        data = {
            'DockScan': {'Dock': {'Result': snapshot([ship(level=125)])}},
            'MindCalculatorScan': {'MindCalculator': {'Result': {'ships': [ship()]},
                                                       'Analysis': {'extra': [ship()]}}},
            'FleetTechScan': {'FleetTech': {'Record': {'observed': {'10102': 125},
                                                       'manual': {'10102': {'owned': True}}}}},
        }
        before = copy.deepcopy(data)
        self.assertFalse(dock.has_snapshot(data))
        self.assertEqual(dock.read_snapshot(data)['source'], 'empty')
        self.assertEqual(dock.read_snapshot(data)['ships'], [])
        self.assertFalse(tech.progress(dock.technology_record(data), 10102)['owned'])
        self.assertEqual(data, before)
        data['snapshot'] = snapshot([])
        self.assertTrue(dock.has_snapshot(data))
        self.assertEqual(dock.report_snapshot(data)['ships'], [])
        self.assertEqual(dock.report_snapshot(data)['source'], 'scan')


    def test_科技合并保留人工阵营且只读(self):
        current = snapshot([dict(ship(), id=1)])
        options = dict(progress={'10102': dict(owned=False, full_star=False, lv120=False)}, nations={'1': 3})
        data = dict(snapshot=current, technology=options, mind={})
        before = copy.deepcopy(data)
        record = dock.technology_record(data)
        self.assertEqual(record['nations'], options['nations'])
        state = tech.progress(record, 10102)
        self.assertFalse(state['owned'])
        self.assertEqual(state['current_count'], 1)
        self.assertFalse(tech.progress(record, 10103)['owned'])
        self.assertEqual(data, before)

    def test_无快照仍读取独立人工设置且默认全范围(self):
        data = dict(snapshot=None, mind={}, technology={'progress': {'10102': {'owned': True}}})
        self.assertTrue(tech.progress(dock.technology_record(data), 10102)['owned'])
        report = dock.report_snapshot(data)
        self.assertEqual((report['min_level'], report['max_level'], report['source']), (1, 125, 'empty'))

    def test_局部扫描只提供本次卡片且不派生科技历史(self):
        result = snapshot([ship(level=105)], min_level=95)
        self.assertEqual(result['ships'][0]['level'], 105)
        self.assertFalse(result['complete'])
        self.assertNotIn('history', result)
        self.assertFalse(tech.progress(dock.technology_record({'snapshot': result}), 10102)['owned'])


if __name__ == '__main__':
    unittest.main()

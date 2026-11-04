"""校验资源快照的字面量 INSERT 语句与 RESOURCE_COLUMNS、数据表结构保持一致。"""

import re
import sqlite3
import unittest
from pathlib import Path

from module.statistics.resource_stats import RESOURCE_COLUMNS, _SNAPSHOT_INSERT_SQL


class ResourceSnapshotSqlTests(unittest.TestCase):
    def test_columns_and_placeholders_match_resource_columns(self):
        match = re.fullmatch(r'INSERT INTO resource_snapshots \((.+)\) VALUES \((.+)\)', _SNAPSHOT_INSERT_SQL)
        self.assertIsNotNone(match)
        columns = match.group(1).split(',')
        placeholders = match.group(2).split(',')
        expected = ['instance', 'ts', *RESOURCE_COLUMNS.values()]
        self.assertEqual(columns, expected)
        self.assertEqual(placeholders, [':' + column for column in expected])

    def test_statement_runs_against_schema(self):
        schema = Path('module/persistence/schema_v1.sql').read_text(encoding='utf-8')
        table = re.search(r'CREATE TABLE resource_snapshots \(.*?\) STRICT;', schema, re.S).group(0)
        table = table.replace('REFERENCES storage_instances(instance)', '')
        with sqlite3.connect(':memory:') as conn:
            conn.execute(table)
            row = {'instance': 'demo', 'ts': '2026-01-01T00:00:00'}
            row.update({column: 1 for column in RESOURCE_COLUMNS.values()})
            conn.execute(_SNAPSHOT_INSERT_SQL, row)
            self.assertEqual(conn.execute('SELECT oil, purple_coin FROM resource_snapshots').fetchone(), (1, 1))


if __name__ == '__main__':
    unittest.main()

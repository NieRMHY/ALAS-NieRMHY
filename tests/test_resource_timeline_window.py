"""资源时间线的窗口过滤：下推到 SQL 后窗口内的点一个不少。"""
import shutil
import sqlite3
import tempfile
import unittest
from tests.opsi_test_support import install_store
from pathlib import Path

from module.statistics import resource_stats


def test_timeline_since_keeps_every_row_in_window():
    # 清理失败即忽略：库文件可能仍被连接占用。
    directory = tempfile.mkdtemp(prefix='azurpilot-resource-')
    case = unittest.TestCase()
    install_store(case, directory)
    database = Path(directory) / 'config' / 'azurstats_local.db'
    original_db, original_ensured = resource_stats._LOCAL_DB, resource_stats._table_ensured
    resource_stats._LOCAL_DB, resource_stats._table_ensured = str(database), False
    try:
        resource_stats._ensure_table()
        with sqlite3.connect(database) as conn:
            conn.executemany(
                "INSERT INTO resource_snapshots (instance, ts, oil) VALUES ('default', ?, ?)",
                [(f'2026-01-01T{hour:02d}:{minute:02d}:00', hour * 100 + minute)
                 for hour in range(24) for minute in (0, 30)],
            )

        whole = resource_stats.get_resource_timeline('default')
        window = resource_stats.get_resource_timeline('default', since='2026-01-01T20:00:00')

        assert len(whole) == 48
        assert [row['oil'] for row in window] == [2000, 2030, 2100, 2130, 2200, 2230, 2300, 2330]
    finally:
        resource_stats._LOCAL_DB, resource_stats._table_ensured = original_db, original_ensured
        case.doCleanups()
        shutil.rmtree(directory, ignore_errors=True)

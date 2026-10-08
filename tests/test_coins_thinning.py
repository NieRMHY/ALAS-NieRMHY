"""凭证快照的抽稀边界：近 3 天逐条，更早每小时只留末条。"""
from datetime import datetime, timedelta

from module.statistics.cl1_database import COINS_EXACT_DAYS, thin_coins_snapshots


def _at(days_ago: int, hour: int, minute: int) -> dict:
    stamp = (datetime.now() - timedelta(days=days_ago)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return {'ts': stamp.isoformat(), 'yellow_coins': f'{days_ago}d{hour:02d}:{minute:02d}'}


def test_thin_coins_snapshots_keeps_recent_and_thins_older():
    snapshots = [
        _at(0, 10, 5), _at(0, 10, 55),        # 3 天内：两条都留
        _at(COINS_EXACT_DAYS + 2, 9, 10),     # 超期同小时
        _at(COINS_EXACT_DAYS + 2, 9, 50),     # 超期同小时的末条，应取代上一条
        _at(COINS_EXACT_DAYS + 2, 11, 30),    # 另一个小时，独立保留
    ]

    kept = [item['yellow_coins'] for item in thin_coins_snapshots(snapshots)]

    assert '0d10:05' in kept and '0d10:55' in kept
    assert '5d09:50' in kept and '5d09:10' not in kept
    assert '5d11:30' in kept
    assert len(kept) == 4


def test_thin_coins_snapshots_stays_bounded_for_repeated_hours():
    snapshots = [_at(30, 9, minute) for minute in (5, 15, 25, 35, 45, 55)]

    kept = thin_coins_snapshots(snapshots)

    assert len(kept) == 1
    assert kept[0]['yellow_coins'] == '30d09:55'

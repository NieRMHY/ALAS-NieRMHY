# -*- coding: utf-8 -*-
"""
为已有 AP 快照回填 asset 和 virtual_asset 字段。

用法:
    python -m dev_tools.backfill_asset_snapshots

遍历所有实例、所有月份，对缺少 asset/virtual_asset 的 AP 快照
按录制时间戳重新计算并回填，不会修改已有的 asset/virtual_asset 值。
"""
import sys
from pathlib import Path

# 将项目根目录加入 sys.path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from datetime import datetime
from calendar import monthrange
from module.statistics.cl1_database import db as cl1_db


def backfill_all_asset_snapshots(dry_run: bool = False) -> dict:
    """
    遍历所有实例和月份，回填 asset 和 virtual_asset 字段。

    Args:
        dry_run: True 时只扫描不写入

    Returns:
        统计信息: {checked, updated, skipped, errors}
    """
    stats = {'checked': 0, 'updated': 0, 'skipped': 0, 'errors': 0}
    rows = cl1_db._list_stats_rows()

    cl5_efficiency = 1700.0 / 30.0

    for instance, month_key in rows:
        print(f"  [{instance}] [{month_key}] ... ", end='', flush=True)

        try:
            data = cl1_db.get_stats(instance, month_key)
            snapshots = data.get('ap_snapshots', [])
            if not snapshots:
                print("skipped (no ap_snapshots)")
                stats['skipped'] += 1
                continue

            # 获取该月的黄币快照（用于旧数据中没有 yellow_coin 的情况）
            yellow_coin_snapshots = data.get('yellow_coin_snapshots', [])

            changed = False
            for snap in snapshots:
                # 如果已经有 asset 和 virtual_asset，跳过
                if 'asset' in snap and 'virtual_asset' in snap:
                    continue

                stats['checked'] += 1

                # 解析时间戳
                ts_raw = snap.get('ts', '')
                try:
                    snap_dt = datetime.fromisoformat(ts_raw)
                except Exception:
                    stats['errors'] += 1
                    continue

                # 从快照读取 AP（当时录制时的值）
                ap = snap.get('ap', 0)
                if not isinstance(ap, (int, float)):
                    ap = 0
                ap = int(ap)

                # 获取当时的黄币
                # 1) 优先从快照中已有的 yellow_coin 字段读取
                # 2) 如果旧快照没有，从该月的黄币快照中查找最近的一条
                yellow_coin = snap.get('yellow_coin', None)
                if yellow_coin is None:
                    # 从黄币快照中查找不超过 6 小时（21600秒）的记录
                    yc_found = None
                    for yc_snap in reversed(yellow_coin_snapshots):
                        try:
                            yc_ts = yc_snap.get('ts', '')
                            yc_dt = datetime.fromisoformat(yc_ts)
                            diff = abs((snap_dt - yc_dt).total_seconds())
                            if diff < 21600:  # 6小时内
                                yc_found = int(yc_snap.get('yellow_coin', 0))
                                break
                        except Exception:
                            continue
                    yellow_coin = yc_found if yc_found is not None else 0

                # 计算到月底的剩余时间
                year, month_num = snap_dt.year, snap_dt.month
                last_day = monthrange(year, month_num)[1]
                month_end = datetime(year, month_num, last_day, 23, 59, 59)
                time_to_month_end_sec = (month_end - snap_dt).total_seconds()

                # asset = AP × 效率 + 黄币
                asset = ap * cl5_efficiency + yellow_coin

                # virtual_asset = asset + (到月底时间/10分钟) × (1700/30)
                virtual_asset_added = (time_to_month_end_sec / 600.0) * cl5_efficiency
                virtual_asset = asset + virtual_asset_added

                # 回填字段
                snap['asset'] = round(asset, 2)
                snap['yellow_coin'] = int(yellow_coin)  # 确认旧数据也有该字段
                snap['virtual_asset'] = round(virtual_asset, 2)
                changed = True

            if changed:
                if dry_run:
                    print(f"would update {sum(1 for s in snapshots if 'asset' in s)} snapshots (dry-run)")
                else:
                    data['ap_snapshots'] = snapshots
                    cl1_db.save_stats(instance, month_key, data)
                    print(f"updated {stats['checked']} snapshots")
                stats['updated'] += 1
            else:
                print("skipped (already up-to-date)")
                stats['skipped'] += 1

        except Exception as e:
            print(f"ERROR: {e}")
            stats['errors'] += 1

    return stats


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="回填旧 AP 快照的 asset 和 virtual_asset 字段"
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='仅扫描不写入，查看需要更新的数量'
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  AP 快照资产/虚拟资产回填工具")
    if args.dry_run:
        print("  模式: DRY RUN (不会写入数据库)")
    print("=" * 60)

    stats = backfill_all_asset_snapshots(dry_run=args.dry_run)

    print("=" * 60)
    print("  完成统计:")
    print(f"    扫描快照: {stats['checked']}")
    print(f"    月份已更新: {stats['updated']}")
    print(f"    月份已跳过: {stats['skipped']}")
    print(f"    错误数: {stats['errors']}")
    print("=" * 60)


if __name__ == '__main__':
    main()

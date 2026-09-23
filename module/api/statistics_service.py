"""复用既有统计源，为分类页面提供指标、时间线和可导出的明细。"""
import math
import threading
from datetime import datetime, timedelta

import os
from module.api.protocol import ApiError


_loot_lock = threading.Lock()


def get_statistics_fingerprint(instance: str) -> str:
    """获取当前实例统计数据的轻量级指纹。

    检测 SQLite 本地快照库、CL1 记录库、舰船统计文件以及配置文件修改时间，
    用于 WebSocket 会话高效判断后端统计数据是否有更新。
    """
    parts = []
    # 1. 资源快照数据库 (azurstats_local.db)
    res_db = './config/azurstats_local.db'
    try:
        stat = os.stat(res_db)
        parts.append(f"res:{stat.st_mtime_ns}:{stat.st_size}")
    except OSError:
        parts.append("res:none")

    # 2. 实例配置文件 (config/<instance>.json)
    cfg_file = f'./config/{instance}.json'
    try:
        stat = os.stat(cfg_file)
        parts.append(f"cfg:{stat.st_mtime_ns}")
    except OSError:
        parts.append("cfg:none")

    # 3. 大世界与委托记录库 (cl1_record.db)
    cl1_db = './config/cl1_record.db'
    try:
        stat = os.stat(cl1_db)
        parts.append(f"cl1:{stat.st_mtime_ns}")
    except OSError:
        parts.append("cl1:none")

    # 4. 舰船经验统计文件 (log/ship_exp_stats.json)
    ship_file = './log/ship_exp_stats.json'
    try:
        stat = os.stat(ship_file)
        parts.append(f"ship:{stat.st_mtime_ns}")
    except OSError:
        parts.append("ship:none")

    return ';'.join(parts)



def refresh_loot(configs, instance):
    """只重算已有本地掉落记录，复用旧界面刷新操作。"""
    configs.path(instance)
    from module.statistics.azurstats import AzurStats
    with _loot_lock:
        AzurStats.get_meowofficer_farming(instance=instance)
    return {'refreshed': True}


RESOURCE_LABELS = {
    'Oil': '石油', 'Coin': '物资', 'Gem': '钻石', 'Cube': '心智魔方', 'Pt': '活动 PT',
    'Core': '核心数据', 'Medal': '荣誉勋章', 'Merit': '功勋', 'GuildCoin': '舰队币',
    'ActionPoint': '行动力', 'YellowCoin': '作战补给凭证', 'PurpleCoin': '特别兑换凭证',
}


def table(title, columns, rows, note='', default_sort=None):
    result = {'title': title, 'columns': columns, 'rows': rows, 'note': note}
    if default_sort is not None:
        result['defaultSort'] = default_sort
    return result


def series(rows, key, label):
    """保留真实采集时间与来源，跳过无效值，绝不把缺失值补成零。"""
    points = []
    for row in rows:
        value = row.get(key)
        try:
            timestamp = datetime.fromisoformat(str(row['ts']))
            if value is None or not math.isfinite(float(value)):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        points.append({'time': timestamp.isoformat(sep=' '), 'value': float(value),
                       'source': row.get('source', '')})
    points.sort(key=lambda item: item['time'])
    return {'key': key, 'label': label, 'points': points}


def report(configs, instance, category, month, days, period):
    configs.path(instance)
    now = datetime.now()
    try:
        selected = datetime.strptime(month, '%Y-%m') if month else now.replace(day=1)
    except ValueError as exc:
        raise ApiError('INVALID_PARAMS', '月份格式应为 YYYY-MM') from exc
    if not 2020 <= selected.year <= 9998:
        raise ApiError('INVALID_PARAMS', '统计月份应在 2020 至 9998 年之间')
    year, month_number = selected.year, selected.month
    result = {'instance': instance, 'category': category, 'month': f'{year:04d}-{month_number:02d}',
              'metrics': [], 'series': [], 'tables': [], 'notes': []}

    def metric(label, value, unit=''):
        result['metrics'].append({'label': label, 'value': value, 'unit': unit})

    if category == 'resources':
        from module.statistics.resource_stats import RESOURCE_COLUMNS, get_resource_timeline
        rows = get_resource_timeline(instance, limit=50001)
        cutoff = (now - timedelta(days=days)).isoformat(sep=' ')
        rows = [row for row in rows if str(row['ts']).replace('T', ' ') >= cutoff]
        if len(rows) > 50000:
            result['notes'].append('记录超过 50,000 条，当前展示最近 50,000 条，请缩短时间范围查看细节。')
            rows = rows[-50000:]
        resource_items = [
            (name, key) for name, key in RESOURCE_COLUMNS.items()
            if name not in ('ActionPoint', 'YellowCoin', 'PurpleCoin')
        ]
        result['series'] = [series(rows, key, RESOURCE_LABELS[name]) for name, key in resource_items]
        return result

    from module.statistics.cl1_database import db
    if category == 'opsi':
        from module.statistics.opsi_month import get_opsi_stats, compute_monthly_cl1_akashi_ap
        summary = get_opsi_stats(instance).summary(year, month_number)
        battles = summary['total_battles']
        # 沿用旧界面口径：向上取整，每轮侵蚀1消耗 5 行动力。
        rounds = (battles + 1) // 2
        cost = rounds * 5
        purchased = compute_monthly_cl1_akashi_ap(year, month_number, instance_name=instance)
        encounters = summary['akashi_encounters']
        devices = summary['siren_research_devices']
        for label, value, unit in [
            ('战斗次数', battles, '场'), ('出击轮数', rounds, '轮'), ('出击消耗', cost, '行动力'),
            ('明石遭遇', encounters, '次'), ('明石遭遇率', round(encounters / rounds * 100, 2) if rounds else None, '%'),
            ('塞壬研究装置', devices, '个'), ('装置获取率', round(devices / rounds * 100, 2) if rounds else None, '%'),
            ('购买行动力', purchased, ''), ('平均每次购买', round(purchased / encounters, 2) if encounters else None, ''),
            ('净行动力', purchased - cost, ''), ('循环效率', round((purchased - cost) / cost * 100, 2) if cost else None, '%'),
        ]:
            metric(label, value, unit)
        rows = []
        for hazard in (3, 5):
            data = db.get_meow_stats(instance, year, month_number, hazard_level=hazard)
            rows.append([hazard, data.get('battle_count'), data.get('effective_rounds'),
                         data.get('avg_battle_time'), data.get('avg_round_time'),
                         data.get('siren_research_devices'), round(data.get('siren_research_rate', 0) * 100, 2),
                         {'exact': '实测', 'estimated': '估算', 'none': '暂无记录'}.get(data.get('by_hazard', {}).get(str(hazard), {}).get('source', 'none'))])
        result['tables'].append(table('短猫运行统计', ['侵蚀等级', '战斗次数', '有效轮数', '平均战斗秒数', '平均每轮秒数', '研究装置', '获取率（%）', '统计来源'], rows))
    elif category == 'action':
        from module.statistics.opsi_month import get_ap_timeline, get_coins_timeline
        ap = get_ap_timeline(year, month_number, instance)
        coins = get_coins_timeline(year, month_number, instance)
        ap_normalized = [
            {**row, 'ap': row['ap_total'] if row.get('ap_total') is not None else row.get('ap')}
            for row in ap
        ]
        result['series'] = [series(ap_normalized, 'ap', '行动力'), series(ap, 'asset', '行动力资产'),
                            series(ap, 'distance', '海里数'), series(coins, 'yellow_coins', '作战补给凭证'),
                            series(coins, 'purple_coins', '特别兑换凭证')]
    elif category == 'commission':
        from module.statistics.commission_income_stats import get_commission_income_interval_summary
        start = selected.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        if period != 'month':
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if period == 'week':
                start -= timedelta(days=start.weekday())
            end = now
        summary = get_commission_income_interval_summary(instance, start, end)
        metric('完成委托', summary['total_commissions'], '项')
        labels = {**RESOURCE_LABELS, 'Chip': '心智单元'}
        for name, item in summary['items'].items():
            metric(labels[name], item['total'])
        result['tables'].append(table('委托收益明细', ['资源', '总收益', '掉落记录数', '平均每次掉落'],
            [[labels[item['name']], item['total'], item['count'], item['avg']] for item in summary['detail_rows']]))
        entries = []
        cursor = start.replace(day=1)
        while cursor < end:
            entries.extend(db.get_commission_income(instance, cursor.year, cursor.month))
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        entries = [item for item in entries if start.isoformat(sep=' ') <= str(item.get('ts', '')).replace('T', ' ') < end.isoformat(sep=' ')]
        entries.sort(key=lambda item: item['ts'])
        from module.statistics.commission_income_stats import COMMISSION_ITEM_NAME_MAP
        normalized = [{**item, 'items': {COMMISSION_ITEM_NAME_MAP.get(k, k): v for k, v in item.get('items', {}).items()}} for item in entries]
        result['tables'].append(table('委托结算记录', ['时间', '委托数量', '钻石', '魔方', '心智单元', '石油', '物资'],
            [[item['ts'], item.get('commission_count', 1), *[item['items'].get(k) for k in ('Gem', 'Cube', 'Chip', 'Oil', 'Coin')]] for item in normalized],
            default_sort={'index': 0, 'descending': True}))
        result['series'] = [series([{'ts': item['ts'], **item['items']} for item in normalized], k, labels[k]) for k in ('Gem', 'Cube', 'Chip', 'Oil', 'Coin')]
    elif category == 'ships':
        from module.statistics.ship_exp_stats import ShipExpStats
        from module.statistics.opsi_month import get_opsi_stats
        stats = ShipExpStats(instance_name=instance)
        data = stats.data
        metric('目标等级', data.get('target_level', 125))
        metric('预估经验效率', stats.get_exp_per_hour(), '/小时')
        metric('平均战斗时长', stats.get_average_battle_time(), '秒')
        metric('平均每轮时长', stats.get_average_round_time(), '秒')
        metric('短猫平均战斗时长', stats.get_average_meow_battle_time(), '秒')
        today = stats.get_today_stats() or {}
        metric('今日战斗', today.get('battle_count'), '场')
        metric('今日经验', today.get('total_exp_gained'))
        metric('今日运行', round(today['total_run_time'] / 60, 1) if 'total_run_time' in today else None, '分钟')
        battles = get_opsi_stats(instance).summary()['total_battles']
        progress = stats.get_all_progress(battles)
        result['tables'].append(table('舰船升级进度', ['位置', '等级', '当前经验', '累计经验', '目标经验', '检测后战斗数', '还需经验', '还需战斗', '预估用时'],
            [[p.get(k) for k in ('position', 'level', 'current_exp', 'total_exp', 'target_exp', 'battles_done', 'exp_needed', 'battles_needed', 'time_needed')] for p in progress],
            f"上次检测：{data.get('last_check_time', '尚未检测')}；舰队：{data.get('fleet_index', '—')}。"))
        daily = [{'ts': key, **value} for key, value in sorted(data.get('daily_stats', {}).items())]
        result['series'] = [series(daily, 'total_exp_gained', '每日经验'), series(daily, 'battle_count', '每日战斗'), series(daily, 'total_run_time', '每日运行秒数')]
    elif category == 'loot':
        from module.statistics.azurstats import AzurStats
        rows = []
        with _loot_lock:
            cached = AzurStats.load_meowofficer_farming(instance=instance)
        for row in cached:
            if row[2] > 0:
                rows.append([int(row[0]), datetime.fromtimestamp(row[1]).isoformat(sep=' '), float(row[2]), *[round(float(value), 4) for value in row[3:]]])
        result['tables'].append(table('短猫掉落收益', AzurStats.meowofficer_farming_labels, rows))
        result['notes'].append('仅统计当前实例的掉落；旧记录缺少实例信息，作为历史共享数据保留，不计入当前实例。')
    return result

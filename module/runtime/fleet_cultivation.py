"""Read-only cultivation projections for explicitly selected physical cards."""
import json
from functools import lru_cache
from pathlib import Path

from module.api.protocol import ApiError
from module.runtime.mind_calculator import catalog, find_ship


@lru_cache(maxsize=1)
def rules():
    return json.loads((Path(__file__).parents[2] / 'assets/ship/cultivation.json').read_text())


def mind_costs_100_to_120():
    data = rules()
    return {rarity: sum(data['awaken'][str(level)][rarity]['mind'] for level in (100, 105, 110, 115))
            for rarity in ('N', 'R', 'SR', 'SSR', 'UR')}


def project(cards, ship_ids, target_level=120):
    by_id = {card['id']: card for card in cards}
    if len(set(ship_ids)) != len(ship_ids) or any(ship_id not in by_id for ship_id in ship_ids):
        raise ApiError('INVALID_PARAMS', '所选舰船已不存在或包含重复副本，请重新选择')
    data, rows = rules(), []
    for ship_id in ship_ids:
        card = by_id[ship_id]
        level = card['level']
        info = find_ship(card['name'])
        if not info:
            # The confirmed group disambiguates names shared by different ships.
            matches = [item for item in catalog()['ships'].values()
                       if item['group_type'] == card.get('group_type')
                       and card['name'] in (item['name'], item.get('raw_name'))]
            info = matches[0] if len(matches) == 1 else None
        rarity = info['base_rarity'] if info else None
        row = dict(id=ship_id, name=card['name'], current_level=card['level'], level=level,
                   target_level=target_level,
                   mind=None, mind2=None, gold=None,
                   status='unknown', notes=[], stages=[])
        if (card.get('review') or not info or card.get('group_type') != info['group_type']
                or card.get('base_rarity') != rarity or not 1 <= level <= 125
                or rarity not in ('N', 'R', 'SR', 'SSR', 'UR')):
            row['notes'].append('身份、等级或基础稀有度待核对，暂不计入资源合计')
            rows.append(row)
            continue
        if info.get('group') == '布里':
            row['notes'].append('本计算暂不支持布里的养成费用，未计入资源合计')
            rows.append(row)
            continue
        row['status'] = 'exact'
        # At an awakening boundary, its next awakening is still unpaid.
        cap = next((n for n in (100, 105, 110, 115, 120, 125) if n >= level), 125)
        row['mind'] = row['mind2'] = row['gold'] = 0
        for threshold in (100, 105, 110, 115, 120):
            if cap <= threshold < target_level:
                cost = data['awaken'][str(threshold)][rarity]
                row['stages'].append(threshold)
                for key in ('mind', 'mind2', 'gold'):
                    row[key] += cost[key]
        rows.append(row)
    return dict(ships=rows, target_level=target_level, included=len(rows),
                mind_costs_100_to_120=mind_costs_100_to_120(),
                unknown=sum(row['status'] == 'unknown' for row in rows),
                mind=sum(row['mind'] or 0 for row in rows), mind2=sum(row['mind2'] or 0 for row in rows),
                gold=sum(row['gold'] or 0 for row in rows), rules_sha256=data['source_sha256'])

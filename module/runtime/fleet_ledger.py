"""舰船底账的类型校验与待确认差异，不操作设备。"""
from collections import Counter

CARD_FIELDS = ('group_type', 'name', 'level', 'rarity', 'base_rarity', 'extra_exp', 'review', 'source', 'full_star', 'form')
RARITIES = ('', 'N', 'R', 'SR', 'SSR', 'UR')


def integer(value, label, low=0, high=None, *, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not int or value < low or (high is not None and value > high):
        raise ValueError(f'{label} 必须是有效整数')
    return value


def card(values, base=None):
    result = dict(group_type=None, name='', level=0, rarity='', base_rarity='', extra_exp=None,
                  review=False, source='', full_star=None, form=None)
    if base:
        result.update({key: base[key] for key in CARD_FIELDS if key in base})
    result.update({key: values[key] for key in CARD_FIELDS if key in values})
    if not isinstance(result['name'], str) or not 1 <= len(result['name']) <= 100:
        raise ValueError('舰船名称不能为空且不能超过 100 字')
    if result['group_type'] is None and not result['review']:
        from module.runtime import fleet_tech, mind_calculator
        info = mind_calculator.find_ship(result['name'])
        result['group_type'] = (info['group_type'] if info else
                                fleet_tech.catalog()['aliases'].get(mind_calculator.normalize_name(result['name'])))
    integer(result['group_type'], '舰船类型', 1, nullable=True)
    integer(result['level'], '等级', 0, 125)
    integer(result['extra_exp'], '零散经验', nullable=True)
    if result['full_star'] is not None and type(result['full_star']) is not bool:
        raise ValueError('满星状态必须是布尔值或空值')
    if result['form'] not in (None, 'base', 'retrofit'):
        raise ValueError('舰船形态无效')
    if result['group_type'] is not None:
        from module.runtime import fleet_tech
        info = next((row for row in fleet_tech.catalog()['ships'] if row['group_type'] == result['group_type']), None)
        if info is None and not result['review']:
            raise ValueError('舰船身份不在图鉴中，请保留为待核对记录')
        if result['form'] == 'retrofit' and info and not info['retrofit_names']:
            raise ValueError('该舰船没有已知改造形态')
    for key in ('rarity', 'base_rarity'):
        if result[key] not in RARITIES:
            raise ValueError('稀有度无效')
    for key in ('review',):
        if type(result[key]) is not bool:
            raise ValueError(f'{key} 必须是布尔值')
    if not isinstance(result['source'], str) or len(result['source']) > 200:
        raise ValueError('来源不能超过 200 字')
    from module.runtime import fleet_tech
    result['full_star'] = fleet_tech.full_star_state(result)
    return result


def observed_fields(raw):
    # Only supplied fields participate in a scan or import update.
    return tuple(key for key in CARD_FIELDS if key in raw)


def changed(before, after, fields):
    return [key for key in fields if key != 'source' and before.get(key) != after.get(key)]


def proposals(current, incoming, *, complete):
    """Exact multiset matches first; uncertain duplicate identity needs the player's choice."""
    remaining = {row['id']: row for row in current}
    waiting, output = [], []
    for raw in incoming:
        values = card(raw)
        fields = observed_fields(raw)
        gid = values['group_type'] if not values['review'] else None
        matches = [row for row in remaining.values() if gid is not None and row['group_type'] == gid
                   and not changed(row, values, fields)]
        if matches:
            del remaining[min(matches, key=lambda row: row['id'])['id']]
        else:
            waiting.append((values, fields, gid))
    counts = Counter(gid for _, _, gid in waiting if gid is not None)
    unresolved = set()
    for values, fields, gid in waiting:
        matches = [row for row in remaining.values() if gid is not None and row['group_type'] == gid]
        if len(matches) == 1 and counts[gid] == 1:
            target = matches[0]['id']
            del remaining[target]
            operation = 'update'
        elif matches:
            operation, target = 'resolve', None
            unresolved.add(gid)
        else:
            operation, target = 'add', None
        output.append(dict(operation=operation, ship_id=target, values=values, fields=fields,
                           candidates=[row['id'] for row in matches] if operation == 'resolve' else []))
    if complete:
        for row in remaining.values():
            if row['group_type'] is not None and row['group_type'] not in unresolved and not row['review']:
                output.append(dict(operation='remove', ship_id=row['id'], values=card(row), fields=()))
    return output

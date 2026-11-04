"""Static catalog and authoritative account milestones; no game-device operations."""
import copy
import hashlib
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from module.runtime.mind_calculator import normalize_name

ROOT = Path(__file__).parents[2]


def read_record(data):
    """科技人工记录只来自独立舰船数据库，忽略旧配置内容。"""
    value = data.get('technology', {})
    if not isinstance(value, dict):
        raise ValueError('舰船科技记录格式无效，已保留原始数据')
    return copy.deepcopy(value)


@lru_cache(maxsize=1)
def catalog():
    """把按群组生成的科技索引与现有共享舰船资料关联。"""
    index = json.loads((ROOT / 'assets/ship/fleet_tech.json').read_text(encoding='utf-8'))
    shared = json.loads((ROOT / 'assets/ship/ship_data.json').read_text(encoding='utf-8'))
    rows, aliases, points = [], defaultdict(set), defaultdict(int)
    for entry in index['ships']:
        gid = entry['group_type']
        base = shared[str(gid * 10 + 1)]
        row = dict(entry, name=base['name']['cn'], names=base['name'], nationality=base['nationality'],
                   rarity=('DR' if base['rarity_name'] in ('UR', 'DR') else 'PR') if entry['blueprint'] else base['rarity_name'],
                   type=base['type'],
                   full_star_rule='explicit_breakthrough' if entry['blueprint'] or base['nationality'] == 97
                   or base['rarity_name'] == 'UR' else 'ordinary_level_cap',
                   variant='child' if base.get('is_child') else
                   'mu' if 'μ兵装' in base['name']['cn'] else '', retrofit_names=[], scan_types=[base['type']])
        rows.append(row)
        if entry['technology']:
            points[str(row['nationality'])] += sum(entry['technology'][k] for k in ('pt_get', 'pt_upgrage', 'pt_level'))
        aliases[normalize_name(row['name'])].add(gid)
    # 改造名按真实群组归并，不能靠去掉“改”或相似名字猜测身份。
    known = {row['group_type'] for row in rows}
    by_group = {row['group_type']: row for row in rows}
    for ship_id, row in shared.items():
        gid = row['group_type']
        if gid not in known or int(ship_id) // 10 != gid:
            continue
        if row['type'] not in by_group[gid]['scan_types']:
            by_group[gid]['scan_types'].append(row['type'])
        for name in row.get('retrofit_names', []):
            aliases[normalize_name(name)].add(gid)
            by_group[gid]['retrofit_names'].append(name)
    names = {(row['name'], row['nationality'], row['type']) for row in rows}
    for row in rows:
        if (not row['variant'] and row['name'].startswith('小')
                and (row['name'][1:], row['nationality'], row['type']) in names):
            row['variant'] = 'child'
    for ship in shared.values():
        gid = ship['group_type']
        if gid not in by_group or not ship['is_retrofit']:
            continue
        row = by_group[gid]
        if (normalize_name(ship['name']['cn']) in {normalize_name(name) for name in row['retrofit_names']}
                and ship['type'] not in row['scan_types']):
            row['scan_types'].append(ship['type'])
    return dict(version=index['version'], updated_at=index['updated_at'], source_commit=index['source_commit'],
                ships=rows, nations=index['nations'], nation_points=dict(points), max_points=sum(points.values()),
                aliases={name: next(iter(ids)) for name, ids in aliases.items() if len(ids) == 1})


def public_catalog():
    """名称索引仅供服务端确认身份，不重复传给浏览器。"""
    return {key: value for key, value in catalog().items() if key != 'aliases'}


def revision(record):
    """空记录也有稳定版本，供人工编辑进行并发保护。"""
    return hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


MILESTONES = ('owned', 'full_star', 'lv120')


def fixed_full_star_state(ship):
    """Return a state only when the level and confirmed identity force it."""
    level = ship.get('level', 0)
    if type(level) is int and 1 <= level < 70:
        return False
    if type(level) is int and level >= 100 and not ship.get('review'):
        info = next((row for row in catalog()['ships'] if row['group_type'] == ship.get('group_type')), None)
        if info and info['full_star_rule'] == 'ordinary_level_cap':
            return True
    return None


def full_star_state(ship):
    """Apply fixed game constraints when writing current ship data."""
    forced = fixed_full_star_state(ship)
    if forced is not None:
        return forced
    return ship.get('full_star')


def positive_facts(ship):
    """Read persisted card states; only legacy inputs need level-rule conversion."""
    info = next((row for row in catalog()['ships'] if row['group_type'] == ship.get('group_type')), None)
    if info is None or ship.get('review'):
        return set()
    level = ship.get('level', 0)
    facts = {'owned'}
    if type(level) is int and level >= 120:
        facts.add('lv120')
    if (ship['full_star'] if 'full_star' in ship else full_star_state(ship)) is True:
        facts.add('full_star')
    return facts


def progress(record, group_type):
    gid = str(group_type)
    saved = record.get('progress', {}).get(gid, {})
    cards = [row for row in record.get('holdings', []) if row.get('group_type') == group_type and not row.get('review')]
    evidence = {key: [row['id'] for row in cards if 'id' in row and key in positive_facts(row)] for key in MILESTONES}
    state = {key: saved.get(key) is True for key in MILESTONES}
    status = ('complete' if all(state[key] is True for key in MILESTONES) else
              'unowned' if state['owned'] is False else 'unfinished')
    return dict(group_type=group_type, **state, awakening_pending=saved.get('awakening_pending') is True,
                status=status, points=0,
                current_count=len(cards), current_level=max((row['level'] for row in cards), default=None),
                evidence=evidence,
                source=saved.get('source', ''), updated_at=saved.get('updated_at', ''))


def scan_summary(ships, *, min_level, max_level, reached_bottom, filters_clear,
                 physical_count, expected_count):
    """Count uncertain cards and require full dock coverage before suggesting removals."""
    known = {row['group_type'] for row in catalog()['ships']}
    reviews = 0
    for ship in ships:
        gid, level = ship.get('group_type'), ship.get('level')
        if type(level) is int and 1 <= level <= 125 and not min_level <= level <= max_level:
            continue
        if (ship.get('review') or type(gid) is not int or gid not in known
                or type(level) is not int or not 1 <= level <= 125):
            reviews += 1
    complete = (min_level == 1 and max_level == 125 and reached_bottom and filters_clear
                and type(expected_count) is int and physical_count == expected_count == len(ships) and not reviews)
    return dict(complete=bool(complete), review_count=reviews)


def ship_type(value):
    """导驱与风帆各形态共用界面分类，但每条加成仅累计一次。"""
    return 1 if value in (20, 21) else 22 if value in (22, 23, 24) else value


def report(record):
    """Count confirmed account milestones against technology-bearing catalog types."""
    rows, bonuses = [], defaultdict(lambda: defaultdict(int))
    confirmed_points = completed = 0
    milestone_counts = {key: 0 for key in MILESTONES}

    def add(types, attr, value):
        for target in {ship_type(t) for t in types}:
            bonuses[str(target)][str(attr)] += value

    for info in catalog()['ships']:
        row = progress(record, info['group_type'])
        owned, full_star, lv120 = row['owned'], row['full_star'], row['lv120']
        if info['technology']:
            for key in MILESTONES:
                milestone_counts[key] += row[key] is True
        tech = info['technology']
        if tech:
            if owned:
                row['points'] += tech['pt_get']
                add(tech['add_get_shiptype'], tech['add_get_attr'], tech['add_get_value'])
            if full_star:
                row['points'] += tech['pt_upgrage']
            if lv120:
                row['points'] += tech['pt_level']
                add(tech['add_level_shiptype'], tech['add_level_attr'], tech['add_level_value'])
            completed += all(row[key] is True for key in MILESTONES)
        confirmed_points += row['points']
        rows.append(row)
    ship_bonuses = {t: dict(attrs) for t, attrs in bonuses.items()}
    levels = record.get('nations', {})
    for key, value in levels.items():
        if value and key in catalog()['nations']:
            for types, attr, amount in catalog()['nations'][key][value - 1]:
                add(types, attr, amount)
    nation_bonuses = {t: {a: n - ship_bonuses.get(t, {}).get(a, 0) for a, n in attrs.items()
                          if n - ship_bonuses.get(t, {}).get(a, 0)} for t, attrs in bonuses.items()}
    return dict(revision=revision(record), rules_version=1, data_version=record.get('snapshot_revision'),
                ships=rows, nation_levels=levels,
                milestone_counts=milestone_counts,
                ship_bonuses=ship_bonuses, nation_bonuses=nation_bonuses,
                bonuses={t: dict(attrs) for t, attrs in bonuses.items()}, confirmed_points=confirmed_points,
                completed=completed)

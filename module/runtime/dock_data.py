"""独立舰船数据库的纯分析投影；不读取旧任务配置中的舰船数据。"""
import copy
from module.runtime import fleet_tech as tech


def has_snapshot(data):
    value = data.get('snapshot')
    return isinstance(value, dict) and isinstance(value.get('ships'), list)


def build_snapshot(ships, *, min_level, max_level, reached_bottom, filters_clear,
                   physical_count, expected_count, updated_at):
    """保留每个物理副本，完整性与科技扫描的缺失保护使用同一规则。"""
    if (type(min_level) is not int or type(max_level) is not int
            or not 1 <= min_level <= max_level <= 125):
        raise ValueError('扫描等级范围必须满足 1 ≤ 最低等级 ≤ 最高等级 ≤ 125')
    rows = copy.deepcopy(ships)
    for index, row in enumerate(rows):
        row.setdefault('slot', index)
    scan = tech.scan_summary(rows, min_level=min_level, max_level=max_level,
                             reached_bottom=reached_bottom, filters_clear=filters_clear,
                             physical_count=physical_count, expected_count=expected_count)
    output = dict(version=1, ships=rows, updated_at=updated_at, min_level=min_level,
                  max_level=max_level, reached_bottom=bool(reached_bottom),
                  filters_clear=bool(filters_clear), physical_count=physical_count,
                  expected_count=expected_count, complete=scan['complete'],
                  review_count=scan['review_count'], source='scan')
    output['revision'] = tech.revision(output)
    return output


def read_snapshot(data):
    """仅接受数据库底账；无数据时返回空状态，不回退到配置 JSON。"""
    if has_snapshot(data):
        output = copy.deepcopy(data['snapshot'])
        output.setdefault('source', 'scan')
        output.setdefault('revision', tech.revision(output))
        return output
    return dict(version=1, ships=[], updated_at='', min_level=1, max_level=125,
                reached_bottom=False, filters_clear=False, physical_count=0,
                expected_count=None, complete=False, review_count=0,
                revision=tech.revision({}), source='empty')


def technology_record(data):
    """Read cumulative milestones directly; holdings explain facts without remerging them."""
    options = tech.read_record(data)
    snapshot = read_snapshot(data)
    return dict(progress=copy.deepcopy(options.get('progress', {})),
                nations=copy.deepcopy(options.get('nations', {})),
                holdings=copy.deepcopy(snapshot['ships']),
                snapshot_revision=snapshot['revision'])


def report_snapshot(data):
    snapshot = read_snapshot(data)
    return {key: snapshot[key] for key in ('revision', 'updated_at', 'min_level', 'max_level',
                                          'ships', 'complete', 'review_count', 'source')}

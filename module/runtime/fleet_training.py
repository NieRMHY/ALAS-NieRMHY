"""普通舰队培养条件与持久记录；不操作设备，不估算等级或好感。"""

from copy import deepcopy
from datetime import datetime

from module.config.time_source import now
from module.config.redirect_utils.utils import fleet_training_interval_redirect
from module.combat.emotion_state import EmotionRecoveryState
from module.exception import FleetManagementError
from module.retire.ship_name import ShipNameMatcher
from module.runtime.mind_calculator import find_ship
from module.runtime.fleet_rotation import ROTATION_PATH, active_fleets

LEVEL_PATH = 'FleetInfo.FleetLevelTraining'
AFFINITY_PATH = 'FleetInfo.FleetAffinityTraining'
TRAINING_PATH = 'FleetInfo.FleetTraining.State'
INTERVAL_PATH = 'FleetInfo.FleetTraining.CheckIntervalHours'
FULL_RECORD_PATH = 'FleetInfo.FleetTraining.FullScanRecord'


def _date(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def mark_full_scan(config):
    config.cross_set(FULL_RECORD_PATH, now())


def _check_signature(config):
    task = config.task.command
    fields = ('Mode', 'Fleet1Control', 'Fleet2Control', 'Fleet1Recover', 'Fleet2Recover',
              'Fleet1Oath', 'Fleet2Oath', 'Fleet1Onsen', 'Fleet2Onsen')
    return dict(goals=goals(config), mood=config.cross_get(ROTATION_PATH + '.Enabled', False),
                rules=config.cross_get(ROTATION_PATH + '.Rules', '{}'),
                fleets={str(role): fleet for role, fleet in active_fleets(config).items()},
                selected_only=config.cross_get(ROTATION_PATH + '.SelectedOnly', False),
                order=config.cross_get(task + '.Fleet.FleetOrder'),
                emotion={field: config.cross_get(task + '.Emotion.' + field) for field in fields})


def persist_context(config, context):
    """仅保存已核对的计时与培养心情相位，不改写逐船培养记录。"""
    if not isinstance(context.get('training_checked_at'), datetime):
        return
    saved = state(config)
    training = {}
    for role, item in context.get('training', {}).items():
        recovery = item.get('state')
        if recovery is not None:
            training[str(role)] = dict(actual=item['actual'], slots=item['slots'], value=recovery.value,
                                       state=recovery.export())
    saved.setdefault('checks', {})[config.task.command] = dict(
        signature=_check_signature(config), checked_at=context['training_checked_at'].isoformat(),
        goals=context.get('training_goals', {}), training=training,
        morale_low=context.get('morale_low', {}), scanned=context.get('scanned', False))
    config.cross_set(TRAINING_PATH, saved)


def restore_context(config, context):
    """跨任务启动恢复计时和已扣减的培养心情，不能从旧截图重新估算消耗。"""
    if isinstance(context.get('training_checked_at'), datetime):
        return
    checked = state(config).get('checks', {}).get(config.task.command, {})
    if not isinstance(checked, dict):
        return
    date = _date(checked.get('checked_at'))
    if date is None:
        return
    # 配置变化不能绕过实读间隔；心情状态由 RotationEmotion 按当前舰位和恢复设置复核。
    context['training_checked_at'] = date
    if not isinstance(checked.get('training', {}), dict) or not isinstance(checked.get('morale_low', {}), dict):
        return
    training = {}
    try:
        for role, item in checked.get('training', {}).items():
            data = item['state']
            recovery = EmotionRecoveryState.restore(data, item['value'], _date(data['record']), *data['signature'])
            recovery.advance(now())
            training[int(role)] = dict(actual=item['actual'], slots=item['slots'], state=recovery)
    except (ValueError, TypeError, KeyError):
        return
    context.update(training_checked_at=date, training_goals=checked.get('goals', {}),
                   training_mood=config.cross_get(ROTATION_PATH + '.Enabled', False) is True,
                   training_rules=deepcopy(config.cross_get(ROTATION_PATH + '.Rules', '{}')),
                   training_fleets=active_fleets(config), training=training,
                   morale_low=checked.get('morale_low', {}),
                   scanned=checked.get('scanned', False) and
                   (bool(training) or not config.cross_get(ROTATION_PATH + '.SelectedOnly', False)),
                   training_selected_only=config.cross_get(ROTATION_PATH + '.SelectedOnly', False) is True)


def invalidate_context(config):
    saved = deepcopy(config.cross_get(TRAINING_PATH, {}))
    if (isinstance(saved, dict) and isinstance(saved.get('checks'), dict)
            and config.task.command in saved['checks']):
        del saved['checks'][config.task.command]
        config.cross_set(TRAINING_PATH, saved)


def goals(config):
    return {metric: config.cross_get(path + '.Target', default) for metric, path, default in
            (('level', LEVEL_PATH, 120), ('affinity', AFFINITY_PATH, 100))
            if config.cross_get(path + '.Enabled', False) is True}


def interval(config):
    """三种调度共用小时实读间隔，兼容尚未迁移的独立旧配置。"""
    hours = config.cross_get(INTERVAL_PATH, None)
    return fleet_training_interval_redirect(config.cross_get('FleetInfo', {})) if hours is None else hours


def due(config, context):
    signature = goals(config)
    if not signature:
        return False
    restore_context(config, context)
    checked = context.get('training_checked_at')
    return (not isinstance(checked, datetime)
            or (now() - checked).total_seconds() / 3600 >= interval(config))


def mark_checked(config, context, targets=None):
    """记录共用读取时刻；下一轮到期再按当前目标完整核对。"""
    context['training_checked_at'] = now()
    context['training_goals'] = dict(goals(config) if targets is None else targets)
    context['training_mood'] = config.cross_get(ROTATION_PATH + '.Enabled', False) is True
    context['training_rules'] = deepcopy(config.cross_get(ROTATION_PATH + '.Rules', '{}'))
    context['training_fleets'] = active_fleets(config)
    persist_context(config, context)


def state(config):
    saved = deepcopy(config.cross_get(TRAINING_PATH, {}))
    if not isinstance(saved, dict) or any(not isinstance(saved.get(key, {}), dict)
                                         for key in ('records', 'pending', 'readings', 'checks')):
        raise FleetManagementError('培养记录格式无效，保留原记录，请检查配置')
    saved.setdefault('records', {})
    saved.setdefault('pending', {})
    return saved


def ships(result, fleet):
    return {item['slot']: item for category in ('main', 'vanguard')
            for item in result.get(category, {}).get(str(fleet), [])
            if type(item.get('slot')) is int and item.get('occupied', True)}


def identity(ship, result, *, allow_duplicates=False):
    """默认要求唯一身份；同名仅可用于按舰位保存读数，不能据此完成或换船。"""
    if not ship or ship.get('review') or not ship.get('name'):
        return None
    info = find_ship(ship['name'])
    if info is None:
        return None
    if ship.get('raw_name'):
        raw = find_ship(ship['raw_name'])
        if raw is None:
            # 编队扫描已确认的截短原文须按同一规则复核，不能再次要求完整拼写。
            matched, status = ShipNameMatcher('cn').approximate(ship['raw_name'])
            raw = find_ship(matched) if status in ('exact', 'prefix', 'similar') else None
        if raw is None or raw['name'] != info['name']:
            return None
    name = info['name']
    matches = sum(item.get('name') == ship['name'] for category in ('main', 'vanguard')
                  for fleet in result.get(category, {}).values() for item in fleet if item.get('occupied', True))
    return name if matches == 1 or (allow_duplicates and matches > 1) else None


def completed(record, targets):
    """必须同一舰船的所有已启用条件都有可靠读数；未知不视为完成。"""
    return bool(targets) and all(type(record.get(metric)) is int and record[metric] >= target
                                 for metric, target in targets.items())


def excluded(record, targets):
    """完成是持久排除；修改目标不能把已完成舰船自动选回来。"""
    done = record.get('completed_for', {})
    return bool(targets) and isinstance(done, dict) and bool(done)


def observe(saved, name, reading, targets, *, fleet=None, slot=None, emotion=None):
    record = dict(saved['records'].get(name, {}), name=name, checked_at=now().isoformat(timespec='seconds'))
    # 同次检查重新写入全部已启用条件，不能把旧高好感与新等级拼成完成。
    record.update({metric: reading.get(metric) for metric in targets})
    if 'level' in targets:
        # level 已按大世界经验表折算；保留界面等级与原始经验，避免重复累加存储经验。
        record['exp'] = reading.get('exp')
        record['display_level'] = reading.get('display_level', reading.get('level'))
    if type(fleet) is int and 1 <= fleet <= 6 and type(slot) is int and 1 <= slot <= 6:
        # 保存当次已确认的位置和已有心情读数，仅用于记录展示，不额外操作游戏。
        record.update(fleet=fleet, slot=slot,
                      emotion=emotion if type(emotion) is int and 0 <= emotion <= 150 else None)
    if completed(record, targets) and not record.get('completed_for'):
        record['completed_for'] = dict(targets)
        record['completed_at'] = now().isoformat(timespec='seconds')
    saved['records'][name] = record
    return completed(record, targets)

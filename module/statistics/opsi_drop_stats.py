"""大世界掉落统计汇总。

把 azurstats_local.db 里逐次记录的掉落明细（opsi_items）按时间窗口聚合，供
WebUI 统计页「大世界掉落」分类展示。数据入口在 module/statistics/azurstats.py：
除侵蚀1练级外的大世界任务，只要掉落记录开关不是「不记录」（保存与上传都算），
任务跑完就会把掉落解析入库，本模块只负责读和汇总。

展示口径（2026-09-25 用户定，暂时只看两类，其余物品照常入库、只是不展示）：
    - 金菜：通用/主炮/鱼雷/防空炮/舰载机 部件T4（Plate*T4）；
    - 彩图纸：舰炮/鱼雷/防空炮/舰载机 研发图纸UR型（GearDesignPlan*T5）。

要放开口径：在 should_show() 里加规则、往 assets/stats/opsi_item_names.json
补中文名与稀有度，再把要固定显示（没掉过也占一行）的物品加进 SHOW_ITEMS 即可。
"""

import json
import typing as t
from datetime import datetime

from module.logger import logger

# 模板名 -> 中文名/稀有度的静态表，中文名按游戏数据（sharecfgdata/item_data_statistics.lua）核对
NAME_TABLE_PATH = './assets/stats/opsi_item_names.json'

# 口径：金菜 = 金色强化部件（T4），彩图纸 = UR 研发图纸（T5）
KIND_PLATE = 'plate'
KIND_DESIGN = 'design'
KIND_LABELS = {KIND_PLATE: '金菜', KIND_DESIGN: '彩图纸'}
PLATE_PREFIX = 'Plate'
PLATE_TIER = 'T4'
DESIGN_PREFIX = 'GearDesignPlan'
DESIGN_TIER = 'T5'
# 固定显示顺序：金菜在前、彩图纸在后；没掉过的也留一行（与科研统计的固定清单一致）
SHOW_ITEMS = (
    'PlateGeneralT4', 'PlateGunT4', 'PlateTorpedoT4', 'PlateAntiAirT4', 'PlatePlaneT4',
    'GearDesignPlanGunT5', 'GearDesignPlanTorpedoT5', 'GearDesignPlanAntiAirT5',
    'GearDesignPlanPlaneT5',
)

# 海域类型 -> 中文标签，取值同 module/azur_stats/image/opsi_zone.py 的 zone_type
ZONE_LABELS = {
    'DANGEROUS': '危险海域',
    'SAFE': '安全海域',
    'OBSCURE': '隐秘海域',
    'ABYSSAL': '深渊海域',
    'STRONGHOLD': '要塞海域',
    'ARCHIVE': '档案海域',
    'UNKNOWN': '未知海域',
}

_name_table: t.Optional[dict] = None
_task_names: t.Optional[dict] = None


def load_name_table() -> dict:
    """读取模板名 -> 中文名/稀有度表（进程内缓存）。

    Returns:
        dict: {模板名: {'zh': ..., 'en': ..., 'rarity': ...}}；表缺失时返回空字典。
    """
    global _name_table
    if _name_table is None:
        try:
            with open(NAME_TABLE_PATH, encoding='utf-8') as f:
                _name_table = json.load(f)
        except (OSError, ValueError):
            logger.warning(f'[大世界掉落] 名称表不存在或损坏: {NAME_TABLE_PATH}')
            _name_table = {}
    return _name_table


def item_info(template_name: str) -> dict:
    """取物品的中文名与稀有度。

    Args:
        template_name (str): 模板名（不含扩展名与数字后缀），如 'PlateGeneralT4'。

    Returns:
        dict: {'zh': 中文名, 'en': 英文名, 'rarity': 稀有度}；查不到时用模板名兜底。
    """
    info = load_name_table().get(template_name)
    if info:
        return info
    return {'zh': template_name, 'en': template_name, 'rarity': None}


def kind_of(template_name: str) -> t.Optional[str]:
    """判断掉落属于口径里的哪一类。

    Args:
        template_name (str): 模板名。

    Returns:
        str: KIND_PLATE（金菜）/ KIND_DESIGN（彩图纸）；口径外的物品返回 None。
    """
    name = str(template_name or '')
    if name.startswith(PLATE_PREFIX) and name.endswith(PLATE_TIER):
        return KIND_PLATE
    if name.startswith(DESIGN_PREFIX) and name.endswith(DESIGN_TIER):
        return KIND_DESIGN
    return None


def should_show(template_name: str) -> bool:
    """判断某件掉落是否进入收获明细。

    Args:
        template_name (str): 模板名。

    Returns:
        bool: 是否展示。
    """
    return kind_of(template_name) is not None


def _load_task_names() -> dict:
    """读取任务中文名（进程内缓存）。

    名字取自配置页同一份 i18n（`Task.<任务名>.name`），避免两处各维护一份；
    顺序沿用 i18n 里的顺序（与配置页菜单一致），查不到时退回任务标识。

    Returns:
        dict: {genre: 中文名}，如 {'opsi_abyssal': '深渊坐标'}。
    """
    global _task_names
    if _task_names is None:
        names = {}
        try:
            import inflection

            from module.config.utils import filepath_i18n
            from module.statistics.azurstats import is_opsi_drop_genre

            with open(filepath_i18n('zh-CN'), encoding='utf-8') as f:
                data = json.load(f)
            for key, value in (data.get('Task') or {}).items():
                if not isinstance(value, dict):
                    continue
                genre = inflection.underscore(key)
                if is_opsi_drop_genre(genre):
                    names[genre] = value.get('name') or genre
        except (OSError, ValueError, ImportError):
            logger.warning('[大世界掉落] 任务名表读取失败，任务列显示任务标识')
        _task_names = names
    return _task_names


def task_label(genre: str) -> str:
    """大世界任务的中文名。

    Args:
        genre (str): 掉落分类，即任务名转下划线后的写法（如 'opsi_abyssal'）。

    Returns:
        str: 任务中文名；不在 i18n 里的任务退回标识本身。
    """
    return _load_task_names().get(str(genre)) or str(genre)


def _pinned_tasks() -> frozenset:
    """有独立掉落截图开关的大世界任务（侵蚀1除外，它不做掉落统计）。

    直接取配置侧那份任务清单，避免两处各维护一份。「大世界商店」「白票商店」
    这类没有开关、也不掉东西的任务不会进下拉。

    Returns:
        frozenset: 任务标识集合，如 {'opsi_abyssal', ...}。
    """
    import inflection

    from module.os.config import OPSI_DROP_RECORD_TASKS
    from module.statistics.azurstats import is_opsi_drop_genre

    return frozenset(
        genre for genre in (inflection.underscore(task) for task in OPSI_DROP_RECORD_TASKS)
        if is_opsi_drop_genre(genre)
    )


def available_tasks(counts: t.Optional[dict] = None, selected: t.Optional[str] = None) -> t.List[dict]:
    """统计页任务筛选下拉的选项。

    固定列出有掉落开关的任务，其余任务（每月开荒、月度Boss、档案坐标、跨月每日…）
    只有真的留下记录、或正被选中时才出现。

    Args:
        counts (dict): {任务标识: 窗口内掉落记录数}，缺省为空。
        selected (str): 当前选中的任务标识，保证它始终在列表里。

    Returns:
        list[dict]: [{'key', 'label', 'count'}, ...]，顺序同配置页菜单。
    """
    counts = counts or {}
    pinned = _pinned_tasks()
    return [
        {'key': genre, 'label': label, 'count': counts.get(genre, 0)}
        for genre, label in _load_task_names().items()
        if genre in pinned or genre in counts or genre == selected
    ]


def zone_text(zone_type: str, zone: str, hazard_level: int) -> str:
    """把海域类型、海域名与侵蚀等级拼成一句话。

    Args:
        zone_type (str): 海域类型，如 'ABYSSAL'。
        zone (str): 海域名（识别不出时为空串）。
        hazard_level (int): 侵蚀等级，未知时为 0。

    Returns:
        str: 如 '要塞海域 East Continental Shelf E（侵蚀3）'。
    """
    label = ZONE_LABELS.get(str(zone_type or '').upper(), '未知海域')
    parts = [label]
    if zone:
        parts.append(str(zone))
    text = ' '.join(parts)
    if hazard_level:
        text += f'（侵蚀{hazard_level}）'
    return text


def _record_key(row: dict) -> str:
    """一次掉落记录的身份：imgid + 任务。

    Args:
        row (dict): opsi_items 明细行。

    Returns:
        str: 记录键。
    """
    return f"{row.get('imgid')}|{row.get('genre')}"


def collect(
    instance: str,
    start: datetime,
    end: datetime,
    task: t.Optional[str] = None,
) -> dict:
    """汇总一段时间内的大世界掉落。

    Args:
        instance (str): ALAS 实例名。
        start (datetime): 统计起点（含）。
        end (datetime): 统计终点（不含）。
        task (str): 只看某个任务（genre）；None 表示全部大世界任务。

    Returns:
        dict: {
            'items': [{'name','zh','en','rarity','kind','amount','count','avg'}, ...],
            'records': [[时间, 任务, 海域, 掉落物], ...]（时间倒序）,
            'total': 口径内掉落总数量,
            'record_count': 口径内掉落记录条数,
            'tasks': [{'key','label','count'}, ...]（供任务筛选，顺序同配置页菜单）,
        }
    """
    from module.statistics.azurstats import AzurStats

    rows = AzurStats.load_opsi_drop_rows(
        instance, int(start.timestamp()), int(end.timestamp()), task=task)

    # 一条记录 = 一次掉落截图（imgid），记录内的物品在解析时就已按 imgid 归好组
    records: t.Dict[str, dict] = {}
    for row in rows:
        key = _record_key(row)
        record = records.get(key)
        if record is None:
            record = {
                'ts': row.get('created_at') or 0,
                'genre': str(row.get('genre') or ''),
                'zone': str(row.get('zone') or ''),
                'zone_type': str(row.get('zone_type') or ''),
                'hazard_level': int(row.get('hazard_level') or 0),
                'items': {},
            }
            records[key] = record
        name = str(row.get('item') or '')
        if not should_show(name):
            continue
        record['items'][name] = record['items'].get(name, 0) + int(row.get('amount') or 0)

    # 只保留掉了口径内物品的记录：那一次只掉别的不算它的一次掉落（与科研统计同口径）
    picked = [record for record in records.values() if record['items']]

    amount_by_item: t.Dict[str, int] = {}
    count_by_item: t.Dict[str, int] = {}
    task_count: t.Dict[str, int] = {}
    for record in picked:
        task_count[record['genre']] = task_count.get(record['genre'], 0) + 1
        for name, amount in record['items'].items():
            amount_by_item[name] = amount_by_item.get(name, 0) + amount
            count_by_item[name] = count_by_item.get(name, 0) + 1

    def build(name: str) -> dict:
        """构建单个掉落物品的月度统计展示字典。

        Args:
            name (str): 物品唯一标识名。

        Returns:
            dict: 包含中英文名称、稀有度、总掉落量、掉落次数及平均值的统计字典。
        """
        info = item_info(name)
        amount = amount_by_item.get(name, 0)
        count = count_by_item.get(name, 0)
        return {
            'name': name,
            'zh': info.get('zh') or name,
            'en': info.get('en') or '',
            'rarity': info.get('rarity'),
            'kind': kind_of(name),
            'amount': amount,
            'count': count,
            'avg': round(amount / count, 1) if count else 0,
        }

    # 固定清单铺开（没掉过的留一行），清单之外新出现的口径内物品追加在后面，不丢数据
    items = [build(name) for name in SHOW_ITEMS]
    extra = [name for name in amount_by_item if name not in set(SHOW_ITEMS)]
    extra.sort(key=lambda name: (-amount_by_item[name], name))
    items.extend(build(name) for name in extra)

    record_rows = [
        [
            datetime.fromtimestamp(int(record['ts'])).isoformat(sep=' '),
            task_label(record['genre']),
            zone_text(record['zone_type'], record['zone'], record['hazard_level']),
            '、'.join(
                f"{item_info(name)['zh']} x{amount}"
                for name, amount in sorted(record['items'].items())
            ),
        ]
        for record in sorted(picked, key=lambda record: record['ts'], reverse=True)
    ]
    tasks = available_tasks(counts=task_count, selected=task)

    return {
        'items': items,
        'records': record_rows,
        'total': sum(item['amount'] for item in items),
        'record_count': len(picked),
        'tasks': tasks,
    }

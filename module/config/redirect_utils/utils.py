"""配置重定向工具函数集。

提供配置版本升级时的值转换函数。
当配置 schema 发生变更时（如选项名称修改、值格式调整），
这些函数负责将旧格式的配置值转换为新格式。

重定向函数在 ConfigUpdater.config_redirect() 中被调用，
确保用户升级后无需手动修改配置文件。

常见的重定向场景：
- 选项名称变更（如 'auto' → 'default'）
- 值格式调整（如布尔值 → 枚举值）
- 服务器名称规范化
"""

from module.config.server import to_server


def upload_redirect(value):
    """
    redirect attr about upload.
    """
    if isinstance(value, list):
        if not value[0] and not value[1]:
            return 'do_not'
        elif value[0] and not value[1]:
            return 'save'
        elif not value[0] and value[1]:
            return 'upload'
        else:
            return 'save_and_upload'
    else:
        if not value:
            return 'do_not'
        else:
            return 'save'


def api_redirect(value):
    """
    redirect attr about api.
    """
    if value == 'auto':
        return 'default'
    elif to_server(value) == 'cn':
        return 'cn_gz_reverse_proxy'
    else:
        return 'default'


def dossier_redirect(value):
    """
    OpsiDossierBeacon -> AttackMode
    """
    if value:
        return 'current_dossier'
    else:
        return 'current'


def enhance_favourite_redirect(value):
    """
    EnhanceFavourite -> ShipToEnhance
    """
    if value:
        return 'all'
    else:
        return 'favourite'


def enhance_check_redirect(value):
    """
    CheckPerCategory should be at least 5
    """
    if isinstance(value, int):
        if value < 5:
            return 5
    return value


def emotion_mode_redirect(value):
    """
    CalculateEmotion + IgnoreLowEmotionWarn -> Emotion.Mode
    """
    calculate, ignore = value
    if calculate:
        if ignore:
            return 'calculate_ignore'
        else:
            return 'calculate'
    else:
        if ignore:
            return 'ignore'
        else:
            # Invalid, fallback to calculate
            return 'calculate'


def change_ship_redirect(value):
    """
    FlagshipChange + FlagshipEquipChange -> ChangeFlagship
    """
    ship, equip = value
    if not ship:
        return 'disabled'
    elif equip:
        return 'ship_equip'
    else:
        return 'ship'


def api_redirect2(value):
    """
    remove shanghai proxy, use guangzhou
    """
    if value == 'cn_sh_reverse_proxy':
        return 'cn_gz_reverse_proxy'
    else:
        return value


def coalition_to_frostfall(value):
    """
    将通用难度名转换为霜落活动的内部关卡编号。
    """
    if value == 'easy':
        return 'tc1'
    elif value == 'normal':
        return 'tc2'
    elif value == 'hard':
        return 'tc3'
    else:
        return value


def coalition_to_little_academy(value):
    """
    将旧联动活动的 TC 关卡编号转换为通用难度名。
    """
    normalized = str(value).lower().replace('-', '')
    if normalized == 'tc1':
        return 'easy'
    elif normalized == 'tc2':
        return 'normal'
    elif normalized == 'tc3':
        return 'hard'
    else:
        return value


def execute_fixed_patrol_scan_redirect(value):
    """
    OpsiHazard1Leveling.ExecuteFixedPatrolScan 旧等级枚举 → 布尔开关。

    该配置的形态变过两轮：布尔开关 → 0/1/2 等级 → 又合并回开关（保守模式
    并入效率模式）。存量配置里的数字档位要清洗成布尔，否则复选框会显示
    数字，运行时也容易读错：
    - 0（关闭）           → False
    - 1/2/3（各档强制移动）→ True（等级已合并成同一个效率模式）
    - 布尔值直接透传。
    """
    if isinstance(value, bool):
        return value
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return bool(value)

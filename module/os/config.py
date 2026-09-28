"""大世界（Operation Siren）配置类。

定义大世界地图操作所需的配置参数，包括：
- 地图检测参数（透视检测、网格识别）
- 滑动参数（滑动倍率、最小距离）
- 战斗相关配置（塞壬检测、情绪管理等）
- 故事选项配置

大世界的配置参数与主线战役不同，需要单独定义。
OSConfig 被 OperationSiren 等大世界模块使用。
另提供按任务读取掉落记录开关的 opsi_drop_record()。
"""

# 大世界掉落记录：下列任务各有一个同名开关（见 module/config/argument/argument.yaml
# 的 DropRecord 组），其余任务由 OpsiOther 兜底。
OPSI_DROP_RECORD_TASKS = (
    'OpsiHazard1Leveling',
    'OpsiMeowfficerFarming',
    'OpsiDaily',
    'OpsiObscure',
    'OpsiAbyssal',
    'OpsiStronghold',
    'OpsiExplore',
)
# 与上面某个开关共用记录方式的任务：任务名 → 开关名。共用只影响存图与否，
# 掉落统计仍按各自的 genre 归类（本地解析只放行耄耋相接这一个 genre）。
OPSI_DROP_RECORD_SHARED = {
    'OpsiCrossMonth': 'OpsiDaily',
    'OpsiArchive': 'OpsiObscure',
    'OpsiMonthBoss': 'OpsiAbyssal',
}
OPSI_DROP_RECORD_OTHER = 'OpsiOther'


def opsi_drop_record(config):
    """读取当前大世界任务对应的掉落记录开关。

    任务身份取自 `config.task.command`；智能调度、防止行动力溢出等代理任务
    执行子任务时它已被换成子任务名，因此这里的开关与掉落统计都按子任务归类。

    Args:
        config (AzurLaneConfig): 已绑定当前任务的配置对象。

    Returns:
        str: 记录方式，do_not / save / upload / save_and_upload。
    """
    task = config.task.command
    arg = OPSI_DROP_RECORD_SHARED.get(task)
    if arg is None:
        arg = task if task in OPSI_DROP_RECORD_TASKS else OPSI_DROP_RECORD_OTHER
    return getattr(config, f'DropRecord_{arg}')


class OSConfig:
    """大世界配置参数类。

    定义大世界地图操作所需的所有配置参数。
    这些参数覆盖了地图检测、滑动控制和战斗管理的默认值。

    Attributes:
        STORY_OPTION (int): 剧情选项，-2 表示自动选择。
        MAP_FOCUS_ENEMY_AFTER_BATTLE (bool): 战斗后是否聚焦到敌人位置。
        MAP_HAS_SIREN (bool): 地图是否有塞壬敌人。
        MAP_HAS_FLEET_STEP (bool): 地图是否有步数限制。
        IGNORE_LOW_EMOTION_WARN (bool): 是否忽略低情绪警告。
        MAP_GRID_CENTER_TOLERANCE (float): 网格中心对齐容差。
        MAP_SWIPE_DROP (float): 最小滑动距离阈值。
        MAP_SWIPE_MULTIPLY (tuple): 滑动距离倍率。
        DETECTION_BACKEND (str): 检测后端（'perspective' 或 'homography'）。
    """
    STORY_OPTION = -2

    MAP_FOCUS_ENEMY_AFTER_BATTLE = True
    MAP_HAS_SIREN = True
    MAP_HAS_FLEET_STEP = True
    IGNORE_LOW_EMOTION_WARN = False

    MAP_GRID_CENTER_TOLERANCE = 0.3
    MAP_SWIPE_DROP = 0.35
    MAP_SWIPE_MULTIPLY = (1.174, 1.200)
    MAP_SWIPE_MULTIPLY_MINITOUCH = (1.135, 1.160)
    MAP_SWIPE_MULTIPLY_MAATOUCH = (1.102, 1.126)

    DETECTION_BACKEND = 'perspective'
    MID_DIFF_RANGE_H = (103 - 3, 103 + 3)
    MID_DIFF_RANGE_V = (103 - 3, 103 + 3)
    INTERNAL_LINES_FIND_PEAKS_PARAMETERS = {
        'height': (80, 255 - 40),
        'width': (1.5, 10),
        'prominence': 35,
        'distance': 35,
    }
    EDGE_LINES_FIND_PEAKS_PARAMETERS = {
        'height': (255 - 40, 255),
        'prominence': 10,
        'distance': 50,
        'wlen': 1000
    }
    INTERNAL_LINES_HOUGHLINES_THRESHOLD = 75
    EDGE_LINES_HOUGHLINES_THRESHOLD = 75

    HOMO_EDGE_DETECT = True
    HOMO_CANNY_THRESHOLD = (40, 60)
    HOMO_EDGE_HOUGHLINES_THRESHOLD = 300

    MAP_ENEMY_GENRE_DETECTION_SCALING = {
        'DD': 0.8,
        'CL': 0.8,
        'CA': 0.8,
        'CV': 0.8,
        'BB': 0.8,
    }
    MAP_SWIPE_PREDICT = False

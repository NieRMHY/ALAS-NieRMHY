"""手动配置定义模块。

定义非自动生成的硬编码配置项，包括：
- 服务器信息和资源文件路径
- UI 按钮的服务器特定偏移量
- 任务调度的默认优先级逻辑
- 各功能模块的配置属性访问器

此文件中的配置项需要手动维护，不随 config_updater.py 自动更新。
配置属性通过 `@property` 装饰器暴露，供 AzurLaneConfig 通过多重继承访问。
"""

import typing as t
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typing import Any

# 此文件定义了手动配置项。
# 包含了非自动生成的硬编码设置，如资源文件路径、UI 按钮偏移量以及任务调度的默认优先级逻辑。
from module.config.deep import deep_get
from module.config.utils import *
from module.config.task_priority import get_scheduler_tasks, merge_task_priority
import module.config.server as server


class ManualConfig:
    """手动配置基类。

    提供 AzurLaneConfig 中不通过代码生成器创建的配置属性。
    这些属性包括：
    - 服务器标识（SERVER）
    - 任务调度优先级（_DEFAULT_SCHEDULER_PRIORITY）
    - 各功能模块的配置访问器（如 Research_PresetFilter、Fleet_FleetOrder 等）

    通过多重继承被 AzurLaneConfig 组合使用。
    """
    if TYPE_CHECKING:
        def cross_get(self, keys: list[str], default: Any = None) -> Any: ...
        YukikazeTaskManager_TaskPriorityAdjustment: str | None
    @property
    def SERVER(self):
        return server.server

    _DEFAULT_SCHEDULER_PRIORITY = """
    Restart
    > OpsiCrossMonth
    > Commission > Tactical > Research
    > Exercise
    > Dorm > Meowfficer > Guild > Gacha
    > Reward
    > ShopFrequent > EventShop > ShopOnce > Shipyard > Freebies
    > PrivateQuarters
    > OpsiExplore
    > Minigame > Awaken
    > OpsiAshBeacon
    > OpsiDaily > OpsiShop > OpsiVoucher
    > OpsiScheduling
    > OpsiAbyssal > OpsiStronghold > OpsiObscure > OpsiArchive
    > Daily > Hard > OpsiAshBeacon > OpsiAshAssist > OpsiMonthBoss
    > Sos > EventSp > EventA > EventB > EventC > EventD
    > RaidDaily > CoalitionSp > WarArchives > MaritimeEscort
    # Add by MHY: 赛季任务读取排在岛屿生产任务之前。它只读「开发季-开发计划」页面，
    # 结果决定已提交的物品要不要继续生产；原先未登记默认优先级，被追加到全表最后
    # （78/78），长期被其它任务插队饿死——真机表现为 NextRun 已过期却始终不执行。
    > IslandSeasonPlan
    > IslandJuuEatery > IslandJuuCoffee > IslandGrill > IslandTeahouse > IslandRestaurant
    > IslandFarm > IslandRancher > IslandMineForest > IslandDailyGather > IslandManufacture
    > IslandAirDrop > IslandBusiness
    > Event > Event2 > Event3 > Raid > Hospital > HospitalEvent > Coalition > CoalitionScuttle > RaidAffection > Main > Main2 > Main3
    > OpsiMeowfficerFarming
    > GemsFarming
    > Ambush11
    > OpsiHazard1Leveling
    > ThreeOilLowCost
    > OperationHandover
    """

    @staticmethod
    def _normalize_scheduler_priority(value: str | None) -> str:
        """规范化用户定义的调度优先级文本。

        - 去除每行的行内 `# ...` 注释。
        - 过滤空行。
        - 保留以换行符连接的原始任务表达式。
        - 去除末尾的 `>` 防止意外拼接任务标识符。

        Args:
            value: 原始调度优先级字符串。

        Returns:
            规范化后的调度优先级字符串。
        """
        if not value:
            return ""

        cleaned_lines = []
        for raw_line in str(value).splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            cleaned_lines.append(line)

        cleaned = "\n".join(cleaned_lines).strip()
        while cleaned.endswith(">"):
            cleaned = cleaned[:-1].rstrip()
        return cleaned

    @property
    def SCHEDULER_PRIORITY(self) -> str:
        """获取并计算合并后的任务调度优先级字符串。

        Returns:
            按优先级排序的任务序列字符串。
        """
        if TYPE_CHECKING:
            from module.config.config import AzurLaneConfig
            self = t.cast(AzurLaneConfig, self)
        task_adj = None
        # 使用 getattr 适配类型检查器未感知的完整继承树
        cross_get = getattr(self, "cross_get", None)
        if cross_get:
            try:
                task_adj = cross_get(keys=["YukikazeTaskManager", "TaskPriorityAdjustment"], default=None)
            except Exception:
                task_adj = None

        if not task_adj:
            task_adj = getattr(self, "YukikazeTaskManager_TaskPriorityAdjustment", None)

        try:
            args = read_file(filepath_args())
            default_priority = deep_get(
                args,
                "General.YukikazeTaskManager.TaskPriorityAdjustment.value",
                getattr(self, "_DEFAULT_SCHEDULER_PRIORITY", ""),
            )
            available_tasks = get_scheduler_tasks(args)
        except Exception:
            default_priority = getattr(self, "_DEFAULT_SCHEDULER_PRIORITY", "")
            available_tasks = None

        return merge_task_priority(task_adj, default_priority, available_tasks)

    """
    module.assets
    """
    ASSETS_FOLDER = './assets'
    ASSETS_MODULE = './module'
    ASSETS_RESOLUTION = (1280, 720)

    """
    module.base
    """
    BUTTON_OFFSET = 30
    WAIT_BEFORE_SAVING_SCREEN_SHOT = 1

    """
    module.campaign
    """
    MAP_CLEAR_ALL_THIS_TIME = False
    # 来自 chapter_template.lua
    STAR_REQUIRE_1 = 1
    STAR_REQUIRE_2 = 2
    STAR_REQUIRE_3 = 3
    # normal: 大多数关卡使用
    # blue: 蝶海一梦（信浓活动，event_20200917_cn）中的蓝色关卡图标
    # half: 假日航线（死或生联动，event_20201126_cn）中 '%' 的左半部分
    #       死或生联动关卡图标较小，'%' 的右半部分超出原始区域
    STAGE_ENTRANCE = ['normal']  # normal, blue, half
    # 设置 stage='TH' 且 run_count=100 时，循环执行 TH1~TH5
    STAGE_LOOP_ALIAS = {
        ('event_20221124_cn', 'TH'): 'TH1 > TH2 > TH3 > TH4 > TH5',
        ('event_20250724_cn', 'TS'): 'TS1 > TS2 > TS3 > TS4 > TS5',
    }

    """
    module.combat.level
    """
    LV_TRIGGERED = False
    LV32_TRIGGERED = False
    STOP_IF_REACH_LV32 = False

    """
    module.device
    """
    DEVICE_OVER_HTTP = False
    FORWARD_PORT_RANGE = (20000, 21000)
    REVERSE_SERVER_PORT = 7903

    ASCREENCAP_FILEPATH_LOCAL = './bin/ascreencap'
    ASCREENCAP_FILEPATH_REMOTE = '/data/local/tmp/ascreencap'

    # 'DroidCast', 'DroidCast_raw'
    DROIDCAST_VERSION = 'DroidCast'
    DROIDCAST_FILEPATH_LOCAL = './bin/DroidCast/DroidCast_raw-release-1.1.apk'
    DROIDCAST_FILEPATH_REMOTE = '/data/local/tmp/DroidCast_raw.apk'

    MINITOUCH_FILEPATH_REMOTE = '/data/local/tmp/minitouch'

    HERMIT_FILEPATH_LOCAL = './bin/hermit/hermit.apk'

    SCRCPY_FILEPATH_LOCAL = './bin/scrcpy/scrcpy-server-v1.20.jar'
    SCRCPY_FILEPATH_REMOTE = '/data/local/tmp/scrcpy-server-v1.20.jar'

    MAATOUCH_FILEPATH_LOCAL = './bin/MaaTouch/maatouchsync'
    MAATOUCH_FILEPATH_REMOTE = '/data/local/tmp/maatouchsync'

    """
    module.campaign.gems_farming
    """
    COMMON_CV_FILTER = 'bogue > ranger > langley > hermes'
    COMMON_DD_FILTER =  'z20 > z21 > aulick > foote > cassin > downes'
    GEMS_EMOTION_TRIGGERED = False

    """
    module.handler
    """
    STORY_OPTION = 0
    # 临时修复碧蓝航线客户端剧情跳过问题的补丁
    # 2023.09.07 碧蓝航线跳过剧情时会跳过剧情选项
    # 导致必须选择的选项也会被跳过，例如深渊强制确认、塞壬扫描装置和记录装置交互
    # 在上述情况下禁止点击跳过（SKIP）
    STORY_ALLOW_SKIP = True

    """
    module.map.fleet
    """
    MAP_HAS_MODE_SWITCH = False  # event_20240725_cn 地图准备阶段支持模式切换
    # 20240725 至 20241219 活动引入的新章节切换
    MAP_CHAPTER_SWITCH_20241219 = False
    MAP_CHAPTER_SWITCH_20241219_SP = False
    MAP_CHAPTER_SWITCH_20241219_SPEX = False
    MAP_CHAPTER_SWITCH_20260326 = False
    # 自 event_20241219_cn 起 B 篇章在活动开始时解锁，AB 篇章连续
    STAGE_INCREASE_AB = True
    # 向 STAGE_INCREASE 插入自定义关卡
    STAGE_INCREASE_CUSTOM = ''
    MAP_HAS_CLEAR_PERCENTAGE = True
    MAP_CLEAR_PERCENTAGE_SHORT = False
    MAP_HAS_WALK_SPEEDUP = False
    MAP_HAS_AMBUSH = True
    MAP_HAS_FLEET_STEP = False
    MAP_HAS_MOVABLE_ENEMY = False
    MAP_HAS_MOVABLE_NORMAL_ENEMY = False
    MAP_HAS_SIREN = False
    MAP_HAS_DYNAMIC_RED_BORDER = False
    MAP_HAS_MAP_STORY = False  # event_20200521_cn（穹顶下的圣咏曲）增加战后剧情
    MAP_HAS_WALL = False  # event_20200521_cn（穹顶下的圣咏曲）在格子间增加障碍墙
    MAP_HAS_PT_BONUS = False  # 追击成功获得 100% PT 加成，否则 50%，撤退 0%
    MAP_IS_ONE_TIME_STAGE = False
    MAP_HAS_PORTAL = False
    MAP_HAS_LAND_BASED = False
    MAP_HAS_MAZE = False  # event_20210422_cn 增加迷宫，迷宫墙每 3 回合移动一次
    MAP_HAS_FORTRESS = False  # event_2021917_cn 清除要塞以解除通往 Boss 的路障
    MAP_HAS_MISSILE_ATTACK = False  # event_202111229_cn 导弹袭击覆盖塞壬特征区域
    MAP_HAS_BOUNCING_ENEMY = False  # event_20220224_cn 敌人在固定路线上往返移动
    MAP_HAS_DECOY_ENEMY = False  # event_20220428 地图诱饵敌人，舰队到达后消失
    MAP_HAS_SUBMARINE_SUPPORT = False # 主线 16-1 和 16-2 拥有潜艇支援舰队
    MAP_FOCUS_ENEMY_AFTER_BATTLE = False  # 大世界战后锁定敌人
    MAP_ENEMY_TEMPLATE = ['Light', 'Main', 'Carrier', 'Treasure']
    MAP_SIREN_TEMPLATE = ['DD', 'CL', 'CA', 'BB', 'CV']
    MAP_ENEMY_GENRE_DETECTION_SCALING = {}  # 键: str 模板名，值: float 缩放因子
    MAP_ENEMY_GENRE_SIMILARITY = 0.85
    MAP_SIREN_MOVE_WAIT = 1.5  # 敌人移动耗时约 1.2 ~ 1.5 秒
    MAP_SIREN_COUNT = 0
    MAP_SIREN_HAS_BOSS_ICON = False  # 右下角带小型 Boss 图标的无名塞壬
    MAP_SIREN_HAS_BOSS_ICON_SMALL = False
    MAP_HAS_MYSTERY = True
    MAP_MYSTERY_MAP_CLICK = True
    MAP_MYSTERY_HAS_CARRIER = False
    MAP_GRID_CENTER_TOLERANCE = 0.2
    # 参见 map_control_init()
    MAP_FLEET_REVERSE_WAIT_INFO_BAR = False

    MOVABLE_ENEMY_FLEET_STEP = 2
    MOVABLE_ENEMY_TURN = (2,)
    MOVABLE_NORMAL_ENEMY_TURN = (1,)

    POOR_MAP_DATA = False
    # 将地图网格距离转换为滑动距离
    # 通常范围在 1/0.62 到 1/0.61 之间
    # 不同地图数值可能不同
    # 2023.05.25 前
    # MAP_SWIPE_MULTIPLY = 1.626
    # MAP_SWIPE_MULTIPLY_MINITOUCH = 1.572
    # MAP_SWIPE_MULTIPLY_MINITOUCH = 1.525
    # 2023.05.25, 适配 14-1 滑动
    # MAP_SWIPE_MULTIPLY = (1.006, 1.025)
    # MAP_SWIPE_MULTIPLY_MINITOUCH = (0.973, 0.991)
    # MAP_SWIPE_MULTIPLY_MAATOUCH = (0.944, 0.961)
    # 2023.05.25, 滑动转换到 7-2 基准
    MAP_SWIPE_MULTIPLY = (1.064, 1.084)
    MAP_SWIPE_MULTIPLY_MINITOUCH = (1.029, 1.048)
    MAP_SWIPE_MULTIPLY_MAATOUCH = (0.999, 1.017)
    # 地图网格滑动距离低于此值将被丢弃，因为过短的滑动在游戏中会被判定为点击
    MAP_SWIPE_DROP = 0.25
    # 模拟器卡顿时滑动可能在中途停止，预测实际滑动距离以校正相机视角
    MAP_SWIPE_PREDICT = True
    MAP_SWIPE_PREDICT_WITH_CURRENT_FLEET = True
    MAP_SWIPE_PREDICT_WITH_SEA_GRIDS = False
    # ensure_edge_insight 中需要确保视野的角落
    # 取值可为 'upper-left', 'upper-right', 'bottom-left', 'bottom-right', 或 'upper', 'bottom', 'left', 'right'
    # 缺失的轴将随机选择，'' 表示完全随机
    MAP_ENSURE_EDGE_INSIGHT_CORNER = ''
    # 使用当前舰队上的绿色箭头判断舰队是否到达指定网格
    MAP_WALK_USE_CURRENT_FLEET = False
    # 优化移动路径以减少遭遇伏击
    MAP_WALK_TURNING_OPTIMIZE = True
    # 优化滑动路径以减少滑动误触发点击
    MAP_SWIPE_OPTIMIZE = True
    # Boss 出现后重新对焦滑动，避免相机位于边缘时的地图检测错误
    MAP_BOSS_APPEAR_REFOCUS_SWIPE = (0, 0)

    """
    module.map_detection
    """
    SCREEN_SIZE = (1280, 720)
    DETECTING_AREA = (123, 55, 1280, 720)
    SCREEN_CENTER = (SCREEN_SIZE[0] / 2, SCREEN_SIZE[1] / 2)
    DETECTION_BACKEND = 'homography'
    # event_20200723_cn B3D3 中网格宽度为 1.2 倍，网格上的图片大小保持不变
    GRID_IMAGE_A_MULTIPLY = 1.0

    """
    module.map_detection.homography
    """
    HOMO_TILE = (140, 140)
    HOMO_CENTER_OFFSET = (48, 48)
    # [左上, 右上, 左下, 右下]
    HOMO_CORNER_OFFSET_LIST = [(-42, -42), (68, -42), (-42, 69), (69, 69)]

    HOMO_CANNY_THRESHOLD = (100, 150)
    HOMO_CENTER_GOOD_THRESHOLD = 0.9
    HOMO_CENTER_THRESHOLD = 0.8
    HOMO_CORNER_THRESHOLD = 0.8
    HOMO_RECTANGLE_THRESHOLD = 10

    HOMO_EDGE_DETECT = True
    HOMO_EDGE_HOUGHLINES_THRESHOLD = 180
    HOMO_EDGE_COLOR_RANGE = (0, 33)
    # ((x, y), [左上, 右上, 左下, 右下])
    HOMO_STORAGE = None

    """
    module.map_detection.perspective
    """
    # scipy.signal.find_peaks 参数
    # https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html
    INTERNAL_LINES_FIND_PEAKS_PARAMETERS = {
        'height': (150, 255 - 33),
        'width': (0.9, 10),
        'prominence': 10,
        'distance': 35,
    }
    EDGE_LINES_FIND_PEAKS_PARAMETERS = {
        'height': (255 - 33, 255),
        'prominence': 10,
        'distance': 50,
        # 'width': (0, 7),
        'wlen': 1000
    }
    # cv2.HoughLines 参数
    INTERNAL_LINES_HOUGHLINES_THRESHOLD = 75
    EDGE_LINES_HOUGHLINES_THRESHOLD = 75
    # 直线预清理参数
    HORIZONTAL_LINES_THETA_THRESHOLD = 0.005
    VERTICAL_LINES_THETA_THRESHOLD = 18
    TRUST_EDGE_LINES = False  # True 表示用边缘线裁剪内部线，False 表示用内部线裁剪边缘线
    TRUST_EDGE_LINES_THRESHOLD = 5
    # 透视计算参数
    VANISH_POINT_RANGE = ((540, 740), (-3000, -1000))
    DISTANCE_POINT_X_RANGE = ((-3200, -1600),)
    # 直线清理参数
    COINCIDENT_POINT_ENCOURAGE_DISTANCE = 3
    ERROR_LINES_TOLERANCE = (-10, 10)
    MID_DIFF_RANGE_H = (129 - 3, 129 + 3)
    MID_DIFF_RANGE_V = (129 - 3, 129 + 3)

    """
    module.os
    """
    # 探索整张地图的区域 ID 顺序
    # 从 0 (纽约港) 开始，左下方，顺时针方向遍历
    # 侵蚀 1 与 侵蚀 2
    # 侵蚀 3
    # 侵蚀 4
    # 侵蚀 5
    # 侵蚀 6
    # 核心区 侵蚀 5 与 侵蚀 6
    OS_EXPLORE_FILTER = """
    44 > 24 > 22 > 31 > 21 > 23
    > 83 > 43 > 81 > 84 > 92 > 93
    > 131 > 134 > 132 > 122 > 112

    > 33 > 34 > 32 > 25
    > 41 > 105 > 95 > 94
    > 141 > 143 > 133 > 135 > 111 > 113 > 114 > 125 > 123
    > 65 > 62 > 66

    > 14 > 42
    > 85 > 82 > 91 > 104 > 103
    > 142
    > 61 > 52 > 51 > 53 > 54 > 63 > 64

    > 13 > 12
    > 101 > 102
    > 144 > 124
    > 71 > 73

    > 11 > 106 > 121 > 72

    > 151 > 152 > 159 > 158
    > 153 > 157 > 156 > 155
    """
    OS_ACTION_POINT_BOX_USE = True
    OS_ACTION_POINT_PRESERVE = 0
    OS_NORMAL_YELLOW_COINS_PRESERVE = 35000
    OS_NORMAL_PURPLE_COINS_PRESERVE = 100
    OS_MISSION_COMPLETE = False

    """
    module.os.globe_detection
    """
    OS_GLOBE_HOMO_STORAGE = ((4, 3), ((445, 180), (879, 180), (376, 497), (963, 497)))
    OS_GLOBE_DETECTING_AREA = (0, 0, 1280, 720)
    OS_GLOBE_IMAGE_PAD = 700
    OS_GLOBE_IMAGE_RESIZE = 0.5
    OS_GLOBE_FIND_PEAKS_PARAMETERS = {
        'height': 100,
        # 'width': (0.9, 5),
        'prominence': 20,
        'distance': 35,
        'wlen': 500,
    }
    OS_LOCAL_FIND_PEAKS_PARAMETERS = {
        'height': 50,
        # 'width': (0.9, 5),
        'prominence': 20,
        'distance': 35,
        'wlen': 500,
    }
    # minitouch 下屏幕滑动 (200, 200) 对应地图滑动 (382, 442)
    OS_GLOBE_SWIPE_MULTIPLY = (1.91, 2.21)

    # 塞壬装置处理方法
    # 'never', 'use_until_destroyed'
    OS_SIREN_DEVICE_USAGE = 'never'

    """
    module.retire
    """
    DOCK_FULL_TRIGGERED = False
    GET_SHIP_TRIGGERED = False
    COMMON_CV_THRESHOLD = 0.9

    """
    module.shop
    """
    # 开发调试用途：自动提取新商品模板
    SHOP_EXTRACT_TEMPLATE = False

    """
    module.shop_event
    """
    EVENT_SHOP_IGNORE_DEADLINE = False

    """
    module.war_archives
    """
    USE_DATA_KEY = False

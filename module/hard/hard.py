"""困难模式战役执行模块。

自动执行碧蓝航线的困难模式关卡。困难模式与普通模式共享同一张地图，
但使用独立的战役入口和额外的限制条件（如每日出击次数、舰队锁定等）。
通过 OCR 识别剩余出击次数，循环执行直到用尽。

配置路径: Hard.HardStage (关卡选择), Hard.HardFleet (舰队选择)
"""

import importlib

from campaign.campaign_hard.campaign_hard import Campaign
from module.campaign.run import CampaignRun
from module.handler.fast_forward import to_map_file_name
from module.hard.assets import *
from module.logger import logger
from module.ocr.ocr import Digit

OCR_HARD_REMAIN = Digit(OCR_HARD_REMAIN, letter=(123, 227, 66), threshold=128, alphabet='0123')

# Add by MHY, 图纸类型到关卡编号的映射
_BLUEPRINT_STAGE_MAP = {
    'DD': '1',   # 驱逐 → X-1
    'CL': '2',   # 巡洋 → X-2
    'BB': '3',   # 战列 → X-3
    'CV': '4',   # 航母 → X-4
}


class CampaignHard(CampaignRun):
    """困难模式战役执行器。

    继承自 CampaignRun，负责执行困难模式关卡。从普通模式战役加载地图数据，
    强制启用舰队锁定和自动搜索，通过 OCR 识别每日剩余出击次数并循环执行。

    Attributes:
        equipment_has_take_on: 装备是否已穿戴（当前未使用）。
        campaign: 战役执行实例，由 CampaignRun 提供。
    """

    equipment_has_take_on = False
    campaign: Campaign

    def run(self):
        logger.hr('困难战役', level=1)
        # Modify by MHY: 支持均衡模式开关，开启则跨天轮转刷图纸，关闭走原有固定单关逻辑
        if self.config.Hard_HardNewMode:
            self._run_balanced_mode()
        else:
            self._run_fixed_mode()

    def _run_fixed_mode(self):
        name = to_map_file_name(self.config.Hard_HardStage)
        self.config.override(
            Campaign_Mode='hard',
            Campaign_UseFleetLock=True,
            Campaign_UseAutoSearch=True,
            Fleet_FleetOrder='fleet1_all_fleet2_standby' if self.config.Hard_HardFleet == 1 else 'fleet1_standby_fleet2_all',
            Emotion_Mode='nothing',  # 不计算也不忽略
        )
        # 装备穿戴
        # campaign/campaign_hard/campaign_hard.py Campaign.fleet_preparation()

        # 初始化
        self.load_campaign(name='campaign_hard', folder='campaign_hard')  # 加载战役文件
        module = importlib.import_module('.' + name, 'campaign.campaign_main')  # 从普通模式加载地图
        self.campaign.MAP = module.MAP

        # UI 确认
        self.device.screenshot()
        self.campaign.device.image = self.device.image
        self.campaign.ensure_campaign_ui(
            name=self.config.Hard_HardStage,
            mode='hard'
        )

        # 执行
        remain = OCR_HARD_REMAIN.ocr(self.device.image)
        logger.attr('剩余次数', remain)
        for n in range(remain):
            self.campaign.run()

        self.campaign.ensure_auto_search_exit()
        # self.campaign.equipment_take_off_when_finished()

        # 调度器
        self.config.task_delay(server_update=True)
        self.config.task_call('Reward', force_call=False)

    # Add by MHY, 困难图均衡模式: 根据勾选的图纸类型在多个关卡间轮转
    def _run_balanced_mode(self):
        chapter = self.config.Hard_HardNewChapter
        # 构建选中的关卡列表
        stages = []
        for bp_type in ['DD', 'CL', 'BB', 'CV']:
            if getattr(self.config, f'Hard_HardNew{bp_type}'):
                stage_num = _BLUEPRINT_STAGE_MAP[bp_type]
                stages.append(f'{chapter}-{stage_num}')

        if not stages:
            logger.warning('均衡模式未勾选任何图纸类型，回退到 {chapter}-1'.format(chapter=chapter))
            stages = [f'{chapter}-1']

        logger.attr('均衡关卡列表', stages)

        self.config.override(
            Campaign_Mode='hard',
            Campaign_UseFleetLock=True,
            Campaign_UseAutoSearch=True,
            Fleet_FleetOrder='fleet1_all_fleet2_standby' if self.config.Hard_HardFleet == 1 else 'fleet1_standby_fleet2_all',
            Emotion_Mode='nothing',
        )

        # 加载战役模块
        self.load_campaign(name='campaign_hard', folder='campaign_hard')

        cursor = self.config.Hard_HardNewCursor
        first_stage = stages[cursor % len(stages)]

        # 先导航到第一个关卡再OCR剩余次数
        map_name = to_map_file_name(first_stage)
        module = importlib.import_module('.' + map_name, 'campaign.campaign_main')
        self.campaign.MAP = module.MAP
        self.device.screenshot()
        self.campaign.device.image = self.device.image
        self.campaign.ensure_campaign_ui(name=first_stage, mode='hard')
        remain = OCR_HARD_REMAIN.ocr(self.device.image)
        logger.attr('剩余次数', remain)

        if remain == 0:
            self.campaign.ensure_auto_search_exit()
            self.config.task_delay(server_update=True)
            self.config.task_call('Reward', force_call=False)
            return

        # 第一天关已导航好，直接打
        self.campaign.run()
        cursor += 1

        for i in range(remain - 1):
            stage = stages[cursor % len(stages)]
            logger.attr('当前关卡', stage)

            map_name = to_map_file_name(stage)
            module = importlib.import_module('.' + map_name, 'campaign.campaign_main')
            self.campaign.MAP = module.MAP

            self.device.screenshot()
            self.campaign.device.image = self.device.image
            self.campaign.ensure_campaign_ui(name=stage, mode='hard')

            self.campaign.run()
            cursor += 1

        # 持久化指针
        self.config.Hard_HardNewCursor = cursor

        self.campaign.ensure_auto_search_exit()

        self.config.task_delay(server_update=True)
        self.config.task_call('Reward', force_call=False)

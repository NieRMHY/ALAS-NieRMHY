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
    equipment_has_take_on = False
    campaign: Campaign

    def run(self):
        logger.hr('Campaign hard', level=1)
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
            Emotion_Mode='nothing',  # Dont calculate and dont ignore
        )
        # Equipment take on
        # campaign/campaign_hard/campaign_hard.py Campaign.fleet_preparation()

        # Initial
        self.load_campaign(name='campaign_hard', folder='campaign_hard')  # Load campaign file
        module = importlib.import_module('.' + name, 'campaign.campaign_main')  # Load map from normal mode.
        self.campaign.MAP = module.MAP

        # UI ensure
        self.device.screenshot()
        self.campaign.device.image = self.device.image
        self.campaign.ensure_campaign_ui(
            name=self.config.Hard_HardStage,
            mode='hard'
        )

        # Run
        remain = OCR_HARD_REMAIN.ocr(self.device.image)
        logger.attr('Remain', remain)
        for n in range(remain):
            self.campaign.run()

        self.campaign.ensure_auto_search_exit()
        # self.campaign.equipment_take_off_when_finished()

        # Scheduler
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
            logger.warning('No stage selected in balanced mode, fallback to 14-1')
            stages = [f'{chapter}-1']

        logger.attr('BalancedStages', stages)

        self.config.override(
            Campaign_Mode='hard',
            Campaign_UseFleetLock=True,
            Campaign_UseAutoSearch=True,
            Fleet_FleetOrder='fleet1_all_fleet2_standby' if self.config.Hard_HardFleet == 1 else 'fleet1_standby_fleet2_all',
            Emotion_Mode='nothing',
        )

        # 加载战役模块
        self.load_campaign(name='campaign_hard', folder='campaign_hard')

        # 获取剩余次数
        self.device.screenshot()
        remain = OCR_HARD_REMAIN.ocr(self.device.image)
        logger.attr('Remain', remain)

        cursor = self.config.Hard_HardNewCursor
        for i in range(remain):
            stage = stages[cursor % len(stages)]
            logger.attr('CurrentStage', stage)

            # 加载当前关卡的地图数据
            map_name = to_map_file_name(stage)
            module = importlib.import_module('.' + map_name, 'campaign.campaign_main')
            self.campaign.MAP = module.MAP

            # 导航到当前关卡
            self.device.screenshot()
            self.campaign.device.image = self.device.image
            self.campaign.ensure_campaign_ui(name=stage, mode='hard')

            # 执行战斗
            self.campaign.run()
            cursor += 1

        # 持久化指针
        self.config.Hard_HardNewCursor = cursor

        self.campaign.ensure_auto_search_exit()

        self.config.task_delay(server_update=True)
        self.config.task_call('Reward', force_call=False)

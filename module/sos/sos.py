"""SOS 深海搜索模块。

自动执行碧蓝航线的 SOS 深海搜索任务。SOS 任务通过信号列表进入，
每个章节（3~10 章）有独立的搜索信号。通过 OCR 识别剩余信号数量，
循环选择目标章节并执行战役。

注意：CN/EN/JP 服已不再有 SOS 地图，任务会自动禁用。
仅 TW 服仍保留此功能。

不同服务器的 UI 布局存在差异（滚动条颜色、章节 OCR 区域等），
通过 @Config.when 装饰器实现服务器特定的适配。

配置路径: Sos.Chapter (目标章节)
"""

from campaign.campaign_sos.campaign_base import CampaignBase
from module.base.decorator import Config, cached_property
from module.base.utils import area_pad, random_rectangle_vector
from module.campaign.run import CampaignRun
from module.logger import logger
from module.ocr.ocr import Digit
from module.sos.assets import *
from module.ui.assets import CAMPAIGN_CHECK
from module.ui.page import page_campaign
from module.ui.scroll import Scroll

OCR_SOS_SIGNAL = Digit(OCR_SIGNAL, letter=(255, 255, 255), threshold=128, name='OCR_SOS_SIGNAL')


class CampaignSos(CampaignRun, CampaignBase):
    """SOS 深海搜索战役执行器。

    继承自 CampaignRun（战役运行）和 CampaignBase（SOS 战役基础），
    负责 SOS 任务的完整自动化流程：
    1. 进入战役页面，打开信号列表
    2. 通过 OCR 识别剩余信号数量
    3. 根据配置选择目标章节（3~10 章）
    4. 在信号列表中定位目标章节（不同服务器使用滚动或滑动方式）
    5. 执行 SOS 战役
    6. 循环直到所有信号用尽

    服务器差异：
    - EN 服无滚动条，通过拖拽滑动信号列表
    - TW 服滚动条颜色不同（金色 vs 灰色）
    - 章节 OCR 的裁剪区域和颜色参数各服务器不同
    """

    @cached_property
    @Config.when(SERVER='en')
    def _sos_chapter_crop(self):
        return [-330, 8, -285, 45]

    @cached_property
    @Config.when(SERVER='jp')
    def _sos_chapter_crop(self):
        return [-430, 8, -382, 45]

    @cached_property
    @Config.when(SERVER='tw')
    def _sos_chapter_crop(self):
        return [-400, 8, -370, 45]

    @cached_property
    @Config.when(SERVER=None)
    def _sos_chapter_crop(self):
        return [-403, 8, -381, 35]

    @cached_property
    @Config.when(SERVER='tw')
    def _sos_scroll(self):
        return Scroll(SOS_SCROLL_AREA, color=(247, 210, 66), name='SOS_SCROLL')

    @cached_property
    @Config.when(SERVER=None)
    def _sos_scroll(self):
        return Scroll(SOS_SCROLL_AREA, color=(164, 173, 189), name='SOS_SCROLL')

    @cached_property
    @Config.when(SERVER='tw')
    def _sos_chapter_ocr(self):
        return Digit([], letter=[173, 247, 74], threshold=180, name='OCR_SOS_CHAPTER')

    @cached_property
    @Config.when(SERVER=None)
    def _sos_chapter_ocr(self):
        return Digit([], letter=[132, 230, 115], threshold=136, name='OCR_SOS_CHAPTER')

    def _find_target_chapter(self, chapter):
        """寻找目标章节的信号搜索或前往按钮。

        Args:
            chapter (int): SOS 目标章节（3~10）。

        Returns:
            Button | None: 找到的目标章节入口按钮，未找到返回 None。
        """
        signal_search_buttons = TEMPLATE_SIGNAL_SEARCH.match_multi(self.device.image)
        sos_goto_buttons = TEMPLATE_SIGNAL_GOTO.match_multi(self.device.image)
        sos_confirm_buttons = TEMPLATE_SIGNAL_CONFIRM.match_multi(self.device.image)
        all_buttons = sos_goto_buttons + signal_search_buttons + sos_confirm_buttons
        if not len(all_buttons):
            logger.info('未找到SOS章节')
            return None

        chapter_buttons = [button.crop(self._sos_chapter_crop) for button in all_buttons]
        self._sos_chapter_ocr.buttons = chapter_buttons
        chapter_list = self._sos_chapter_ocr.ocr(self.device.image)
        if not isinstance(chapter_list, list):
            chapter_list = [chapter_list]
        if chapter in chapter_list:
            logger.info('找到目标SOS章节')
            return all_buttons[chapter_list.index(chapter)]
        else:
            logger.info('未找到目标SOS章节')
            return None

    @Config.when(SERVER='en')
    def _sos_signal_select(self, chapter):
        """选择指定章节的 SOS 信号（EN 服滑动实现）。

        EN 服没有滚动条，通过拖拽手势上下滑动信号列表。

        Args:
            chapter (int): 目标章节（3 到 10）。

        Returns:
            bool: 是否成功选中目标章节。

        Pages:
            in: page_campaign
            out: page_campaign，位于目标章节
        """
        logger.hr(f'[SOS] 选择第 {chapter} 章信号 ')
        self.ui_click(SIGNAL_SEARCH_ENTER, appear_button=CAMPAIGN_CHECK, check_button=SIGNAL_LIST_CHECK,
                      skip_first_screenshot=True)

        detection_area = (620, 285, 720, 485)
        for _ in range(0, 5):
            target_button = self._find_target_chapter(chapter)
            if target_button is not None:
                self._sos_signal_confirm(entrance=target_button)
                return True

            p1, p2 = random_rectangle_vector(
                (0, -200), box=detection_area, random_range=(-50, -50, 50, 50), padding=20)
            self.device.drag(p1, p2, segments=2, shake=(0, 25), point_random=(0, 0, 0, 0), shake_random=(0, -5, 0, 5))
            self.device.sleep((0.6, 1))
            self.device.screenshot()
        return False

    @Config.when(SERVER=None)
    def _sos_signal_select(self, chapter):
        """选择指定章节的 SOS 信号（滚动条实现）。

        Args:
            chapter (int): 目标章节（3 到 10）。

        Returns:
            bool: 是否成功选中目标章节。

        Pages:
            in: page_campaign
            out: page_campaign，位于目标章节
        """
        logger.hr(f'[SOS] 选择第 {chapter} 章信号 ')
        self.ui_click(SIGNAL_SEARCH_ENTER, appear_button=CAMPAIGN_CHECK, check_button=SIGNAL_LIST_CHECK,
                      skip_first_screenshot=True)
        if chapter in [3, 4, 5]:
            positions = [0.0, 0.5, 1.0]
        elif chapter in [6, 7]:
            positions = [0.5, 1.0, 0.0]
        elif chapter in [8, 9, 10]:
            positions = [1.0, 0.5, 0.0]
        else:
            logger.warning(f'[SOS] 未知的SOS章节: {chapter}')
            positions = [0.0, 0.5, 1.0]

        for scroll_position in positions:
            if self._sos_scroll.appear(main=self):
                self._sos_scroll.set(scroll_position, main=self, distance_check=False)
            else:
                logger.info('SOS信号滚动条未出现，跳过设置滚动位置')
            target_button = self._find_target_chapter(chapter)
            if target_button is not None:
                self._sos_signal_confirm(entrance=target_button)
                return True
        return False

    def _sos_signal_confirm(self, entrance, skip_first_screenshot=True):
        """搜索 SOS 信号并前往目标章节。

        Args:
            entrance (Button): 入口按钮。
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: SIGNAL_SEARCH
            out: page_campaign
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(SIGNAL_LIST_CHECK, offset=(20, 20), interval=2):
                image = self.image_crop(area_pad(entrance.area, pad=-30), copy=False)
                if TEMPLATE_SIGNAL_SEARCH.match(image):
                    self.device.click(entrance)
                if TEMPLATE_SIGNAL_GOTO.match(image):
                    self.device.click(entrance)
                if TEMPLATE_SIGNAL_CONFIRM.match(image):
                    self.device.click(entrance)

            # 结束
            if self.appear(CAMPAIGN_CHECK, offset=(20, 20)):
                break

    def run(self, name=None, folder='campaign_sos', mode='normal', total=1):
        """运行 SOS 任务主循环。

        Args:
            name (str, optional): 关卡名称，SOS 关卡动态生成，默认为 None。
            folder (str): 关卡资源目录，默认为 'campaign_sos'。
            mode (str): 战斗模式，SOS 必须为 'normal'。
            total (int): 运行总次数，SOS 关卡仅可通关一次，默认为 1。

        Pages:
            in: 任意页面
            out: page_campaign
        """
        if self.config.SERVER in ['cn', 'en', 'jp']:
            logger.warning('碧蓝航线不再有SOS地图，禁用任务')
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        logger.hr('战役SOS', level=1)
        self.ui_ensure(page_campaign)

        while 1:
            # End
            remain = OCR_SOS_SIGNAL.ocr(self.device.image)
            logger.attr('SOS信号', remain)
            if remain <= 0:
                logger.info(f'所有SOS信号已清除')
                break

            # Run
            if self._sos_signal_select(self.config.Sos_Chapter):
                name = f'campaign_{self.config.Sos_Chapter}_5'
                self.config.override(Campaign_Name=name)
                super().run(name, folder=folder, mode=mode, total=total)
                if self.run_count > 0:
                    continue
                else:
                    self.config.task_stop()
            else:
                self.ui_click(SIGNAL_SEARCH_CLOSE, appear_button=SIGNAL_LIST_CHECK, check_button=CAMPAIGN_CHECK,
                              skip_first_screenshot=True)
                logger.warning(f'清除SOS信号失败，无法定位章节 {self.config.Sos_Chapter}')
                break

        # Scheduler
        self.config.task_delay(server_update=True)

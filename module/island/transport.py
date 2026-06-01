from datetime import datetime, timedelta
import numpy as np
import re

from cached_property import cached_property

from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.base.utils import area_offset, crop, image_color_count, rgb2gray
from module.island.assets import *
from module.island.ui import IslandUI
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.ocr.ocr import Duration
from module.ui_white.assets import POPUP_CANCEL_WHITE, POPUP_CONFIRM_WHITE


class IslandTransport:
    # 运输委托索引
    index: int
    # 是否成功解析运输委托
    valid: bool
    # 委托是否被锁定
    locked: bool
    # 运输委托持续时间
    duration: timedelta
    # 运输委托状态：finished, running, pending, refreshing, unknown
    status: str
    # 委托是否需要开始
    start: bool
    # 委托是否需要刷新
    refresh: bool

    def __init__(self, main, index, blacklist):
        """
        初始化运输委托对象。

        Args:
            main: 主处理器实例
            index (int): 委托索引
            blacklist (list[Template]): 需要提交物品的黑名单模板列表
        """
        self.index = index
        self.blacklist = blacklist
        self.image = main.device.image
        self.valid = True
        self.locked = False
        self.duration = None
        self.start = True
        self.refresh = False
        self.items = SelectedGrids([])
        self.parse_transport(main)
        if not self.valid:
            self.start = False
        self.create_time = datetime.now()

    def parse_transport(self, main):
        offset = (-20, -20, 20, 20)
        delta = 176
        self.offset = area_offset(offset, (0, delta * self.index))

        # 检查委托是否锁定
        lock_offset = area_offset(offset, (0, delta * (self.index - 1)))
        if self.index >= 1 and main.appear(TRANSPORT_LOCKED, lock_offset):
            self.locked = True
            return

        self.status = self.get_transport_status(main)
        if self.status == 'unknown':
            self.valid = False
            return
        elif self.status == 'pending':
            button = OCR_TRANSPORT_TIME.move((0, self.offset[1] + 20))
            ocr = Duration(button, lang='cnocr', letter=(207, 207, 207), name='OCR_TRANSPORT_TIME')
            self.duration = ocr.ocr(self.image)
            if not self.duration.total_seconds():
                self.valid = False
                return

            # 解析物品信息
            origin_y = 174 + delta * self.index
            grids = ButtonGrid(origin=(481, origin_y), delta=(105, 0), 
                               button_shape=(86, 86), grid_shape=(3, 1), name='ITEMS')
            self.items = SelectedGrids([TransportItem(self.image, button, self.blacklist)
                                        for button in grids.buttons]).select(valid=True)
            self.start = self.items.select(load=True).count == self.items.count
            self.refresh = main.appear(TRANSPORT_REFRESH, offset=self.offset) and \
                           bool(self.items.select(refresh=True).count)

            # 先检测物品以获取刷新信息
            if not main.match_template_color(TRANSPORT_START, offset=self.offset):
                self.start = False
        elif self.status == 'running':
            self.start = False
            button = OCR_TRANSPORT_TIME_REMAIN.move((0, self.offset[1] + 20))
            ocr = Duration(button, name='OCR_TRANSPORT_TIME')
            self.duration = ocr.ocr(self.image)
            if not self.duration.total_seconds():
                self.valid = False
                return
        elif self.status == 'finished':
            self.start = False
        elif self.status == 'refreshing':
            self.start = False
            button = OCR_TRANSPORT_REFRESH.move((0, self.offset[1] + 20))
            ocr = Duration(button, letter=(63, 64, 66), name='OCR_TRANSPORT_REFRESH')
            self.duration = ocr.ocr(self.image)
            if not self.duration.total_seconds():
                self.valid = False
                return

    def get_transport_status(self, main):
        if main.appear(TRANSPORT_STATUS_PENDING, offset=self.offset):
            return 'pending'
        elif main.appear(TRANSPORT_STATUS_RUNNING, offset=self.offset):
            return 'running'
        elif main.appear(TRANSPORT_RECEIVE, offset=self.offset):
            return 'finished'
        elif main.appear(TRANSPORT_REFRESH_CHECK, offset=self.offset):
            return 'refreshing'
        else:
            return 'unknown'

    def convert_to_refreshing(self):
        if self.valid:
            self.status = 'refreshing'
            self.start = False
            self.refresh = False
            self.duration = timedelta(hours=0, minutes=30, seconds=0)
            self.create_time = datetime.now()

    def convert_to_running(self):
        if self.valid:
            self.status = 'running'
            self.start = False
            self.refresh = False
            self.create_time = datetime.now()

    @property
    def finish_time(self):
        if self.valid:
            return (self.create_time + self.duration).replace(microsecond=0)
        else:
            return None

    def __str__(self):
        if not self.valid:
            return f'Index: {self.index} (Invalid)'
        if self.locked:
            return f'Index: {self.index} (Locked)'
        info = {'Index': self.index, 'Status': self.status}
        if self.duration:
            info['Duration'] = self.duration
        info['Start'] = self.start
        info['Refresh'] = self.refresh
        info = ', '.join([f'{k}: {v}' for k, v in info.items()])
        return info


class TransportItem:
    # 物品是否足够提交且不在黑名单中
    load: bool
    # 物品是否在黑名单中
    refresh: bool

    def __init__(self, image, button, blacklist):
        """
        初始化运输物品对象。

        Args:
            image: 截图图像
            button: 物品按钮区域
            blacklist: 黑名单模板列表
        """
        self.image_raw = image
        self.button = button
        self.blacklist = blacklist
        self.image = crop(image, button.area)
        self.valid = self.predict_valid()
        self.refresh = False
        self.load = self.predict_load()

    def predict_valid(self):
        # 灰色物品表示空物品
        mean = np.mean(np.max(self.image, axis=2) > 234)
        # 物品顶部的蓝色条表示已加载
        blue_bar_check = image_color_count(self.image[:10, :, :], color=(90, 201, 255), threshold=221, count=500)
        return mean > 0.3 and not blue_bar_check

    def predict_load(self):
        if not self.valid:
            return False
        self.refresh = self.handle_blacklist_items()
        if self.refresh:
            return False
        if not TEMPLATE_ITEM_SATISFIED.match(rgb2gray(self.image)):
            return False
        return True

    def handle_blacklist_items(self):
        """
        检查当前物品是否为黑名单物品。

        Returns:
            bool: 是否存在黑名单物品
        """
        for template in self.blacklist:
            if template.match(self.image):
                return True
        return False

    def __str__(self):
        if not self.valid:
            return '(Invalid)'
        info = {'Load': self.load, 'Refresh': self.refresh}
        info = ', '.join([f'{k}: {v}' for k, v in info.items()])
        return info


class IslandTransportRun(IslandUI):
    @cached_property
    def blacklist(self):
        blacklist = []
        for k, v in self.config.cross_get(keys='Island.IslandTransport').items():
            if k.startswith('Submit') and not v:
                item = k.split('Submit')[-1]
                item = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', item)
                item = re.sub('([a-z0-9])([A-Z])', r'\1_\2', item)
                blacklist.append(globals()[f'TEMPLATE_{item.upper()}'])
        return blacklist

    def _transport_detect(self):
        """
        从当前截图中检测所有运输委托。

        Returns:
            SelectedGrids: 检测到的委托列表
        """
        logger.hr('Transport Commission detect')
        commission = []
        for index in range(3):
            comm = IslandTransport(main=self, index=index, blacklist=self.blacklist)
            logger.attr(f'Transport Commission', comm)
            for item in comm.items:
                logger.attr(item.button, item)
            commission.append(comm)
        return SelectedGrids(commission)

    def transport_detect(self, trial=1, skip_first_screenshot=True):
        """
        检测所有运输委托，支持重试。

        Args:
            trial (int): 检测到无效委托时的重试次数
            skip_first_screenshot (bool): 是否跳过首次截图

        Returns:
            SelectedGrids: 有效委托列表
        """
        commissions = SelectedGrids([])
        for _ in range(trial):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            commissions = self._transport_detect()
            if not commissions.count:
                logger.warning('No commission detected, retry commission detect')
                continue
            elif commissions.select(valid=False).count:
                logger.warning('Found 1 invalid commission at least, retry commission detect')
                continue
            else:
                return commissions.select(valid=True)

        logger.info('trials of transport commission detect exhausted, stop')
        return commissions.select(valid=True)

    def transport_receive(self):
        """
        领取运输页面上所有已完成的运输委托。

        Returns:
            bool: 是否成功领取
        """
        logger.hr('Island Transport', level=2)
        self.device.click_record_clear()
        self.interval_clear([GET_ITEMS_ISLAND, TRANSPORT_RECEIVE, POPUP_CANCEL_WHITE])
        success = True
        click_timer = Timer(5, count=10).start()
        confirm_timer = Timer(1, count=2).start()
        for _ in self.loop():
            if self.handle_info_bar():
                click_timer.reset()
                confirm_timer.reset()
                continue

            if self.appear_then_click(TRANSPORT_RECEIVE, offset=(-20, -20, 20, 400), interval=2):
                success = False
                click_timer.reset()
                confirm_timer.reset()
                continue

            if self.handle_get_items():
                success = True
                click_timer.reset()
                confirm_timer.reset()
                continue

            if self.handle_popup_cancel('REFRESH_CANCEL', offset=(30, 30)):
                click_timer.reset()
                confirm_timer.reset()
                continue

            # 处理岛屿升级弹窗
            if click_timer.reached():
                success = True
                self.device.click(GET_ITEMS_ISLAND)
                self.device.sleep(0.3)
                click_timer.reset()
                confirm_timer.reset()
                continue

            if self.island_in_transport():
                if success and confirm_timer.reached():
                    break
                click_timer.reset()
            else:
                confirm_timer.reset()

        return success

    def transport_refresh(self, comm):
        """
        刷新指定的运输委托。

        Args:
            comm (IslandTransport): 需要刷新的委托

        Returns:
            bool: 是否成功刷新
        """
        logger.info('Transport commission refresh')
        self.interval_clear([TRANSPORT_REFRESH, POPUP_CONFIRM_WHITE])
        success = True
        confirm_timer = Timer(1, count=2).start()
        for _ in self.loop():
            if self.appear_then_click(TRANSPORT_REFRESH, offset=comm.offset, interval=2):
                continue

            if self.handle_popup_confirm('REFRESH_CONFIRM', offset=(30, 30)):
                success = True
                confirm_timer.reset()
                continue

            if self.island_in_transport():
                if success and confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()
        return success

    def transport_start(self, comm):
        """
        启动指定的运输委托。

        Args:
            comm (IslandTransport): 需要启动的委托

        Returns:
            bool: 是否成功启动
        """
        logger.info('Transport commission start')
        self.interval_clear([GET_ITEMS_ISLAND, TRANSPORT_START, POPUP_CANCEL_WHITE])
        success = True
        confirm_timer = Timer(1, count=2).start()
        for _ in self.loop():
            if self.appear_then_click(TRANSPORT_START, offset=comm.offset, interval=2):
                success = False
                confirm_timer.reset()
                continue

            if self.handle_get_items():
                success = True
                confirm_timer.reset()
                continue

            if self.handle_popup_cancel('REFRESH_CANCEL', offset=(30, 30)):
                confirm_timer.reset()
                continue

            if self.island_in_transport():
                if success and confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()
        return success

    def island_transport_run(self):
        """
        执行岛屿运输流程：领取已完成的委托，刷新和启动新委托。

        Returns:
            list[timedelta]: 未来完成时间列表
        """
        logger.hr('Island Transport Run', level=1)
        future_finish = []
        self.transport_receive()
        commissions = self.transport_detect(trial=5)

        comm_refresh = commissions.select(status='pending', refresh=True)
        comm_choose = commissions.select(status='pending', start=True)
        for comm in comm_refresh:
            if self.transport_refresh(comm):
                comm.convert_to_refreshing()
        for comm in comm_choose:
            if self.transport_start(comm):
                comm.convert_to_running()

        logger.hr('Showing transport commission', level=2)
        for comm in commissions:
            logger.attr(f'Transport Commission', comm)

        running_finish = [f for f in commissions.select(status='running').get('finish_time') if f is not None]
        refreshing_finish = [f for f in commissions.select(status='refreshing').get('finish_time') if f is not None]
        future_finish = sorted(running_finish + refreshing_finish)
        logger.info(f'Transport finish: {[str(f) for f in future_finish]}')
        if not len(future_finish):
            logger.info('No island transport running')
        return future_finish

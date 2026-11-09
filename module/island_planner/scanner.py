"""岛屿科技树扫描。

移植自 AzurLaneAutoScript（LmeSzinc/AzurLaneAutoScript，GPL-3.0）的
module/island_handler/technology_scanner.py。识别不依赖语言：用科技树连线轮廓
（assets/island/technology/technology_chart_{2..6}.png，配合 MASK_ISLAND_TECHNOLOGY）
定位当前视野，再按 data.py 中的节点坐标读取节点亮度，亮度高即已解锁。
左侧 2~6 号标签按颜色识别；1 号标签不含生产相关科技，不扫描。

AzurPilot 改动：点击加间隔、滑动加次数上限，避免无限点击或滑动。
"""
import cv2
import numpy as np

from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.mask import Mask
from module.base.timer import Timer
from module.base.utils import area_offset, color_mask, crop, load_image, random_rectangle_vector, rgb2luma
from module.island_planner.data import DIC_ISLAND_TECHNOLOGY
from module.logger import logger
from module.ui.navbar import Navbar
from module.ui.page import page_island_technology
from module.ui.ui import UI

DELTA_X = 136 + 2 / 3
DELTA_Y = 60
ORIGIN_X = -5 / 3
ORIGIN_Y = 46
LEFT_STRIP = 167
MASK_ISLAND_TECHNOLOGY = Mask('./assets/mask/MASK_ISLAND_TECHNOLOGY.png')
DETECTION_AREA = (167, 54, 1280, 720)
DETECTION_AREA_MASK = (1098, 646, 1280, 720)
BUTTON_AREA = (-110, -26, 110, 26)
SCANNED_TABS = (2, 3, 4, 5, 6)
# 最长的 5 号标签约 4400 像素宽，每次滑动 600，留足余量
MAX_SWIPES = 15
# 节点平均亮度超过该值视为已解锁
UNLOCKED_LUMA = 160


def extract_flowchart(image):
    """提取科技树连线轮廓，用于与整张科技树模板匹配。"""
    brightness = rgb2luma(image)
    brightness_mask = cv2.inRange(brightness, 160, 255)
    black_mask = color_mask(image, (7, 10, 17), threshold=10)
    mask = cv2.bitwise_or(brightness_mask, black_mask)
    contours, _ = cv2.findContours(mask.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled_mask = np.zeros_like(mask)
    cv2.drawContours(filled_mask, contours, -1, 255, thickness=cv2.FILLED)
    filled_mask = MASK_ISLAND_TECHNOLOGY.apply(filled_mask)
    return filled_mask[:, LEFT_STRIP:]


def get_technology_tab_and_position(technology_id):
    """科技所在标签及其在整张科技树上的中心坐标。"""
    info = DIC_ISLAND_TECHNOLOGY[technology_id]
    axis_x, axis_y = info['axis']
    return info['tech_belong'], (ORIGIN_X + DELTA_X * axis_x, ORIGIN_Y + DELTA_Y * axis_y)


def node_in_view(position, view_x):
    """节点按钮是否完整位于可识别区域内（右下角按钮遮挡区除外）。"""
    tech_x, tech_y = position
    x = LEFT_STRIP + tech_x - view_x
    if not DETECTION_AREA[0] - BUTTON_AREA[0] <= x <= DETECTION_AREA[2] - BUTTON_AREA[2]:
        return False
    return not (tech_y > DETECTION_AREA_MASK[1] + BUTTON_AREA[1] and x >= DETECTION_AREA_MASK[0])


def node_unlocked(image, position, view_x):
    tech_x, tech_y = position
    button = crop(image, area=area_offset(BUTTON_AREA, (LEFT_STRIP + tech_x - view_x, tech_y)))
    return float(np.mean(rgb2luma(button))) > UNLOCKED_LUMA


class IslandTechnologyScanner(UI):
    """扫描岛屿科技 2~6 号标签的解锁状态。

    Pages:
        in: 任意页面
        out: page_island_technology
    """

    @cached_property
    def _side_navbar(self):
        grids = ButtonGrid(origin=(13, 107), delta=(0, 196 / 3), button_shape=(128, 43), grid_shape=(1, 5))
        return Navbar(grids=grids, active_color=(30, 143, 255), inactive_color=(50, 52, 55),
                      active_count=500, inactive_count=500)

    def _side_navbar_get_active(self):
        """当前标签号；左侧导航栏全未激活时为 1 号标签。"""
        active, _, _ = self._side_navbar.get_info(main=self)
        if active is None:
            return 1
        return active + 2

    def side_navbar_ensure(self, tab, skip_first_screenshot=True):
        """切换到指定科技标签。

        Args:
            tab (int): 2~6 对应左侧导航栏 1~5 格。
        """
        click_timer = Timer(2)
        for _ in self.loop(skip_first=skip_first_screenshot, timeout=30):
            active = self._side_navbar_get_active()
            if active == tab:
                return True
            if active == 1:
                # 1 号标签时导航栏全未激活，Navbar.set 无法判断当前格，直接点目标格
                if click_timer.reached():
                    self.device.click(self._side_navbar.grids.buttons[tab - 2])
                    click_timer.reset()
                continue
            self._side_navbar.set(self, upper=tab - 1)
            return True
        logger.warning(f'[岛屿-科技] 切换到科技标签 {tab} 超时')
        return False

    @cached_property
    def _globe_views(self):
        return {tab: load_image(f'./assets/island/technology/technology_chart_{tab}.png') for tab in SCANNED_TABS}

    def get_view_position(self, tab):
        """当前视野左边缘在整张科技树中的横坐标。"""
        result = cv2.matchTemplate(self._globe_views[tab], extract_flowchart(self.device.image), cv2.TM_CCOEFF_NORMED)
        _, _, _, location = cv2.minMaxLoc(result)
        return location[0]

    def _swipe(self, forward=True):
        vector = (-600, 0) if forward else (600, 0)
        p1, p2 = random_rectangle_vector(vector, box=DETECTION_AREA, random_range=(-50, -50, 50, 50), padding=20)
        self.device.drag(p1, p2, segments=2, shake=(0, 25), point_random=(0, 0, 0, 0), shake_random=(0, -5, 0, 5))
        self.device.click_record_remove('DRAG')

    def reset_view(self, tab, skip_first_screenshot=True):
        """滑到科技树最左端。"""
        for _ in range(MAX_SWIPES):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.get_view_position(tab) < 3:
                return True
            self._swipe(forward=False)
        logger.warning(f'[岛屿-科技] 标签 {tab} 未能滑回最左端')
        return False

    def scan_tab(self, tab, nodes):
        """从左到右滑过一个标签，返回已解锁的科技 ID。

        Args:
            tab (int): 科技标签。
            nodes (dict): {科技ID: 坐标}。
        """
        unlocked = set()
        last_x = None
        for _ in range(MAX_SWIPES):
            self.device.screenshot()
            view_x = self.get_view_position(tab)
            # 视野不再移动即已到最右端
            if last_x is not None and view_x - last_x < 5:
                break
            last_x = view_x
            for technology_id, position in nodes.items():
                if node_in_view(position, view_x) and node_unlocked(self.device.image, position, view_x):
                    unlocked.add(technology_id)
            self._swipe(forward=True)
        else:
            logger.warning(f'[岛屿-科技] 标签 {tab} 滑动次数达到上限 {MAX_SWIPES}')
        return unlocked

    def scan_all(self):
        """
        Returns:
            dict[int, bool]: {科技ID: 是否解锁}，只含 2~6 号标签。
        """
        nodes_by_tab = {tab: {} for tab in SCANNED_TABS}
        for technology_id in DIC_ISLAND_TECHNOLOGY:
            tab, position = get_technology_tab_and_position(technology_id)
            if tab in nodes_by_tab:
                nodes_by_tab[tab][technology_id] = position
        unlocked = set()
        for tab in SCANNED_TABS:
            logger.hr(f'Island technology tab {tab}', level=2)
            self.side_navbar_ensure(tab=tab)
            self.device.screenshot()
            self.reset_view(tab)
            found = self.scan_tab(tab, nodes_by_tab[tab])
            logger.attr(f'IslandTechnologyTab{tab}', f'{len(found)}/{len(nodes_by_tab[tab])}')
            unlocked |= found
        return {technology_id: technology_id in unlocked
                for nodes in nodes_by_tab.values() for technology_id in nodes}

    def get_technology_status(self):
        self.ui_ensure(page_island_technology)
        return self.scan_all()

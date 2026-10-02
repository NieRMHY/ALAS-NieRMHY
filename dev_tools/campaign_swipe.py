from campaign.campaign_main.campaign_7_2 import MAP
from module.campaign.campaign_base import CampaignBase
from module.config.config import AzurLaneConfig
from module.logger import logger
from module.map_detection.homography import Homography
from module.map_detection.utils import *


class Config:
    pass
    # Universal configs to reduce error
    INTERNAL_LINES_HOUGHLINES_THRESHOLD = 40
    EDGE_LINES_HOUGHLINES_THRESHOLD = 40
    DETECTION_BACKEND = 'perspective'

    INTERNAL_LINES_FIND_PEAKS_PARAMETERS = {
        'height': (80, 255 - 24),
        'width': (1.5, 10),
        'prominence': 10,
        'distance': 35,
    }
    EDGE_LINES_FIND_PEAKS_PARAMETERS = {
        'height': (255 - 40, 255),
        'prominence': 10,
        'distance': 50,
        'wlen': 1000
    }

    STORY_OPTION = -2

    MAP_FOCUS_ENEMY_AFTER_BATTLE = True
    MAP_HAS_SIREN = True
    MAP_HAS_FLEET_STEP = True
    IGNORE_LOW_EMOTION_WARN = False

    MAP_GRID_CENTER_TOLERANCE = 0.2
    MAP_SWIPE_MULTIPLY = (1.320, 1.009)
    MAP_SWIPE_MULTIPLY_MINITOUCH = (1.276, 0.974)


cfg = AzurLaneConfig('alas', task='Alas').merge(Config())
cfg.DETECTION_BACKEND = 'perspective'
az = CampaignBase(cfg)
az.map = MAP
# az.device.disable_stuck_detection()

az.update()
hm = Homography(cfg)
# Load from a known homo_storage
# sto = ((10, 5), [(137.776, 83.461), (1250.155, 83.461), (18.123, 503.909), (1396.595, 503.909)])
# hm.load_homography(storage=sto)

# Or from screenshot
hm.load_homography(image=np.array(az.device.image))


class SwipeSimulate:
    """地图滑动参数拟合模拟器，计算并校验不同触摸控制方式的滑动乘数。"""

    def __init__(self, swipe, simulate_count=4):
        """初始化滑动模拟器。

        Args:
            swipe (tuple[float, float]): 初始滑动的向量 (x, y)。
            simulate_count (int): 每次拟合测试的模拟重复次数。
        """
        self.simulate_count = simulate_count
        self.swipe = np.array(swipe, dtype=float)
        self.swipe_base = self.cal_swipe_base()
        logger.info(f'Swipe base {self.swipe_base}')

    def cal_swipe_base(self):
        """计算视野内网格基准像素距离。

        Returns:
            np.ndarray: [横向网格基准, 纵向网格基准]。
        """
        swipe_base = None
        for loca, grid in az.view.grids.items():
            offset = grid.screen2grid([az.config.SCREEN_CENTER])[0].astype(int)
            points = grid.grid2screen(np.add([[0.5, 0], [-0.5, 0], [0, 0.5], [0, -0.5]], offset))
            swipe_base = np.array([np.linalg.norm(points[0] - points[1]), np.linalg.norm(points[2] - points[3])])
            break

        if swipe_base is None:
            logger.critical('无法获取到网格基准')
            exit(1)
        else:
            return swipe_base

    @staticmethod
    def normalise_offset(offset):
        """将透视单应性坐标转换为滑动偏移量。

        将范围在 0 到 140 的单应坐标归一化到 -70 到 70 的差值范围。

        Args:
            offset (np.ndarray): 原始单应性定位坐标。

        Returns:
            np.ndarray: 归一化后的偏移量。
        """
        if offset[0] > 70:
            offset[0] -= 140
        if offset[1] > 100:
            offset[1] -= 140
        return offset

    def simulate(self):
        """执行一组滑动模拟，测量误差并调整滑动手势向量。

        Returns:
            float: 拟合后的横向偏差绝对值。
        """
        logger.hr(f'Swipe: {self.swipe}', level=1)
        record = []
        for n in range(self.simulate_count):
            hm.detect(az.device.image)
            # hm.draw()
            init_offset = self.normalise_offset(hm.homo_loca)

            az.device.swipe_vector(self.swipe)
            az.device.sleep(0.3)
            az.device.screenshot()
            hm.detect(az.device.image)
            offset = self.normalise_offset(hm.homo_loca)
            record.append(offset - init_offset)
            # fit = hm.fit_points(np.array(record), encourage=2)
            fit = np.mean(record, axis=0)
            # (170, 65)
            multiply = np.round(np.abs(self.swipe) / (3, 3) / self.swipe_base, 3)
            logger.info(
                f'[{n}/{self.simulate_count}] init_offset={init_offset}, offset={offset}, fit={fit}, multiply={multiply}')

            fleet = az.get_fleet_show_index()
            az.fleet_set(3 - fleet)
            az.fleet_set(fleet)
            # az.fleet_set(3)
            # az.fleet_set(1)
            az.ensure_no_info_bar()

        self.multiply = multiply
        self.swipe -= (fit[0], 0)
        # self.swipe -= (0, fit[1])
        self.show()
        return abs(fit[0])

        # return abs(fit[1])

    def show(self):
        """打印最终计算得到的滑动乘数配置代码。"""
        print()
        print(f'Last swipe: {self.swipe}')
        print('Result to copy:')
        print()

        adb, minitouch, maatouch = get_multiplier(self.multiply[0])
        print(f'    MAP_SWIPE_MULTIPLY = {adb}')
        print(f'    MAP_SWIPE_MULTIPLY_MINITOUCH = {minitouch}')
        print(f'    MAP_SWIPE_MULTIPLY_MAATOUCH = {maatouch}')
        print()

    def run(self):
        """持续运行模拟直至滑动误差收敛在阈值范围内。"""
        while 1:
            result = self.simulate()
            if result <= 1:
                break


def get_multiplier(minitouch_x):
    """根据横向乘数换算 ADB、minitouch 和 maatouch 对应的配置元组。

    Args:
        minitouch_x (float): minitouch 的横向基准比例。

    Returns:
        tuple[str, str, str]: 分别对应 ADB、minitouch、maatouch 的格式化配置字符串。
    """
    # MAP_SWIPE_MULTIPLY = (1.064, 1.084)
    # MAP_SWIPE_MULTIPLY_MINITOUCH = (1.029, 1.048)
    # MAP_SWIPE_MULTIPLY_MAATOUCH = (0.999, 1.017)
    minitouch = np.array((1.029, 1.048)) / 1.029 * minitouch_x
    adb = np.array((1.064, 1.084)) / 1.029 * minitouch_x
    maatouch = np.array((0.999, 1.017)) / 1.029 * minitouch_x
    return f'({adb[0]:.3f}, {adb[1]:.3f})', \
           f'({minitouch[0]:.3f}, {minitouch[1]:.3f})', \
           f'({maatouch[0]:.3f}, {maatouch[1]:.3f})'


if __name__ == '__main__':
    """
    To fit MAP_SWIPE_MULTIPLY.
    
    Before running this, move your fleet on map to be like this:
    FL is current fleet, Fl is another fleet.
    Camera should focus on current fleet (Double click switch over to refocus)
    -- -- -- -- -- --
    -- Fl -- -- FL --
    -- -- -- -- -- --
    After run, Result is ready to copy.
    """
    sim = SwipeSimulate((420, 0)).run()

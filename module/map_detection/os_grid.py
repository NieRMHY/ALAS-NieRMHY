"""大世界网格模块。定义 OSGridInfo 和 OSGrid 类，扩展基础网格以支持大世界特有的
网格属性（敌人、资源、问号、盟友等）和雷达扫描检测。"""

from module.base.utils import *
from module.map_detection.grid import Grid, GridInfo, GridPredictor
from module.map_detection.utils_assets import ASSETS
from module.os.assets import *
from module.os.radar import RadarGrid
from module.template.assets import *


class OSGridInfo(GridInfo):
    is_os = True

    is_enemy = False  # Red gun
    is_resource = False  # green box to get items
    is_exclamation = False  # Yellow exclamation mark '!'
    is_meowfficer = False  # Blue meowfficer
    is_question = False  # White question mark '?'
    is_ally = False  # Ally cargo ship in daily mission, yellow '!' on radar
    is_akashi = False  # White question mark '?'
    is_scanning_device = False
    is_logging_tower = False
    is_exploration_reward = False
    is_exploration_container = False
    is_fleet_mechanism = False

    is_fleet = False

    is_radar_scanned = False

    @property
    def is_interactive_only(self):
        """舰队无法直接走上该格子，只能在其相邻格进行互动（如盟友和明石）。"""
        return self.is_ally or self.is_akashi

    def encode(self):
        dic = {
            'AL': 'is_ally',
            'AK': 'is_akashi',
            'SD': 'is_scanning_device',
            'LT': 'is_logging_tower',
            'ER': 'is_exploration_reward',
            'EC': 'is_exploration_container',
            'FM': 'is_fleet_mechanism',
        }
        for key, value in dic.items():
            if self.__getattribute__(value):
                return key

        if self.is_siren:
            name = self.enemy_genre[6:8].upper() if self.enemy_genre else 'SU'
            return name if name else 'SU'

        if self.is_enemy:
            return '%s%s' % (
                self.enemy_scale if self.enemy_scale else 0,
                self.enemy_genre[0].upper() if self.enemy_genre else 'E')

        dic = {
            'RE': 'is_resource',
            'EX': 'is_exclamation',
            'ME': 'is_meowfficer',
            'QU': 'is_question',
            'FL': 'is_fleet',
            '==': 'is_radar_scanned'
        }
        for key, value in dic.items():
            if self.__getattribute__(value):
                return key

        return '--'

    def merge(self, info, mode='normal'):
        """将大世界扫描信息合并到当前网格。

        Args:
            info (OSGridInfo | RadarGrid): 待合并的大世界网格或雷达网格对象。
            mode (str, optional): 扫描模式，大世界中通常为 'normal'。默认为 'normal'。

        Returns:
            bool: 是否合并成功。
        """
        if isinstance(info, RadarGrid):
            self.is_radar_scanned = True

        if info.is_ally:
            self.is_ally = True
            return True
        if info.is_akashi:
            self.is_akashi = True
            return True
        if info.is_scanning_device:
            self.is_scanning_device = True
            return True
        if info.is_logging_tower:
            self.is_logging_tower = True
            return True
        if info.is_exploration_reward:
            self.is_exploration_reward = True
            return True
        if info.is_exploration_container:
            self.is_exploration_container = True
            return True
        if info.is_fleet_mechanism:
            self.is_fleet_mechanism = True
            return True

        if info.is_question:
            self.is_question = True
            return True
        if info.is_meowfficer:
            self.is_meowfficer = True
            return True
        if info.is_exclamation:
            self.is_exclamation = True
            return True
        if info.is_resource:
            self.is_resource = True
            return True
        if info.is_enemy:
            self.is_enemy = True
            if info.enemy_scale:
                self.enemy_scale = info.enemy_scale
            if info.enemy_genre and not (info.enemy_genre == 'Enemy' and self.enemy_genre):
                self.enemy_genre = info.enemy_genre
            return True

        # if info.is_fleet:
        #     self.is_fleet = True
        #     return True

        return True

    def wipe_out(self):
        """当舰队移动到该网格时清除上面的敌人或事件标记。"""
        super().wipe_out()

        self.is_enemy = False
        self.is_resource = False
        self.is_exclamation = False
        self.is_meowfficer = False
        self.is_question = False
        self.is_scanning_device = False
        self.is_logging_tower = False
        self.is_exploration_reward = False
        self.is_exploration_container = False
        self.is_fleet_mechanism = False

    def reset(self):
        """进入地图后重置大世界网格的所有状态。"""
        super().reset()

        self.is_radar_scanned = False
        self.is_ally = False
        self.is_akashi = False


class OSGridPredictor(GridPredictor):
    def predict(self):
        """预测大世界网格上的对象类型（敌人、资源、机关等）。"""
        self.enemy_genre = self.predict_enemy_genre()
        # self.enemy_scale = self.predict_enemy_scale()
        # self.is_resource = self.predict_resource()
        # self.is_meowfficer = self.predict_meowfficer()  # 这会增加约 100ms 的总耗时
        # self.is_ally = self.predict_ally()
        self.is_akashi = self.enemy_genre == 'Akashi'
        self.is_scanning_device = self.enemy_genre == 'ScanningDevice'
        self.is_logging_tower = self.enemy_genre == 'LoggingTower'
        self.is_exploration_reward = self.enemy_genre == 'ExplorationReward'
        self.is_exploration_container = self.enemy_genre == 'ExplorationContainer'
        self.is_current_fleet = self.predict_current_fleet()
        self.is_fleet = self.is_current_fleet
        self.is_fleet_mechanism = self.predict_fleet_mechanism()

        if self.enemy_genre:
            self.is_enemy = True
        if self.enemy_scale:
            self.is_enemy = True
        # if not self.is_enemy:
        #     self.is_enemy = self.predict_static_red_border()
        if self.is_enemy and not self.enemy_genre:
            self.enemy_genre = 'Enemy'
        if self.config.MAP_HAS_SIREN:
            if self.enemy_genre is not None and self.enemy_genre.startswith('Siren'):
                self.is_siren = True
                self.enemy_scale = 0

    def predict_fleet(self):
        """预测大世界网格上是否有舰队（大世界没有弹药图标，通过光标预测）。

        Returns:
            bool: 是否有舰队。
        """
        # 大世界中没有弹药图标
        return super().predict_current_fleet()

    def predict_sea(self):
        """预测大世界网格是否为海洋。

        Returns:
            bool: 是否为海洋地块。
        """
        color = cv2.mean(self.image_trans)
        if not min(color[1], color[2]) > color[0] + 20:
            return False

        area = area_pad((48, 48, 48 + 46, 48 + 46), pad=5)
        res = cv2.matchTemplate(ASSETS.tile_center_image, crop(self.image_homo, area=area, copy=False), cv2.TM_CCOEFF_NORMED)
        _, sim, _, _ = cv2.minMaxLoc(res)
        if sim > lower_template_match_similarity(0.8):
            return True

        # tile = 135
        # corner = 25
        # corner = [(5, 5, corner, corner), (tile - corner, 5, tile, corner), (5, tile - corner, corner, tile),
        #           (tile - corner, tile - corner, tile, tile)]
        # for area, template in zip(corner[::-1], ASSETS.tile_corner_image_list[::-1]):
        #     res = cv2.matchTemplate(template, crop(self.image_homo, area=area), cv2.TM_CCOEFF_NORMED)
        #     _, sim, _, _ = cv2.minMaxLoc(res)
        #     if sim > 0.8:
        #         return True

        return False

    _os_template_enemy = {
        'Akashi': TEMPLATE_SIREN_Akashi,
        'ScanningDevice': TEMPLATE_ScanningDevice,
        'LoggingTower': TEMPLATE_LoggingTower,
        'ExplorationReward': TEMPLATE_ExplorationReward,
        'ExplorationContainer': TEMPLATE_ExplorationContainer,
    }
    _os_template_enemy_upper = {
        'ScanningDevice': TEMPLATE_ScanningDeviceUpper,
        'LoggingTower': TEMPLATE_LoggingTowerUpper,
    }

    def predict_enemy_genre(self):
        """预测大世界敌舰或特殊装置的类型（如明石、扫描装置、记录塔等）。

        Returns:
            str | None: 识别出的类型名称；若未识别出则返回 None。
        """
        image = rgb2gray(self.relative_crop((-0.5, -1, 0.5, 0), shape=(60, 60)))
        for name, template in self._os_template_enemy.items():
            if template.match(image, similarity=0.9, direct_match=True):
                return name

        image = rgb2gray(self.relative_crop((-0.5, -2, 0.5, -1), shape=(60, 60)))
        for name, template in self._os_template_enemy_upper.items():
            if template.match(image, similarity=0.9, direct_match=True):
                return name

        return None

    def predict_enemy_scale(self):
        """检测左上角显示的敌人规模（大型、中型）。

        Returns:
            int: 2 为中型, 3 为大型, 0 为未知。
        """
        point = (-0.385, 0.815)
        size = (0.53, 0.53)
        image = self.relative_crop((point[0] - size[0], point[1] - size[1], point[0], point[1]), shape=(50, 50))
        red = color_similarity_2d(image, (255, 130, 132))
        yellow = color_similarity_2d(image, (255, 235, 156))

        if TEMPLATE_ENEMY_L.match(red):
            scale = 3
        elif TEMPLATE_ENEMY_M.match(yellow):
            scale = 2
        # 禁用单三角敌人的检测
        # 在大世界中地图上的灯塔会被误检测为单三角小型敌人
        # elif TEMPLATE_ENEMY_S.match(yellow):
        #     scale = 1
        else:
            scale = 0

        return scale

    def predict_resource(self):
        """预测网格是否为物资箱。

        Returns:
            bool: 是否为物资箱。
        """
        image = rgb2gray(self.relative_crop((-0.5, -1, 0.5, 0), shape=(60, 60)))
        return TEMPLATE_OS_Resource.match(image, similarity=0.85, direct_match=True)

    def predict_meowfficer(self):
        """预测网格是否为指挥喵搜索点。

        Returns:
            bool: 是否为指挥喵搜索点。
        """
        image = rgb2gray(self.image_trans)
        return TEMPLATE_OS_Meowfficer.match(image, similarity=0.85, direct_match=True)

    def predict_ally(self):
        """预测网格是否为每日任务中的盟友运输舰。

        Returns:
            bool: 是否为盟友运输舰。
        """
        # 每日任务中的盟友货船
        image = rgb2gray(self.relative_crop((-0.5, -0.5, 0.5, 0.5), shape=(60, 60)))
        return TEMPLATE_OS_AllyCargo.match(image, similarity=0.85, direct_match=True)

    def predict_akashi(self):
        """预测网格是否为明石（奸商问号）。

        Returns:
            bool: 是否为明石。
        """
        image = rgb2gray(self.relative_crop((-0.5, -1, 0.5, 0), shape=(60, 60)))
        return TEMPLATE_SIREN_Akashi.match(image, similarity=0.85, direct_match=True)

    def predict_caught_by_siren(self):
        """预测是否处于被塞壬拦截贴脸状态（检测红色战斗中背景）。

        Returns:
            bool: 是否被塞壬拦截。
        """
        # 检测「作战中」字样的红色斜条纹背景
        return self.relative_rgb_count(
            area=(-1, -0.5, 0, 0.5), color=(255, 109, 91), shape=(50, 50), threshold=30) > 120

    def predict_fleet_mechanism(self):
        """预测网格是否包含舰队机关控制台。

        Returns:
            bool: 是否匹配舰队机关。
        """
        # 获取上边界
        area = self.grid2screen(np.array([(0, 0), (1, 0.2)]))
        area = np.rint(area.flatten()).astype(int).tolist()
        # 青色颜色范围
        h = (185, 195)
        s = (15, 90)
        v = (60, 100)
        image = cv2.cvtColor(crop(self.image, area, copy=False), cv2.COLOR_RGB2HSV)
        lower = (h[0] / 2, s[0] * 2.55, v[0] * 2.55)
        upper = (h[1] / 2 + 1, s[1] * 2.55 + 1, v[1] * 2.55 + 1)
        image = cv2.inRange(image, lower, upper)
        # 压扁为单条水平线
        line = np.max(image, axis=0)
        # 线条应当是连续的；若不连续说明可能有舰队停在上面
        if np.mean(line) < 180:
            return False
        # 还应当有随机白色矩形
        area = self.grid2screen(np.array([(0.2, 0.2), (0.8, 0.8)]))
        area = np.rint(area.flatten()).astype(int).tolist()
        image = color_similarity_2d(crop(self.image, area, copy=False), color=(255, 255, 255))
        count = image[image > 221].shape[0]
        if count < 30:
            return False
        # 不应包含任何绿色或黄色（绿色是岛屿，黄色是传送带）
        # 匹配数字 '2' 模板
        image = rgb2gray(self.image_trans)
        sim, button = TEMPLATE_FleetMechanism.match_result(image)
        point = (53, 37)
        distance = np.linalg.norm(np.subtract(button.area[:2], point))
        if distance > 5 or sim < lower_template_match_similarity(0.3):
            return False

        return True


class OSGrid(OSGridInfo, OSGridPredictor, Grid):
    """大世界地图网格单元类。

    组合大世界网格属性、预测能力和基础网格几何信息。
    """
    pass

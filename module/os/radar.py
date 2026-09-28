"""
大世界雷达检测模块。

负责大世界（Operation Siren）模式下的雷达系统，通过分析屏幕右上角的
雷达小地图来识别附近的敌人、资源、港口、问号等对象。

主要类:
    RadarGrid: 雷达格子数据类，表示雷达上的一个可识别位置。
    Radar: 雷达管理类，管理所有雷达格子并提供预测和查询接口。

雷达布局:
    雷达以当前舰队位置为中心，呈圆形分布格子。
    默认参数: center=(1140, 226), delta=(11.7, 11.7), radius=5.15。
    每个格子通过颜色检测来判断其类型（敌人/资源/港口等）。

术语:
    雷达 (Radar): 大世界地图右上角的小地图，显示附近的对象。
    塞壬 (Siren): 大世界中的敌对势力，在雷达上显示为红色标记。
    明石 (Akashi): 大世界中的隐藏商店，显示为白色问号。
    指挥喵 (Meowfficer): 大世界中的辅助系统，显示为蓝色标记。
"""
from module.base.mask import Mask
from module.base.utils import *
from module.config.config import AzurLaneConfig
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.map_detection.utils import fit_points

MASK_RADAR = Mask('./assets/mask/MASK_OS_RADAR.png')


class RadarGrid:
    """雷达格子数据类。

    表示雷达小地图上的一个位置，通过颜色检测来判断其类型。
    每个格子可以是敌人、资源、港口、问号等不同类型。

    Attributes:
        location (tuple[int, int]): 格子相对于雷达中心的坐标，如 (3, 2)。
        center (tuple[int, int]): 格子中心在截图中的像素坐标。
        is_enemy (bool): 是否为敌人（红色枪标记）。
        is_resource (bool): 是否为资源（绿色箱子）。
        is_exclamation (bool): 是否为感叹号（黄色 '!'）。
        is_meowfficer (bool): 是否为指挥喵（蓝色标记）。
        is_question (bool): 是否为问号（白色 '?'）。
        is_ally (bool): 是否为友军（黄色 '!'，日常任务中的货运船）。
        is_akashi (bool): 是否为明石（白色 '?'，隐藏商店）。
        is_archive (bool): 是否为档案（紫色标记）。
        is_port (bool): 是否为港口。
        is_fleet (bool): 是否为当前舰队位置（坐标原点）。
        enemy_scale (int): 敌人规模（0=未知，1=轻型，2=主力，3=航母）。
        enemy_genre (str): 敌人类型描述，如 'Light'、'Main'、'Carrier'。
    """
    is_enemy = False  # Red gun
    is_resource = False  # green box to get items
    is_exclamation = False  # Yellow exclamation mark '!'
    is_meowfficer = False  # Blue meowfficer
    is_question = False  # White question mark '?'
    is_ally = False  # Ally cargo ship in daily mission, yellow '!' on radar
    is_akashi = False  # White question mark '?'
    is_archive = False  # Purple archive
    is_port = False

    enemy_scale = 0
    enemy_genre = None  # Light, Main, Carrier, Treasure, Enemy(unknown)

    is_fleet = False

    dic_encode = {
        'EN': 'is_enemy',
        'RE': 'is_resource',
        'AR': 'is_archive',
        'EX': 'is_exclamation',
        'ME': 'is_meowfficer',
        'PO': 'is_port',
        'QU': 'is_question',
        'FL': 'is_fleet',
    }

    def __init__(self, location, image, center, config):
        """初始化雷达格子对象。

        Args:
            location (tuple[int, int]): 相对于雷达中心的网格坐标 (x, y)，如 (3, 2)。
            image (np.ndarray | None): 截图图像数据。
            center (tuple[int, int]): 格子在截图中的像素中心点 (x, y)。
            config (AzurLaneConfig): 配置对象。
        """
        self.location = location
        self.image: np.ndarray = image
        self.center = center
        self.config = config
        self.is_fleet = np.sum(np.abs(location)) == 0

    def encode(self):
        """将雷达格子的当前属性编码为双字符代码。

        Returns:
            str: 格子属性代码（如 'EN', 'RE', 'QU' 等），无特殊属性时返回 '--'。
        """
        for key, value in self.dic_encode.items():
            if self.__getattribute__(value):
                return key

        return '--'

    @property
    def str(self):
        return self.encode()

    def reset(self):
        """重置雷达格子的所有检测状态。"""
        self.is_enemy = False
        self.is_resource = False
        self.is_exclamation = False
        self.is_meowfficer = False
        self.is_question = False
        self.is_port = False

        self.is_ally = False
        self.is_akashi = False

        self.enemy_scale = 0
        self.enemy_genre = None

        # self.is_fleet = False

    def predict(self):
        """预测当前雷达格子的实体类型。

        依次检测敌人、资源、指挥喵、感叹号、港口、问号和档案等特征。
        """
        if self.is_fleet:
            return False

        self.is_enemy = self.predict_enemy() or self.predict_boss()
        self.is_resource = self.predict_resource()
        self.is_meowfficer = self.predict_meowfficer()
        self.is_exclamation = self.predict_exclamation()
        self.is_port = self.predict_port()
        self.is_question = self.predict_question()
        self.is_archive = self.predict_archive()

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

    def image_color_count(self, area, color, threshold=30, count=50):
        """统计格子指定区域内匹配目标颜色的像素数量。

        Args:
            area (tuple[int, int, int, int]): 相对于格子中心的检测区域。
            color (tuple[int, int, int]): 目标 RGB 颜色。
            threshold (int): 颜色容差，越小越严格。默认 30。
            count (int): 触发判定的最小像素数。默认 50。

        Returns:
            bool: 匹配像素数达到阈值返回 True，否则返回 False。
        """
        image = crop(self.image, area_offset(area, self.center), copy=False)
        mask = color_mask(image, color=color, threshold=threshold)
        return cv2.countNonZero(mask) >= count

    def predict_enemy(self):
        """检测是否为普通敌人（红色枪标志）。

        Returns:
            bool: 是否匹配。
        """
        return self.image_color_count(area=(-3, -3, 3, 3), color=(247, 89, 49), threshold=30, count=10)

    def predict_resource(self):
        """检测是否为资源箱（绿色箱子）。

        Returns:
            bool: 是否匹配。
        """
        return self.image_color_count(area=(-3, -3, 3, 3), color=(66, 231, 165), threshold=30, count=10)

    def predict_meowfficer(self):
        """检测是否为指挥喵搜索点（蓝色标记）。

        Returns:
            bool: 是否匹配。
        """
        return self.image_color_count(area=(-3, 0, 3, 6), color=(33, 186, 255), threshold=30, count=10)

    def predict_exclamation(self):
        """检测是否为事件感叹号（黄色 '!'）。

        Returns:
            bool: 是否匹配。
        """
        return self.image_color_count(area=(-3, -3, 3, 3), color=(255, 203, 49), threshold=30, count=10)

    def predict_boss(self):
        """检测是否为 Boss 敌人（暗深红色标记）。

        Returns:
            bool: 是否匹配。
        """
        return self.image_color_count(area=(-3, -3, 3, 3), color=(147, 12, 8), threshold=30, count=10)

    def predict_port(self):
        """检测是否为港口入口（白色标记）。

        Returns:
            bool: 是否匹配。
        """
        return self.image_color_count(area=(-3, -3, 3, 3), color=(255, 255, 255), threshold=20, count=9)

    def predict_question(self):
        """检测是否为问号事件（白色 '?'）。

        Returns:
            bool: 是否匹配。
        """
        return self.image_color_count(area=(0, -7, 6, 0), color=(255, 255, 255), threshold=20, count=9)

    def predict_archive(self):
        """检测是否为塞壬档案（紫色标记）。

        Returns:
            bool: 是否匹配。
        """
        return self.image_color_count(area=(-3, -3, 3, 3), color=(173, 113, 255), threshold=20, count=10)


class Radar:
    """雷达管理类。

    管理大世界地图右上角雷达小地图的所有格子，提供预测、查询和
    港口定位等功能。格子以圆形分布，中心为当前舰队位置。

    Attributes:
        grids (dict[tuple, RadarGrid]): 雷达格子字典，键为 (x, y) 坐标。
        center_loca (tuple[int, int]): 雷达中心位置（当前舰队）。
        port_loca (tuple): 上次检测到的港口位置。
        config (AzurLaneConfig): 配置对象。
        center (tuple[int, int]): 雷达在截图中的像素中心点。
        delta (tuple[float, float]): 格子间的像素间距。
        shape (list[list[int]]): 雷达网格的形状范围。
    """
    grids: dict
    center_loca = (0, 0)
    port_loca = (0, 0)

    def __init__(self, config, center=(1140, 226), delta=(11.7, 11.7), radius=5.15):
        """初始化雷达小地图检测器。

        Args:
            config (AzurLaneConfig): 配置对象。
            center (tuple[int, int]): 雷达小地图中心在截图中的像素坐标。默认 (1140, 226)。
            delta (tuple[float, float]): 相邻格子中心的像素偏移增量。默认 (11.7, 11.7)。
            radius (float): 雷达有效圆形扫描半径（以网格距离计）。默认 5.15。
        """
        self.grids = {}
        self.config = config
        self.center = center
        self.delta = delta

        center = np.array(center)
        delta = np.array(delta)
        radius_int = int(radius)
        self.shape = [[-radius_int, radius_int + 1], [-radius_int, radius_int + 1]]
        for x in range(*self.shape[0]):
            for y in range(*self.shape[1]):
                if np.linalg.norm([x, y]) > radius:
                    continue
                grid_center = np.round(delta * (x, y) + center).astype(int)
                self.grids[(x, y)] = RadarGrid(location=(x, y), image=None, center=grid_center, config=self.config)

    def __iter__(self):
        return iter(self.grids.values())

    def __getitem__(self, item):
        """获取指定坐标的雷达格子对象。

        Returns:
            RadarGrid: 雷达格子实例。
        """
        return self.grids[tuple(item)]

    def __contains__(self, item):
        return tuple(item) in self.grids

    def show(self):
        """在日志中打印当前雷达所有格子的排布状态矩阵。"""
        for y in range(*self.shape[1]):
            text = ' '.join([self[(x, y)].str if (x, y) in self else '  ' for x in range(*self.shape[0])])
            logger.info(text)

    def predict(self, image):
        """根据当前游戏截图更新雷达中所有格子的预测状态。

        Args:
            image (np.ndarray): 游戏截图。
        """
        image = MASK_RADAR.apply(image)
        for grid in self:
            grid.image = image
            grid.reset()
            grid.predict()
        # 修正港口附近的问号误读
        for port in self.select(is_port=True):
            for grid in self.select(is_question=True):
                if np.sum(np.abs(np.subtract(port.location, grid.location))) == 1:
                    logger.warning(f'[大世界-雷达] 雷达预测错误 is_question {grid.location} {grid.encode()} '
                                   f'靠近 {port.location} {port.encode()}')
                    grid.is_question = False

    def select(self, **kwargs):
        """筛选符合指定属性条件的雷达格子集合。

        Args:
            **kwargs: RadarGrid 的属性过滤条件。

        Returns:
            SelectedGrids: 匹配的雷达格子集合。
        """
        result = []
        for grid in self:
            flag = True
            for k, v in kwargs.items():
                if grid.__getattribute__(k) != v:
                    flag = False
            if flag:
                result.append(grid)

        return SelectedGrids(result)

    def predict_port_outside(self, image):
        """检测雷达范围外环形区域内的港口图标位置。

        Args:
            image (np.ndarray): 截图。

        Returns:
            np.ndarray | None: 相对于雷达中心的港口图标坐标，未找到返回 None。
        """
        radius = (15, 82)
        image = crop(image, area_offset((-radius[1], -radius[1], radius[1], radius[1]), self.center), copy=False)
        # image.show()
        points = np.where(color_similarity_2d(image, color=(255, 255, 255)) > 250)
        points = np.array(points).T[:, ::-1] - (radius[1], radius[1])
        distance = np.linalg.norm(points, axis=1)
        points = points[np.all([distance < radius[1], distance > radius[0]], axis=0)]
        if len(points):
            point = fit_points(points, mod=(1000, 1000), encourage=5)
            point[point > 500] -= 1000
            self.port_loca = point
            return point
        else:
            return None

    def predict_port_inside(self, image):
        """检测雷达内部可见网格中的港口位置。

        Args:
            image (np.ndarray): 截图。

        Returns:
            np.ndarray | None: 雷达网格中的相对坐标，未找到返回 None。
        """
        self.predict(image)
        for grid in self:
            if grid.is_port:
                # 前往港口相邻格子
                location = np.array(grid.location) - np.sign(grid.location) * (1, 1)
                self.port_loca = location
                return location

        return None

    @staticmethod
    def port_outside_to_inside(point):
        """将雷达外港口方向转换为边界上的最接近网格坐标。

        Args:
            point (np.ndarray): 外环检测出的港口方向向量。

        Returns:
            np.ndarray: 雷达视野边界上的对应网格坐标。
        """
        sight = (-4, -2, 3, 2)
        grids = [(x, y) for x in range(sight[0], sight[2] + 1) for y in [sight[1], sight[3]]] \
                + [(x, y) for x in [sight[0], sight[2]] for y in range(sight[1] + 1, sight[3])]
        grids = np.array([loca for loca in grids])
        distance = np.linalg.norm(grids, axis=1)
        degree = np.sum(grids * point, axis=1) / distance / np.linalg.norm(point)
        grid = grids[np.argmax(degree)]
        return grid

    def port_predict(self, image):
        """综合预测并返回可驶向港口的目标网格坐标。

        Args:
            image (np.ndarray): 截图。

        Returns:
            np.ndarray | None: 港口或朝向港口的网格坐标，未找到返回 None。
        """
        port = self.predict_port_inside(image)
        if port is not None:
            return port

        point = self.predict_port_outside(image)
        if point is not None:
            port = self.port_outside_to_inside(point)
            return port

        return None

    def predict_akashi(self, image):
        """检测雷达中是否存在明石（隐藏商店）坐标。

        Args:
            image (np.ndarray): 截图。

        Returns:
            tuple[int, int] | None: 明石在雷达上的相对坐标，未找到返回 None。
        """
        self.predict(image)
        for location in [(0, 1), (-1, 0), (1, 0), (0, -1)]:
            grid = self[location]
            if grid.is_question and not grid.predict_port():
                return location

        return None

    def predict_question(self, image, in_port=True):
        """预测雷达上距离舰队最近的问号事件坐标。

        Args:
            image (np.ndarray): 截图。
            in_port (bool): 为 False 时将港口图标也视作问号处理。默认 True。

        Returns:
            tuple[int, int] | None: 问号在雷达上的相对网格坐标，未找到返回 None。
        """
        self.predict(image)
        self.show()
        # 扫描顺序按距离近优先：相邻4格 → 相邻斜角4格 → 距离2（上/下/左/右）→ 距离3（上/左/右）。
        # 不扩展正下方3格：本地视野为10x7且舰队位于(5,4)，下方仅2行余量，
        # 超出视野的问号无法经 convert_radar_to_local 转换点击，只会空耗重试。
        for location in [
            (0, 1), (-1, 0), (1, 0), (0, -1),
            (1, 1), (-1, 1), (1, -1), (-1, -1),
            (0, -2), (0, -3),
            (-2, 0), (2, 0), (0, 2),
            (-3, 0), (3, 0),
        ]:
            grid = self[location]
            if in_port:
                if grid.is_question and not grid.is_port:
                    return location
            else:
                if grid.is_question or grid.is_port:
                    return location

        return None

    def nearest_object(self, camera_sight=(-4, -3, 3, 3)):
        """
        Args:
            camera_sight:

        Returns:
            RadarGrid: Or None if no objects
        """
        objects = []
        for grid in self:
            if grid.is_port:
                continue
            if grid.is_enemy or grid.is_resource or grid.is_meowfficer \
                    or grid.is_exclamation or grid.is_question or grid.is_archive:
                objects.append(grid)
        objects = SelectedGrids(objects).sort_by_camera_distance((0, 0))
        if not objects:
            return None

        nearest = objects[0]
        limited = point_limit(nearest.location, area=camera_sight)
        if nearest.location == limited:
            return nearest
        else:
            return self[limited]

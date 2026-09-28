"""全球地图海域数据管理模块。

定义海域（Zone）数据结构和海域管理器（ZoneManager）。

海域是大世界全球地图上的可进入区域，每个海域有：
- zone_id: 海域编号
- shape: 地图形状（如 J10、P16）
- hazard_level: 侵蚀等级（1-7）
- cn/en/jp/tw: 各服务器的名称
- area_pos: 信息栏固定位置
- offset_pos: 任务固定位置偏移
- region: 所在区域（1-5，对应全球地图的象限）
- is_port: 是否为港口
- is_azur_port: 是否为碧蓝航线港口

ZoneManager 管理所有海域实例，提供按类型、区域、状态的查询接口。
"""

import numpy as np

from module.base.decorator import cached_property
from module.exception import ScriptError
from module.map.map_grids import SelectedGrids
from module.os.globe_detection import GLOBE_MAP_SHAPE
from module.os.map_data import DIC_OS_MAP


class Zone:
    """海域数据类。

    存储单个海域的所有属性信息。

    Attributes:
        zone_id (int): 海域编号。
        shape (str): 地图形状，如 'J10'。
        hazard_level (int): 侵蚀等级，1-7。
        cn/en/jp/tw (str): 各服务器的海域名称。
        area_pos (tuple): 信息栏固定位置。
        offset_pos (tuple): 任务固定位置偏移。
        region (int): 所在区域（1=左上, 2=右上, 3=左下, 4=右下, 5=中心）。
        is_port (bool): 是否为港口。
        is_azur_port (bool): 是否为碧蓝航线港口。
    """
    zone_id: int
    # Map shape, such as J10
    shape: str
    # Corrosion level, from 1 to 7
    hazard_level: int
    # Name in different servers
    cn: str
    en: str
    jp: str
    tw: str
    # Position where information bar is pinned on
    area_pos: tuple
    # area_pos + offset_pos is where mission pinned on
    offset_pos: tuple
    # 1 for upper-left, 2 for upper-right, 3 for bottom-left, 4 for bottom-right, 5 for center
    region: int

    is_port: bool
    is_azur_port: bool

    def __init__(self, zone_id, data):
        """初始化海域对象。

        Args:
            zone_id (int): 海域 ID。
            data (dict): 包含海域配置参数的字典。
        """
        self.zone_id = zone_id
        self.__dict__.update(data)
        self.location = self.point_convert(self.area_pos)
        self.mission = self.point_convert(np.add(self.area_pos, self.offset_pos))
        self.is_port = self.zone_id in [0, 1, 2, 3, 4, 5, 6, 7, 154]
        self.is_azur_port = self.zone_id in [0, 1, 2, 3]

    @staticmethod
    def point_convert(point):
        """将 world_chapter_colormask.lua 中的坐标转换为 os_globe_map.png 坐标。

        Args:
            point (tuple[float, float] | np.ndarray): 原始配置坐标 (x, y)。

        Returns:
            np.ndarray: 转换后在全球地图中的坐标数组。
        """
        point = np.multiply(point, 1.25)
        point = np.array((point[0], GLOBE_MAP_SHAPE[1] - point[1]))  # 1694 为 os_globe_map.png 的高度
        return point

    def __str__(self):
        """
        Returns:
            str: 如 `[3|圣彼得伯格|St. Petersburg|ペテルブルク|聖彼得堡]`
        """
        return f'[{self.zone_id}|{self.en}]'

    __repr__ = __str__

    def __eq__(self, other):
        return self.zone_id == other.zone_id


class ZoneManager:
    """全球海域管理器。

    管理大世界所有海域实例，提供按区域、名称、侵蚀等级的检索接口。

    Attributes:
        zone (Zone): 当前所处的海域实例。
    """
    zone: Zone

    @cached_property
    def zones(self):
        """获取所有海域的集合对象。

        Returns:
            SelectedGrids: 包含所有 Zone 实例的集合对象。
        """
        return SelectedGrids([Zone(zone_id, info) for zone_id, info in DIC_OS_MAP.items()])

    def camera_to_zone(self, camera, region=None):
        """根据全球地图坐标检索距离最近的海域对象。

        Args:
            camera (tuple[float, float]): 全球地图中的相机坐标。
            region (int | None): 可选的限定区域编号。默认 None。

        Returns:
            Zone: 距离指定坐标最近的海域对象。
        """
        if region is None:
            zones = self.zones
        else:
            zones = self.zones.select(region=region)
        zones = zones.sort_by_camera_distance(camera=camera)
        return zones[0]

    def name_to_zone(self, name):
        """将各种格式的海域标识转换为对应的海域实例。

        支持 Zone 实例、海域 ID 数值、字符串以及四服语言名称的匹配。

        Args:
            name (str | int | Zone): 各服语言名称、海域 ID 或 Zone 实例。

        Returns:
            Zone: 匹配到的海域实例。

        Raises:
            ScriptError: 无法找到对应海域时抛出。
        """
        if isinstance(name, Zone):
            return name
        elif isinstance(name, int):
            try:
                return self.zones.select(zone_id=name)[0]
            except IndexError as e:
                raise ScriptError(f'Unable to find OS globe zone: {name}') from e
        elif isinstance(name, str) and name.isdigit():
            try:
                return self.zones.select(zone_id=int(name))[0]
            except IndexError as e:
                raise ScriptError(f'Unable to find OS globe zone: {name}') from e
        else:
            def parse_name(n):
                n = str(n).replace(' ', '').lower()
                return n

            name = parse_name(name)
            for zone in self.zones:
                if name == parse_name(zone.cn):
                    return zone
                if name == parse_name(zone.en):
                    return zone
                if name == parse_name(zone.jp):
                    return zone
                if name == parse_name(zone.tw):
                    return zone
            for zone in self.zones:
                for lang_name in [zone.cn, zone.tw]:
                    parsed = parse_name(lang_name)
                    if len(name) == len(parsed) + 1 and name.startswith(parsed):
                        from module.logger import logger
                        logger.warning(
                            f'Zone fuzzy match: OCR={name}, Zone={lang_name}'
                        )
                        return zone
            # 普通难度：仲裁者·XXX, 困难难度：仲裁者·XXX, 困难模拟战：仲裁机关
            for keyword in ['普通', '困难', '仲裁']:
                if keyword in name:
                    return self.name_to_zone(154)
            # Normal - Arbiter: XXX, Hard - Arbiter: XXX, Hard - Arbiter (Practice)
            for keyword in ['normal', 'hard', 'arbiter']:
                if keyword in name:
                    return self.name_to_zone(154)
            # ノーマル：アビータ・XXX, ハード：アビータ・XXX, ハード模擬戦：アビータ
            for keyword in ['ノーマル', 'ハード', 'アビータ',
                            'ノ一マル', 'ハ一ド', 'アビ一タ']:
                if keyword in name:
                    return self.name_to_zone(154)
            # 普通難度：仲裁者·XXX, 困難難度：仲裁者·XXX, 困難模擬戰：仲裁機關
            for keyword in ['普通', '困難', '仲裁']:
                if keyword in name:
                    return self.name_to_zone(154)
            raise ScriptError(f'Unable to find OS globe zone: {name}')

    def zone_nearest_azur_port(self, zone):
        """查找离指定海域最近的碧蓝航线港口。

        优先选择同区域的港口，其次选择直线距离最近的港口。

        Args:
            zone (str | int | Zone): 海域标识或实例。

        Returns:
            Zone: 最近的碧蓝航线港口海域对象。
        """
        zone = self.name_to_zone(zone)
        ports = self.zones.select(is_azur_port=True).delete(SelectedGrids([self.zone]))
        # 同区域港口
        for port in ports:
            if zone.region == port.region:
                return port
        # 跨区域港口
        ports = ports.sort_by_camera_distance(camera=tuple(zone.location))
        return ports[0]

    def zone_select(self, hazard_level):
        """筛选指定侵蚀等级的海域集合（排除中央区域 5）。

        Args:
            hazard_level (int): 侵蚀等级 (1-6)，或 10 代表中央海域。

        Returns:
            SelectedGrids: 符合条件的海域集合对象。

        Raises:
            ScriptError: 侵蚀等级数值无效时抛出。
        """
        if 1 <= hazard_level <= 6:
            return self.zones.select(hazard_level=hazard_level).delete(self.zones.select(region=5))
        elif hazard_level == 10:
            return self.zones.select(region=5)
        else:
            raise ScriptError(f'Invalid hazard_level of zones: {hazard_level}')

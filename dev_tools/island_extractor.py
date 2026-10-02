import re

from dev_tools.slpp import slpp
from dev_tools.utils import LuaLoader


class IslandItem:
    """岛屿道具数据封装类。"""

    def __init__(self, item):
        """解析岛屿道具数据。

        在 'sharecfg/island_item_data_template.lua' 中：
        id: 道具序号
        name: 服务器中道具名称，默认国服
        pt_num: 该道具的 PT 值
        manage_influence: 餐厅经营影响力
        order_price: 订单系统价格

        Args:
            item (dict): 道具源数据字典。
        """
        self.id = item['id']
        # self.name = item['name']
        self.pt_num = item['pt_num']
        self.manage_influence = item['manage_influence']
        self.order_price = item['order_price']

    def encode(self):
        """将道具信息转换为字典保存格式。

        Returns:
            dict: 包含各语言名称与数值属性的道具数据字典。
        """
        data = {
            # 'id': self.id,
            'name': {
                'cn': '',
                'en': '',
                'jp': '',
                # 'tw': '',
            },
            'pt_num': self.pt_num,
            'manage_influence': self.manage_influence,
            'order_price': self.order_price,
        }
        return data


class IslandItemExtractor:
    """岛屿道具提取器，负责从游戏 Lua 数据提取并格式化道具配置。"""

    def __init__(self):
        """初始化提取器并从 Lua 脚本中读取道具数据。"""
        self.item = {}

        data = LOADER.load('sharecfg/island_item_data_template.lua', keyword='pg.base.island_item_data_template')
        for index, item in data.items():
            if not isinstance(index, int) or 0 < index < 1000 or index > 100000:
                continue

            self.item[item['id']] = IslandItem(item).encode()

        for index, name in self.extract_item_name('zh-CN').items():
            self.item[index]['name']['cn'] = name
        for index, name in self.extract_item_name('en-US').items():
            self.item[index]['name']['en'] = name
        for index, name in self.extract_item_name('ja-JP').items():
            self.item[index]['name']['jp'] = name
        # for index, name in self.extract_item_name('zh-TW').items():
        #     self.item[index]['name']['tw'] = name

    def extract_item_name(self, server):
        """提取指定服务器语言下的道具名称映射。

        Args:
            server (str): 服务器语言标识（例如 'zh-CN', 'en-US', 'ja-JP'）。

        Returns:
            dict[int, str]: 道具 ID 到道具名称的映射字典。
        """
        LOADER.server = server
        data = LOADER.load('sharecfg/island_item_data_template.lua', keyword='pg.base.island_item_data_template')
        out = {}
        for index, item in data.items():
            if not isinstance(index, int) or 0 < index < 1000 or index > 100000:
                continue
            out[item['id']] = item['name']

        return out

    def encode(self):
        """将提取的道具数据编码为 Python 字典代码行列表。

        Returns:
            list[str]: 格式化后的代码行列表。
        """
        lines = []
        lines.append('DIC_ISLAND_ITEM = {')
        lines.append("    0: {'name': {'cn': '岛屿开发PT', 'en': 'Island Development Points', 'jp': '離島開発Pt'}, 'pt_num': 1, 'manage_influence': 0, 'order_price': 0},")
        for index, item in self.item.items():
            lines.append(f'    {index}: {item},')
        lines.append('}')
        return lines

    def write(self, file):
        """将提取的道具数据写入指定文件。

        Args:
            file (str): 目标输出文件路径。
        """
        print(f'writing {file}')
        with open(file, 'w', encoding='utf-8') as f:
            for text in self.encode():
                f.write(text + '\n')


def unpack_ingredient_dic(dic):
    """解包配方原料或产物字典。

    Args:
        dic (dict): 包含原料或产物键值对的字典。

    Returns:
        dict: 解包后的道具 ID 到数量的映射字典。

    Raises:
        TypeError: 输入数据不是字典或结构无法解包时抛出。
    """
    try:
        result = {}
        for _, entry in dic.items():
            # print(entry)
            result[entry[0]] = entry[1]
        return result
    except TypeError:
        print(dic)
        raise


class IslandRecipe:
    """岛屿配方数据封装类。"""

    def __init__(self, recipe):
        """解析岛屿配方数据。

        在 'sharecfg/island_formula.lua' 中：
        id: 配方序号
        name: 服务器名称，默认国服
        workload: 耗时，单位为 0.1 秒
        commission_cost: 嵌套原料字典，每项为道具 ID 和数量元组
        production_limit: 单次委托连续生产上限
        commission_product: 嵌套产物字典，为道具 ID 和数量
        second_product_display: 嵌套副产物字典，为道具 ID 和数量

        Args:
            recipe (dict): 配方数据字典。
        """
        self.id = recipe['id']
        # self.name = recipe['name']
        self.workload = recipe['workload']
        self.commission_cost = recipe['commission_cost']
        # self.production_limit = recipe['production_limit']
        self.commission_product = recipe['commission_product']
        self.second_product_display = recipe['second_product_display']

    def encode(self):
        """将配方信息转换为字典结构。

        Returns:
            dict: 配方 ID 到详细参数的字典。
        """
        data = {
            self.id: {
                # 'name': self.name,
                'workload': self.workload,
                'commission_cost': unpack_ingredient_dic(self.commission_cost),
                # 'production_limit': self.production_limit,
                'commission_product': unpack_ingredient_dic(self.commission_product),
                'second_product_display': unpack_ingredient_dic(self.second_product_display),
            }
        }
        return data


class IslandRecipeExtractor:
    """岛屿配方提取器。"""

    def __init__(self):
        """初始化提取器并加载解析配方数据。"""
        self.recipe = {}
        data = LOADER.load('sharecfg/island_formula.lua')
        for index, item in data.items():
            if not isinstance(index, int) or not (index // 10000 < 700 or index // 10000 >= 990):
                continue
            if item['attribute'] in [1, 2, 3, 4, 6]:
                self.recipe.update(IslandRecipe(item).encode())

                # print(item['id'],
                #       item['name'],
                #       item['workload'] // 10,
                #       item['commission_cost'],
                #       item['production_limit'],
                #       item['commission_product'],
                #       item['second_product_display'])

    def encode(self):
        """将配方列表编码为 Python 代码行列表。

        Returns:
            list[str]: 格式化后的代码行列表。
        """
        lines = []
        lines.append('DIC_ISLAND_RECIPE = {')
        for index, recipe in self.recipe.items():
            lines.append(f'    {index}: {recipe},')
        lines.append('}')
        return lines

    def write(self, file):
        """将配方数据写入文件。

        Args:
            file (str): 目标输出文件路径。
        """
        print(f'writing {file}')
        with open(file, '', encoding='utf-8') as f:
            for text in self.encode():
                f.write(text + '\n')


def unpack_activity_formula(dic):
    """解包活动配方列表。

    Args:
        dic (dict): 活动配方嵌套字典。

    Returns:
        list: 解包后的配方 ID 列表。
    """
    try:
        result = []
        for _, entry in dic.items():
            result += [item for _, item in entry[1].items()]
        return result
    except TypeError:
        print(dic)


class IslandProduction:
    """岛屿生产槽位封装类。"""

    def __init__(self, slot):
        """解析生产槽位数据。

        在 'sharecfg/island_production_slot.lua' 中：
        type: 1 = 农业, 2 = 矿业, 3 = 牧业, 4 = 餐饮, 6 = 工业
        place: 槽位位置
        exclusion_slot: 互斥槽位 ID
        formula: 适用配方
        activity_formula: 活动 ID 与活动配方

        Args:
            slot (dict): 槽位配置字典。
        """
        self.id = slot['id']
        self.attribute = slot['attribute']
        self.place = slot['place']
        self.formula = [item for _, item in slot['formula'].items()]
        self.activity_formula = unpack_activity_formula(slot['activity_formula'])

    def encode(self):
        """编码生产槽位数据。

        Returns:
            dict: 槽位 ID 映射的属性字典。
        """
        data = {
            self.id: {
                'attribute': self.attribute,
                'place': self.place,
                'formula': self.formula,
                'activity_formula': self.activity_formula,
            }
        }
        return data


class IslandProductionExtractor:
    """岛屿生产槽位提取器。"""

    def __init__(self):
        """初始化提取器并加载生产槽位数据。"""
        self.slot = {}
        data = LOADER.load('sharecfg/island_production_slot.lua')
        for index, item in data.items():
            if not isinstance(index, int) or index < 9000 or index > 10000:
                continue
            # print(item['attribute'], item['place'], item['formula'], item['activity_formula'])
            self.slot.update(IslandProduction(item).encode())

    def encode(self):
        """将生产槽位编码为代码行列表。

        Returns:
            list[str]: 代码行列表。
        """
        lines = []
        lines.append('DIC_ISLAND_SLOT = {')
        for index, slot in self.slot.items():
            lines.append(f'    {index}: {slot},')
        lines.append('}')
        return lines

    def write(self, file):
        """将槽位数据写入文件。

        Args:
            file (str): 目标文件路径。
        """
        print(f'writing {file}')
        with open(file, 'w', encoding='utf-8') as f:
            for text in self.encode():
                f.write(text + '\n')


class IslandShopItemExtractor:
    """岛屿商店商品提取器。"""

    def __init__(self):
        """初始化提取器并加载商店商品数据。"""
        self.item = {}
        data = LOADER.load('sharecfg/island_shop_goods.lua', keyword='pg.base.island_shop_goods')
        for index, item in data.items():
            if not isinstance(index, int) or index < 100000 or index >= 412000:
                continue
            try:
                self.item[index] = {
                    'resource_consume': {item['resource_consume'][1]: item['resource_consume'][2]},
                    'items': {
                        itm[1]: itm[2] for _, itm in item['items'].items()
                    },
                }
                # print(self.item[index])
            except Exception:
                print(index, item)
                raise

    def encode(self):
        """将商店商品编码为代码行列表。

        Returns:
            list[str]: 代码行列表。
        """
        lines = []
        lines.append('DIC_ISLAND_SHOP_ITEM = {')
        for index, item in self.item.items():
            lines.append(f'    {index}: {item},')
        lines.append('}')
        return lines

    def write(self, file):
        """将商店商品数据写入文件。

        Args:
            file (str): 目标输出文件路径。
        """
        print(f'writing {file}')
        with open(file, 'w', encoding='utf-8') as f:
            for text in self.encode():
                f.write(text + '\n')


class IslandExchangeRecipeExtractor:
    """岛屿物资兑换配方提取器。"""

    def __init__(self):
        """初始化提取器并加载兑换模板。"""
        self.item = {}
        data = LOADER.load('sharecfg/island_exchange_template.lua')
        for index, item in data.items():
            if not isinstance(index, int):
                continue
            try:
                self.item[index] = {
                    'resource_consume': {item['origin_item']: 1},
                    'items': {
                        item['target_item']: item['target_num']
                    },
                }
            except Exception:
                print(index, item)
                raise

    def encode(self):
        """将兑换配方编码为代码行列表。

        Returns:
            list[str]: 代码行列表。
        """
        lines = []
        lines.append('DIC_ISLAND_EXCHANGE_RECIPE = {')
        for index, item in self.item.items():
            lines.append(f'    {index}: {item},')
        lines.append('}')
        return lines


def island_time_to_sql_time(island_time):
    """将游戏内部岛屿时间格式转换为 SQL 标准日期时间字符串。

    时间格式形如: {0: {0: 2026, 1: 2, 2: 5}, 1: {0: 12, 1: 0, 2: 0}}

    Args:
        island_time (dict): 包含年月日、时分秒的嵌套字典。

    Returns:
        str: 格式化后的时间字符串 (YYYY-MM-DD HH:MM:SS)。
    """
    year = island_time[0][0]
    month = island_time[0][1]
    day = island_time[0][2]
    hour = island_time[1][0]
    minute = island_time[1][1]
    second = island_time[1][2]
    return f'{year:04}-{month:02}-{day:02} {hour:02}:{minute:02}:{second:02}'


class IslandSeason:
    """岛屿赛季数据封装类。"""

    def __init__(self, season):
        """解析赛季配置数据。

        在 'sharecfg/island_season.lua' 中：
        id: 赛季序号
        time: 赛季有效时间范围
        task_list: 该赛季的任务列表

        Args:
            season (dict): 赛季配置字典。
        """
        # self.id = season['id']
        self.end_time = island_time_to_sql_time(season['time'][1])
        self.task_list = [task for _, task in season['task_list'].items()]

    def encode(self):
        """编码赛季数据。

        Returns:
            dict: 包含结束时间与任务列表的字典。
        """
        data = {
            'end_time': self.end_time,
            'task_list': self.task_list,
        }
        return data

class IslandSeasonExtractor:
    """岛屿赛季数据提取器。"""

    def __init__(self):
        """初始化提取器并加载赛季数据。"""
        self.season = {}
        data = LOADER.load('sharecfg/island_season.lua')
        for index, item in data.items():
            if not isinstance(index, int):
                continue
            # print(item['task_list'].values())
            self.season[item['id']] = IslandSeason(item).encode()
        # print(self.season)

    def encode(self):
        """将赛季数据编码为代码行列表。

        Returns:
            list[str]: 代码行列表。
        """
        lines = []
        lines.append('DIC_ISLAND_SEASON = {')
        for index, season in self.season.items():
            lines.append(f'    {index}: {season},')
        lines.append('}')
        return lines

    def write(self, file):
        """将赛季数据写入文件。

        Args:
            file (str): 目标输出文件路径。
        """
        print(f'writing {file}')
        with open(file, 'w', encoding='utf-8') as f:
            for text in self.encode():
                f.write(text + '\n')

    def get_latest_season(self):
        """获取最新的赛季 ID。

        Returns:
            int: 最新赛季编号。
        """
        return list(self.season.keys())[-1]

class IslandSeasonalTaskExtractor(IslandSeasonExtractor):
    """岛屿赛季任务提取器。"""

    def __init__(self):
        """初始化提取器并加载当前最新赛季关联的任务数据。"""
        super().__init__()
        self.target_id_to_task_id = {}
        current_season = self.get_latest_season()
        self.task_list = self.season[current_season]['task_list']
        print(self.task_list)
        self.task = {}
        data = LOADER.load('sharecfg/island_task.lua', keyword='pg.base.island_task')
        for index, item in data.items():
            if not isinstance(index, int):
                continue
            if item['id'] not in self.task_list:
                continue
            self.task[item['id']] = {
                'name': {
                    'cn': '',
                    'en': '',
                    'jp': '',
                    # 'tw': '',
                },
                'target_id': item['target_id'][0],
            }
            self.target_id_to_task_id[item['target_id'][0]] = item['id']
        for index, name in self.extract_item_name('zh-CN').items():
            self.task[index]['name']['cn'] = name
        for index, name in self.extract_item_name('en-US').items():
            self.task[index]['name']['en'] = name
        for index, name in self.extract_item_name('ja-JP').items():
            self.task[index]['name']['jp'] = name
        # for index, name in self.extract_item_name('zh-TW').items():
        #     self.item[index]['name']['tw'] = name
        data = LOADER.load('sharecfg/island_task_target.lua', keyword='pg.base.island_task_target')
        for index, item in data.items():
            if not isinstance(index, int):
                continue
            if item['id'] not in self.target_id_to_task_id:
                continue
            task_id = self.target_id_to_task_id[item['id']]
            if isinstance(item['target_param'], dict):
                self.task[task_id]['target'] = {item['target_param'][0]: item['target_num']}
            else:
                self.task[task_id]['target'] = {}

    def extract_item_name(self, server):
        """提取指定服务器语言下的任务名称。

        Args:
            server (str): 服务器标识。

        Returns:
            dict[int, str]: 任务 ID 到任务名称的映射。
        """
        LOADER.server = server
        data = LOADER.load('sharecfg/island_task.lua', keyword='pg.base.island_task')
        out = {}
        for index, item in data.items():
            if not isinstance(index, int) or not item['id'] in self.task.keys():
                continue
            out[item['id']] = item['name']

        return out

    def encode(self):
        """将赛季任务编码为代码行列表。

        Returns:
            list[str]: 代码行列表。
        """
        lines = []
        lines.append('DIC_ISLAND_SEASONAL_TASK = {')
        for index, task in self.task.items():
            lines.append(f'    {index}: {task},')
        lines.append('}')
        return lines

    def write(self, file):
        """将赛季任务数据写入文件。

        Args:
            file (str): 目标输出文件路径。
        """
        print(f'writing {file}')
        with open(file, 'w', encoding='utf-8') as f:
            for text in self.encode():
                f.write(text + '\n')

class IslandRestaurantExtractor:
    """岛屿餐厅料理配方提取器。"""

    def __init__(self):
        """初始化提取器并加载餐厅配方数据。"""
        self.restaurant = {}
        data = LOADER.load('sharecfg/island_manage_restaurant.lua')
        for index, item in data.items():
            if not isinstance(index, int):
                continue
            self.restaurant.update({
                item['id']: {
                    recipe[0]: recipe[1] for _, recipe in item['item_id'].items()
                }
            })

    def encode(self):
        """将餐厅配方编码为代码行列表。

        Returns:
            list[str]: 代码行列表。
        """
        lines = []
        lines.append('DIC_ISLAND_RESTAURANT_RECIPE = {')
        for index, restaurant in self.restaurant.items():
            lines.append(f'    {index}: {restaurant},')
        lines.append('}')
        return lines

    def write(self, file):
        """将餐厅配方写入文件。

        Args:
            file (str): 目标输出文件路径。
        """
        print(f'writing {file}')
        with open(file, 'w', encoding='utf-8') as f:
            for text in self.encode():
                f.write(text + '\n')


class IslandTechnology:
    """岛屿科技项数据封装类。"""

    def __init__(self, item):
        """解析岛屿科技项数据。

        Args:
            item (dict): 科技配置项字典。
        """
        self.id = item['id']
        self.tech_belong = item['tech_belong']
        self.axis_x = item['axis'][0]
        self.axis_y = item['axis'][1]
        self.island_level = item['island_level']

    def encode(self):
        """编码科技项信息。

        Returns:
            dict: 科技详情字典。
        """
        data = {
            'name': {
                'cn': '',
                'en': '',
                'jp': '',
                # 'tw': '',
            },
            'tech_belong': self.tech_belong,
            'axis': (self.axis_x, self.axis_y),
            'island_level': self.island_level,
        }
        return data

class IslandTechnologyExtractor:
    """岛屿科技树提取器。"""

    def __init__(self):
        """初始化提取器并加载科技树数据。"""
        self.item = {}

        data = LOADER.load('sharecfg/island_technology_template.lua', keyword='pg.base.island_technology_template')
        for index, item in data.items():
            if not isinstance(index, int) or item['tech_belong'] == 1:
                continue

            self.item[item['id']] = IslandTechnology(item).encode()

        for index, name in self.extract_item_name('zh-CN').items():
            self.item[index]['name']['cn'] = name
        for index, name in self.extract_item_name('en-US').items():
            self.item[index]['name']['en'] = name
        for index, name in self.extract_item_name('ja-JP').items():
            self.item[index]['name']['jp'] = name
        # for index, name in self.extract_item_name('zh-TW').items():
        #     self.item[index]['name']['tw'] = name

    def extract_item_name(self, server):
        """提取指定服务器语言下的科技名称。

        Args:
            server (str): 服务器标识。

        Returns:
            dict[int, str]: 科技 ID 到名称的映射。
        """
        LOADER.server = server
        data = LOADER.load('sharecfg/island_technology_template.lua', keyword='pg.base.island_technology_template')
        out = {}
        for index, item in data.items():
            if not isinstance(index, int) or item['tech_belong'] == 1:
                continue
            out[item['id']] = item['tech_name']

        return out

    def encode(self):
        """将科技数据编码为代码行列表。

        Returns:
            list[str]: 代码行列表。
        """
        lines = []
        lines.append('DIC_ISLAND_TECHNOLOGY = {')
        for index, item in self.item.items():
            lines.append(f'    {index}: {item},')
        lines.append('}')
        return lines

    def write(self, file):
        """将科技数据写入文件。

        Args:
            file (str): 目标输出文件路径。
        """
        print(f'writing {file}')
        with open(file, 'w', encoding='utf-8') as f:
            for text in self.encode():
                f.write(text + '\n')


if __name__ == '__main__':
    FILE = '../AzurLaneLuaScripts'
    LOADER = LuaLoader(FILE, server='CN')
    save = './module/island/data.py'

    lines = []
    lines.append('# This file was automatically generated by dev_tools/island_extractor.py')
    lines.append("# Don't modify it manually.")
    lines.append('')
    lines.append('DIC_ISLAND_PASSIVE_RECIPE = {')
    lines.append('    1: {"refresh_times": ["03:00"], "product": {2606: 1}},')
    lines.append('    2: {"refresh_times": ["03:00"], "product": {2606: 1}},')
    lines.append('    3: {"refresh_times": ["03:00"], "product": {2606: 1}},')
    lines.append('    4: {"refresh_times": ["03:00"], "product": {2606: 1}},')
    lines.append('    5: {"refresh_times": ["03:00"], "product": {2606: 1}},')
    lines.append('    6: {"refresh_times": ["03:00"], "product": {2606: 1}},')
    lines.append('    40101: {"refresh_times": ["03:00", "18:00"], "product": {2700: 8}},')
    lines.append('    40102: {"refresh_times": ["03:00", "18:00"], "product": {2700: 8}},')
    lines.append('    40103: {"refresh_times": ["03:00", "18:00"], "product": {2700: 8}},')
    lines.append('    40104: {"refresh_times": ["03:00", "18:00"], "product": {2700: 8}},')
    lines.append('    40105: {"refresh_times": ["03:00", "18:00"], "product": {2700: 8}},')
    lines.append('    40106: {"refresh_times": ["03:00", "18:00"], "product": {2700: 8}},')
    lines.append('    40107: {"refresh_times": ["03:00", "18:00"], "product": {2700: 8}},')
    lines.append('    40108: {"refresh_times": ["03:00", "18:00"], "product": {2700: 8}},')
    lines.append('    40109: {"refresh_times": ["03:00", "18:00"], "product": {2700: 8}},')
    lines.append('    40201: {"refresh_times": ["03:00", "18:00"], "product": {2800: 8}},')
    lines.append('    40202: {"refresh_times": ["03:00", "18:00"], "product": {2800: 8}},')
    lines.append('    40203: {"refresh_times": ["03:00", "18:00"], "product": {2800: 8}},')
    lines.append('    40204: {"refresh_times": ["03:00", "18:00"], "product": {2800: 8}},')
    lines.append('    40205: {"refresh_times": ["03:00", "18:00"], "product": {2800: 8}},')
    lines.append('    40206: {"refresh_times": ["03:00", "18:00"], "product": {2800: 8}},')
    lines.append('    40207: {"refresh_times": ["03:00", "18:00"], "product": {2800: 8}},')
    lines.append('    40208: {"refresh_times": ["04:00", "18:00"], "product": {2800: 8}},')
    lines.append('    40209: {"refresh_times": ["04:00", "18:00"], "product": {2800: 8}},')
    lines.append('}')
    lines.append('')

    lines += IslandItemExtractor().encode()
    lines.append('')
    lines += IslandRecipeExtractor().encode()
    lines.append('')
    lines += IslandProductionExtractor().encode()
    lines.append('')
    lines += IslandShopItemExtractor().encode()
    lines.append('')
    lines += IslandExchangeRecipeExtractor().encode()
    lines.append('')
    lines += IslandSeasonExtractor().encode()
    lines.append('')
    lines += IslandSeasonalTaskExtractor().encode()
    lines.append('')
    lines += IslandRestaurantExtractor().encode()
    lines.append('')
    lines += IslandTechnologyExtractor().encode()
    with open(save, 'w', encoding='utf-8') as f:
        for text in lines:
            f.write(text + '\n')

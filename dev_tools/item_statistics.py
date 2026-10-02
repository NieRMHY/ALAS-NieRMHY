import shutil

import numpy as np
from tqdm import tqdm

import module.config.server as server

server.server = 'cn'  # Edit your server here.

from module.base.utils import load_image
from module.logger import logger
from module.statistics.battle_status import BattleStatusStatistics
from module.statistics.get_items import GetItemsStatistics
from module.statistics.utils import *

STATUS_ITEMS_INTERVAL = 10


class DropStatistics(BattleStatusStatistics, GetItemsStatistics):
    """掉落统计类，负责整合战斗状态与获取道具截图以生成掉落记录。

    Attributes:
        folder (str): 掉落截图根目录。
        template_folder (str): 道具模板保存目录。
        battle_status (dict): 战斗状态截图文件映射。
        get_items (dict): 结算道具截图文件映射。
        battle_status_timestamp (np.ndarray): 战斗状态时间戳数组。
    """

    def __init__(self, folder):
        """初始化掉落统计对象。

        Args:
            folder (str): 截图目录路径，例如 '<your_drop_screenshot_folder>/campaign_7_2'。
        """
        self.folder = folder
        self.template_folder = os.path.join(self.folder, 'item_template')
        if not os.path.exists(self.template_folder):
            shutil.copytree('./assets/stats_basic', self.template_folder)
        self.load_template_folder(self.template_folder)
        self.battle_status = load_folder(os.path.join(folder, 'status'))
        self.get_items = load_folder(os.path.join(folder, 'get_items'))
        self.battle_status_timestamp = np.array([int(f) for f in self.battle_status])

    def _items_to_status(self, get_items):
        """根据道具结算时间戳匹配最近的战斗状态截图时间戳。

        Args:
            get_items (str): 结算道具图片的时间戳或文件名。

        Returns:
            str: 对应的战斗状态图片时间戳。

        Raises:
            ImageError: 未找到与该结算时间戳匹配的战斗状态截图时抛出。
        """
        interval = np.abs(self.battle_status_timestamp - int(get_items))
        if np.min(interval) > STATUS_ITEMS_INTERVAL * 1000:
            raise ImageError(f'Timestamp: {get_items}, battle_status image not found.')
        return str(self.battle_status_timestamp[np.argmin(interval)])

    def extract_template(self, image=None, folder=None):
        """从结算道具截图中提取新模板并保存至模板文件夹。

        Args:
            image (np.ndarray, optional): 待提取图像，默认遍历文件夹中的图片。
            folder (str, optional): 目标文件夹，默认存入 item_template 目录。
        """
        for ts, file in tqdm(self.get_items.items()):
            try:
                image = load_image(file)
                super().extract_template(image, folder=self.template_folder)
            except:
                logger.warning(f'Error image: {ts}')

    def stat_drop(self, timestamp):
        """统计单次战斗结算的掉落信息。

        Args:
            timestamp (str): 结算道具截图的时间戳。

        Returns:
            list[list]: 掉落数据列表，每项包含 [道具时间戳, 战斗状态时间戳, 敌方名称, 道具名称, 道具数量]。
        """
        get_items = load_image(self.get_items[timestamp])
        battle_status_timestamp = self._items_to_status(timestamp)
        battle_status = load_image(self.battle_status[battle_status_timestamp])

        enemy_name = self.stats_battle_status(battle_status)
        items = self.stats_get_items(get_items)
        data = [[timestamp, battle_status_timestamp, enemy_name, item.name, item.amount] for item in items]
        return data

    def generate_data(self):
        """批量生成所有结算截图的掉落记录。

        Yields:
            list[list]: 单次结算的掉落数据列表。
        """
        for ts, file in tqdm(self.get_items.items()):
            try:
                data = self.stat_drop(ts)
                yield data
            except:
                logger.warning(f'Error image: {ts}')


"""
参数配置：
    FOLDER:   AzurPilot 掉落截图目录。
              示例：'<your_drop_screenshot_folder>/campaign_7_2'
    CSV_FILE: 保存的目标 CSV 文件。
              示例：'c72.csv'
"""
FOLDER = ''
CSV_FILE = ''
drop = DropStatistics(FOLDER)

"""
首次运行流程：
    1. 取消注释以下代码并运行。
    2. 重命名提取出的模板文件，例如在 <your_drop_screenshot_folder>/campaign_7_2/item_template 中。
"""
# drop.extract_template()

"""
第二次运行流程：
    1. 注释掉首次运行的代码。
    2. 取消注释以下代码并运行导出。
"""
# import csv
# with open(CSV_FILE, 'a', newline='', encoding='utf-8') as csv_file:
#     writer = csv.writer(csv_file)
#     for d in drop.generate_data():
#         writer.writerows(d)

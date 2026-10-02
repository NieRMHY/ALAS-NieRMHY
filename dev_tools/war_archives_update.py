"""作战档案更新脚本。

用于将往期活动战役目录迁移并生成作战档案关卡、更新 README 表格及字典注册表。
"""
import os
import re
import shutil
from datetime import datetime
from typing import List

from cached_property import cached_property
from tqdm import tqdm

from module.base.timer import timer
from module.config.config_updater import ConfigGenerator, ConfigUpdater
from module.logger import logger

SERVER_INDEXS = {
    'cn': 3,
    'en': 4,
    'jp': 5,
    'tw': 6
}


class WarArchivesUpdater:
    """作战档案更新器。

    负责将活动战役代码迁移、复制并配置为常驻作战档案。
    """
    aired_date = None
    event = None

    def __init__(self):
        """初始化更新器各服标识与行缓存。"""
        self.cn, self.en, self.jp, self.tw = '-', '-', '-', '-'
        self.lines: List[str]

    def reset(self):
        """重置各服状态并重新读取 campaign/Readme.md 内容。"""
        self.cn, self.en, self.jp, self.tw = '-', '-', '-', '-'
        with open('./campaign/Readme.md', 'r', encoding='utf-8') as f:
            self.lines = f.readlines()

    @cached_property
    def lines(self):
        """获取 campaign/Readme.md 中的全部文本行列表。"""
        with open('./campaign/Readme.md', 'r', encoding='utf-8') as f:
            return f.readlines()

    @cached_property
    def latest_event_cn(self):
        """解析获取国服最新活动的八位日期编号。"""
        for text in self.lines[::-1]:
            if not re.search(r'^\|.+\|$', text):
                # 非表格行
                continue
            elif re.search(r'^.*\-{3,}.*$', text):
                # 表格分隔线
                continue
            else:
                latest = [x.strip() for x in text.strip('| \n').split('|')]
                if latest[SERVER_INDEXS['cn']] != '-':
                    return re.search(r'\d{8}', latest[1]).group(0)
        return re.search(r'\d{8}', self.lines[-1].strip('| \n').split('|')[1].strip()).group(0)

    def event_name_to_time(self, name):
        """将活动名称转换为八位日期字符串。

        Args:
            name (str): 活动名称（如 '虹彩的终幕曲'）或八位日期。

        Returns:
            str: 对应的活动日期（如 '20220428'），未找到时返回最新国服活动日期。
        """
        if len(name) == 8 and re.search(r'\d{8}', name):
            return name
        for text in self.lines:
            if name in text:
                return re.search(r'\d{8}', text.strip('| \n').split('|')[1].strip()).group(0)
        return self.latest_event_cn

    def event_time_to_name(self, time):
        """将活动日期转换为美服活动名称。

        Args:
            time (str): 八位活动日期（如 '20220428'）。

        Returns:
            str: 对应的美服活动名称（如 "Rondo at Rainbow's End"），未找到时返回最新活动名称。
        """
        for text in self.lines:
            if not re.search(r'^\|.+\|$', text):
                # 非表格行
                continue
            elif re.search(r'^.*\-{3,}.*$', text):
                # 表格分隔线
                continue
            else:
                line = [x.strip() for x in text.strip('| \n').split('|')]
                if time in line[1]:
                    return line[SERVER_INDEXS['en']]
        return self.lines[-1].strip('| \n').split('|')[SERVER_INDEXS['en']].strip()

    def create_campaign_files(self, old_path, new_path):
        """从活动战役目录复制文件生成作战档案战役目录。

        Args:
            old_path (str): 源活动战役目录路径。
            new_path (str): 目标作战档案目录路径。

        Returns:
            bool: 是否成功创建目录。
        """
        if os.path.exists(old_path):
            if not os.path.exists(new_path):
                logger.info(f'Creating files at {new_path}')
                shutil.copytree(old_path, new_path, ignore=shutil.ignore_patterns('sp.py'))
            else:
                logger.info(f'Directory already exists: {new_path}, skip creating files')
                sp_path = os.path.join(new_path, 'sp.py')
                if os.path.exists(sp_path):
                    logger.info(f'Removing sp files')
                    os.remove(sp_path)
                return False
        else:
            logger.warning(f'No such directory: {old_path}')
            return False
        return True

    def modify_campaign_files(self, old_path, new_path):
        """遍历并修改新作战档案目录中的所有 Python 关卡脚本。

        Args:
            old_path (str): 原活动目录路径。
            new_path (str): 目标作战档案目录路径。
        """
        if os.path.exists(old_path) and os.path.exists(new_path):
            files = os.listdir(new_path)
            for file_name in tqdm(files):
                if os.path.splitext(file_name)[-1] == '.py':
                    self.modify_single_campaign_file(os.path.join(new_path, file_name))
        else:
            logger.warning('No such directory, skip modifying files')

    def modify_single_campaign_file(self, file_path):
        """修改单个关卡脚本中的基类导入路径。

        Args:
            file_path (str): 关卡 Python 文件路径。
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        new_lines = []
        pattern = 'from module.campaign.campaign_base import CampaignBase'
        replace = 'from ..campaign_war_archives.campaign_base import CampaignBase'
        modify = False
        for line in lines:
            modified_line = line.replace(pattern, replace)
            if line != modified_line:
                modify = True
            new_lines.append(modified_line)

        if modify:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
        else:
            logger.info(f'No changes, skip modifying file {os.path.basename(file_path)}')

    @timer
    def update_readme(self, aired_date, event):
        """在 campaign/Readme.md 表格中追加作战档案收录记录。

        Args:
            aired_date (str): 作战档案实装上线日期。
            event (str): 对应的活动日期编号。
        """
        insert = True
        for row, text in enumerate(self.lines):
            if f'war archives {event}' in text:
                insert = False
                break
            if not re.search(r'^\|.+\|$', text):
                # 非表格行
                continue
            elif re.search(r'^.*\-{3,}.*$', text):
                # 表格分隔线
                continue
            else:
                line_entries = [x.strip() for x in text.strip('| \n').split('|')]
                if re.search(r'\d{8}', text) and event in line_entries[1]:
                    directory = line_entries[1].replace('event', 'war archives')
                    for server in SERVER_INDEXS.keys():
                        if line_entries[SERVER_INDEXS[server]] == '-':
                            continue
                        elif self.__getattribute__(server) == '-':
                            self.__setattr__(server, line_entries[SERVER_INDEXS[server]])
                if 'war archives' in text:
                    insert_row = row

        if insert:
            insert_event = [aired_date, directory, self.en] + \
                        [self.__getattribute__(server) for server in SERVER_INDEXS.keys()]
            self.lines.insert(insert_row + 1, '|' + '|'.join(insert_event) + '|\n')
            with open('./campaign/Readme.md', 'w', encoding='utf-8') as f:
                f.writelines(self.lines)

    @timer
    def update_campaign_files(self, event):
        """复制并更新指定活动的战役代码文件。

        Args:
            event (str): 八位活动日期编号。
        """
        folder = './campaign'
        raw_directory = 'event_' + event + '_cn'
        directory = 'war_archives_' + event + '_cn'
        old_path = os.path.join(folder, raw_directory)
        new_path = os.path.join(folder, directory)
        self.create_campaign_files(old_path, new_path)
        self.modify_campaign_files(old_path, new_path)

    @timer
    def update_directory(self, event):
        """在 module/war_archives/dictionary.py 中注册新增的作战档案模板。

        Args:
            event (str): 八位活动日期编号。
        """
        directory = 'war_archives_' + event + '_cn'
        name = self.event_time_to_name(event).replace('\'', '').replace('-', '_').replace(' ', '_').upper()
        file_path = './module/war_archives/dictionary.py'
        modify = True
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for row, text in enumerate(lines):
            if name in text:
                modify = False
                break
            if 'war_archives' in text:
                insert_row = row

        if modify:
            lines.insert(insert_row + 1, f'    \'{directory}\': TEMPLATE_{name},\n')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
        else:
            logger.info('No changes, skip modifying dictionary.py')

    @timer
    def war_archives_update(self, aired_date=None, event=None):
        """执行作战档案的批量迁移与更新。

        Args:
            aired_date (str | list[str] | None): 作战档案实装日期，支持 'YYYYMMDD' 格式、'today' 或列表。
            event (str | list[str] | None): 活动标识，支持 'YYYYMMDD' 日期、中文活动名、'recent' 或列表。
        """
        if aired_date is None or aired_date == 'today':
            dates = [datetime.today().strftime("%Y%m%d")]
        elif isinstance(aired_date, str):
            dates = [aired_date]
        elif isinstance(aired_date, list):
            dates = [datetime.today().strftime("%Y%m%d") if d == 'today' else d for d in aired_date]
        else:
            logger.warning('Wrong Aired Date format')
            dates = []

        if event is None or event == 'recent':
            events = [self.latest_event_cn]
        elif isinstance(event, str):
            events = [self.event_name_to_time(event)]
        elif isinstance(event, list):
            events = [self.latest_event_cn if e == 'recent' else self.event_name_to_time(e) for e in event]
        else:
            logger.warning('Wrong Event format')
            events = []

        for aired_date, event in tqdm(zip(dates, events)):
            self.update_readme(aired_date, event)
            self.update_campaign_files(event)
            self.update_directory(event)
            self.reset()

    def run(self):
        """执行作战档案更新、配置定义生成与模板配置同步。"""
        self.war_archives_update(aired_date=self.aired_date, event=self.event)
        ConfigGenerator().generate()
        ConfigUpdater().update_file('template', is_template=True)


if __name__ == '__main__':
    # 作战档案更新上线日期
    # 输入 YYYYMMDD 格式的字符串，支持 'today' 表示今天，或列表传入多个值
    # 如 '20250717', 'today', ['20250619', '20250717', 'today']
    WarArchivesUpdater.aired_date = '20250717'
    # 活动名称或活动更新日期
    # 输入 YYYYMMDD 格式的字符串或活动名称
    # 'recent' 表示国服最新活动，也可传入列表同时处理多个
    # 如 '20220428', '虹彩的终幕曲', 'recent', ['雄鹰的叙事歌', '20220428', 'recent']
    WarArchivesUpdater.event = '20220428'

    updater = WarArchivesUpdater()

    # 确保在 AzurPilot 根目录运行
    os.chdir(os.path.join(os.path.dirname(__file__), '../'))
    updater.run()

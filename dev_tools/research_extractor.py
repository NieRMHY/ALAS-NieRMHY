from module.logger import logger  # Change folder automatically
from dev_tools.utils import LuaLoader


class Item:
    """科研消耗或产出道具封装类。

    Attributes:
        name (str): 道具名称。
        id (int): 道具 ID。
        amount (int): 道具数量。
    """

    def __init__(self, data):
        """解析道具数据元组或字典。

        Args:
            data (dict): 包含类型、道具 ID 与数量的字典，例如 {0: 2, 1: 20001, 2: 5}。
        """
        self.name = ''
        _, self.id, self.amount = data.values()
        if self.id == 1:
            self.id = 59001  # 金币在 technology_data_template 中的 ID 为 1，但在 item_data_statistics 中为 59001

    def __str__(self):
        return f'{self.name}({self.id}) x {self.amount}'


class Task:
    """科研任务条件封装类。

    Attributes:
        name (str): 任务描述名称。
        id (int): 任务 ID。
    """

    def __init__(self, data):
        """初始化科研任务条件。

        Args:
            data (int): 任务 ID。
        """
        self.name = ''
        self.id = data


class Project:
    """科研项目封装类。

    Attributes:
        name (str): 项目代号（如 'D-044-MI'）。
        series (int): 科研期数。
        time (int): 项目耗时（秒）。
        input (list[Item]): 消耗道具列表。
        output (list[Item]): 产出道具列表。
        task (Task): 附带任务条件。
    """

    def __init__(self, data):
        """解析科研项目原始配置。

        Args:
            data (dict): 来自 technology_data_template.lua 的单项配置字典。
        """
        self.name = data['name']
        self.series = int(data['blueprint_version'])
        self.time = int(data['time'])
        self.input = [Item(item) for item in data['consume'].values()]
        self.output = [Item(item) for item in data['drop_client'].values()]
        self.task = Task(int(data['condition']))

    def encode(self):
        """将项目信息转换为字典字符串。

        Returns:
            str: 项目字典的字符串表示。
        """
        data = {
            'name': self.name,
            'series': self.series,
            'time': self.time,
            'task': self.task.name,
            'input': [{'name': item.name, 'amount': item.amount} for item in self.input],
            'output': [{'name': item.name} for item in self.output],
        }
        return str(data)


# 键：中文名称，值：英文对照
DIC_TRANSLATION = {
    '蓝图：安克雷奇': 'Blueprint - Anchorage',
    '蓝图：{namecode:204}': 'Blueprint - Hakuryuu',
    '蓝图：埃吉尔': 'Blueprint - Ägir',
    '蓝图：奥古斯特·冯·帕塞瓦尔': 'Blueprint - August von Parseval',
    '蓝图：马可波罗': 'Blueprint - Marco Polo',
    '蓝图：瓦尔帕莱索': 'Blueprint - Valparaíso',
    '蓝图：{namecode:565}': 'Blueprint - Max Immelmann',
    '蓝图：邓肯': 'Blueprint - Duncan',
    '蓝图：{namecode:313}': 'Blueprint - Takahashi',
    '蓝图：暴风雨': 'Blueprint - Orage',
}


def set_translation(cn, en):
    """记录中英文对照翻译映射。

    Args:
        cn (str): 中文文本。
        en (str): 英文翻译文本。
    """
    if len(cn) and len(en):
        if cn not in DIC_TRANSLATION:
            DIC_TRANSLATION[cn] = en


class TechnologyTemplate:
    """科研项目配置提取器。

    Attributes:
        projects (dict[tuple[int, str], Project]): (期数, 项目代号) 映射的科研项目字典。
    """

    def __init__(self):
        """初始化提取器并加载国服与美服项目数据进行双语映射。"""
        self.projects = self.load_projects(LuaLoader(FOLDER, server='zh-CN'))
        en_projects = self.load_projects(LuaLoader(FOLDER, server='en-US'))

        for key, project in self.projects.items():
            if key not in en_projects:
                continue
            en_project = en_projects[key]
            set_translation(cn=project.task.name, en=en_project.task.name)
            for item, en_item in zip(project.input, en_project.input):
                set_translation(cn=item.name, en=en_item.name)
            for item, en_item in zip(project.output, en_project.output):
                set_translation(cn=item.name, en=en_item.name)

        for project in self.projects.values():
            project.task.name = DIC_TRANSLATION.get(project.task.name, project.task.name)
            for item in project.input:
                # 规范化特殊字符，如 Ägir -> Agir, Valparaíso -> Valparaiso
                item.name = DIC_TRANSLATION.get(item.name, item.name).replace('Ä', 'A').replace('í', 'i')
            for item in project.output:
                item.name = DIC_TRANSLATION.get(item.name, item.name).replace('Ä', 'A').replace('í', 'i')

    def load_projects(self, loader):
        """从指定语言的 Lua 数据中加载科研项目。

        Args:
            loader (LuaLoader): Lua 数据加载器。

        Returns:
            dict[tuple[int, str], Project]: 解析后的项目映射字典。
        """
        tech = loader.load('sharecfg/technology_data_template.lua')
        item = loader.load('sharecfgdata/item_data_statistics.lua')
        virtual_item = loader.load('sharecfgdata/item_virtual_data_statistics.lua')
        item.update(virtual_item)
        task = loader.load('sharecfgdata/task_data_template.lua')

        projects = {}
        for key, value in tech.items():
            if key == 'all':
                continue
            project = Project(value)
            if project.task.id:
                project.task.name = task[project.task.id]['desc'].replace('\\n', '')
            for i in project.input:
                i.name = item[i.id]['name'].strip()
            for i in project.output:
                i.name = item[i.id]['name'].strip()

            key = (project.series, project.name)
            if key not in projects:
                projects[key] = project

        return projects

    def encode(self):
        """将科研项目列表格式化为 Python 代码行列表。

        Returns:
            list[str]: 格式化后的代码行列表。
        """
        lines = []
        lines.append('# This file was automatically generated by dev_tools/research_extractor.py.')
        lines.append("# Don't modify it manually.")
        lines.append('')
        lines.append('LIST_RESEARCH_PROJECT = [')
        for project in self.projects.values():
            lines.append('    ' + project.encode() + ',')
        lines.append(']')

        return lines

    def write(self, file):
        """将科研项目数据写入目标文件。

        Args:
            file (str): 目标输出文件路径。
        """
        print(f'writing {file}')
        with open(file, 'w', encoding='utf-8') as f:
            for text in self.encode():
                f.write(text + '\n')


"""
Alas 科研项目数据自动化提取工具。

克隆 https://github.com/AzurLaneTools/AzurLaneLuaScripts 获取解密脚本。
参数说明：
    FILE:  解密 Lua 脚本仓库路径，例如 '<your_folder>/AzurLaneData'。
    SAVE:  输出保存文件路径，默认为 'module/research/project_data.py'。
"""
FOLDER = '../AzurLaneLuaScripts'
SAVE = 'module/research/project_data.py'

TechnologyTemplate().write(SAVE)

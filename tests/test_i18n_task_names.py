"""任务显示名翻译完整性测试（Add by MHY）。

背景：任务导航用的是 Task.<任务名>.name，配置生成器只给它写占位符
（值为键路径本身，如 "Task.IslandSeasonPlan.name"）。前端 t() 发现值与键相同
就回退显示键名末段，于是界面上出现英文的 IslandSeasonPlan。真机踩过一次：
只补了 <任务>._info.name，漏了 Task.<任务>.name，界面仍是英文。
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, '.')

ROOT = Path(__file__).resolve().parents[1]
# Modify by MHY, 移除喵语（MIAO）中文语言包（nanoda 傲娇风格）
LANGUAGES = ('zh-CN', 'en-US', 'ja-JP', 'zh-TW')


def menu_tasks():
    """从 menu.json 收集所有任务名（含嵌套分组）。"""
    menu = json.loads((ROOT / 'module/config/argument/menu.json').read_text(encoding='utf-8'))
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == 'tasks' and isinstance(value, list):
                    found.extend(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(menu)
    return sorted(set(found))


class TestTaskDisplayNames(unittest.TestCase):
    def test_menu_has_tasks(self):
        self.assertGreater(len(menu_tasks()), 50)

    def test_every_task_has_display_name(self):
        """菜单里每个任务在五种语言下都要有真实显示名，不能是占位符"""
        tasks = menu_tasks()
        problems = []
        for language in LANGUAGES:
            path = ROOT / 'module/config/i18n' / f'{language}.json'
            translations = json.loads(path.read_text(encoding='utf-8')).get('Task', {})
            for task in tasks:
                name = (translations.get(task) or {}).get('name')
                if not name or name == f'Task.{task}.name':
                    problems.append(f'{language}: {task}')
        self.assertEqual(problems, [],
                         '以下任务缺显示名（界面会回退显示英文任务名）：\n' + '\n'.join(problems))


if __name__ == '__main__':
    unittest.main()

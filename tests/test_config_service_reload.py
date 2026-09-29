"""配置服务元数据自动重载测试（Add by MHY）。

背景：更新链路替换 args.json/menu.json/i18n 后，运行中的 WebUI 仍用启动时的
快照，新增任务与配置项必须重启 gui.py 才可见（真机踩过：任务名回退成
IslandSeasonPlan、任务页提示「此任务没有独立配置」）。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, '.')

from module.api.config_service import ConfigService


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def touch_newer(path):
    """把 mtime 往前推，避免同秒写入导致 mtime 相同。"""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns + 10 ** 9, stat.st_mtime_ns + 10 ** 9))


class TestMetadataReload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.argument = self.root / 'module/config/argument'
        self.i18n = self.root / 'module/config/i18n'
        (self.root / 'config').mkdir(parents=True, exist_ok=True)
        write_json(self.argument / 'args.json', {'NewTask': {'Group': {'Arg': {'type': 'input'}}}})
        write_json(self.argument / 'menu.json', {'Island': {'tasks': ['NewTask']}})
        write_json(self.i18n / 'zh-CN.json', {'NewTask': {'_info': {'name': '旧名字'}}})
        write_json(self.root / 'config/template.json', {})
        self.service = ConfigService(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_translation_updated_without_restart(self):
        self.assertEqual(self.service.translate('NewTask._info.name'), '旧名字')
        path = self.i18n / 'zh-CN.json'
        write_json(path, {'NewTask': {'_info': {'name': '新名字'}}})
        touch_newer(path)
        self.assertEqual(self.service.translate('NewTask._info.name'), '新名字')

    def test_schema_picks_up_new_task(self):
        self.assertIn('NewTask', self.service.schema()['args'])
        path = self.argument / 'args.json'
        write_json(path, {'NewTask': {'Group': {'Arg': {'type': 'input'}}},
                          'Added': {'Group': {'Arg': {'type': 'input'}}}})
        touch_newer(path)
        self.assertIn('Added', self.service.schema()['args'])

    def test_menu_picks_up_new_task(self):
        self.assertEqual(self.service.schema()['menu']['Island']['tasks'], ['NewTask'])
        path = self.argument / 'menu.json'
        write_json(path, {'Island': {'tasks': ['NewTask', 'Added']}})
        touch_newer(path)
        self.assertEqual(self.service.schema()['menu']['Island']['tasks'], ['NewTask', 'Added'])

    def test_in_memory_override_survives(self):
        """调用方就地改 args 做临时覆盖时不能被自动重载冲掉（MCP 测试依赖此语义）"""
        self.service.args['NewTask']['Group']['Arg']['display'] = 'readonly'
        self.service.reload_metadata_if_stale()
        self.assertEqual(self.service.args['NewTask']['Group']['Arg']['display'], 'readonly')

    def test_broken_file_keeps_previous_metadata(self):
        """更新写入过程中的半成品文件不能让接口崩掉"""
        path = self.i18n / 'zh-CN.json'
        path.write_text('{ 坏文件', encoding='utf-8')
        touch_newer(path)
        self.assertEqual(self.service.translate('NewTask._info.name'), '旧名字')


if __name__ == '__main__':
    unittest.main()

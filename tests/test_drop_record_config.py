"""掉落记录配置：只保留本地能力，不引入云端上报，原 AzurStats 线路选项保持可用。

存档与统计是两件事：`save` / `save_and_upload` 决定要不要把截图落盘，
科研只要不是 `do_not` 就解析入库，大世界掉落同理。云端上报、`DropRecord_CloudUpload`
总开关和 `cloud_upload.py` 在本地分支已整体移除，这里用配置表与 `AzurStats.new()`
的行为把这个边界固定下来，避免下次合并上游时被悄悄带回来。
"""

import importlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import yaml

from module.config.config_generated import GeneratedConfig
from module.config.redirect_utils.utils import OPSI_RECORD_ARGS
from module.statistics.azurstats import AzurStats

ROOT = Path(__file__).resolve().parents[1]
RECORD_OPTIONS = ['do_not', 'save', 'upload', 'save_and_upload']
# 只保存本地截图的场景，选项比其他场景少两档。
SAVE_ONLY_OPTIONS = ['do_not', 'save']
LANGUAGES = ('zh-CN', 'zh-TW', 'en-US', 'ja-JP')


def load_argument_yaml():
    """读取配置源文件；生成产物（args.json 等）由 config_updater 维护，不作为断言依据。"""
    path = ROOT / 'module/config/argument/argument.yaml'
    return yaml.safe_load(path.read_text(encoding='utf-8'))['DropRecord']


def load_template():
    path = ROOT / 'config/template.json'
    return json.loads(path.read_text(encoding='utf-8'))['Alas']['DropRecord']


def make_config(**overrides):
    """构造只带掉落配置的最小 config，避免读取真实用户配置。"""
    values = {
        'config_name': 'isolated',
        'DropRecord_ResearchRecord': 'do_not',
        'DropRecord_CommissionRecord': 'do_not',
        'DropRecord_SaveFolder': './screenshots',
        'DropRecord_RetentionDays': 0,
        'DropRecord_BackUpMethod': 'zip',
        'DropRecord_ZipMethod': 'zip',
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def new_drop(genre, method, **overrides):
    """按当前本地配置创建一次掉落记录，清理节流在测试里直接屏蔽。"""
    with patch('module.statistics.azurstats.cleanup_drop_screenshots_if_due'):
        return AzurStats(make_config()).new(genre, method=method, **overrides)


class DropRecordSchemaTest(unittest.TestCase):
    def test_cloud_upload_gate_is_gone_from_every_layer(self):
        self.assertNotIn('CloudUpload', load_argument_yaml())
        self.assertNotIn('CloudUpload', load_template())
        self.assertFalse(hasattr(GeneratedConfig, 'DropRecord_CloudUpload'))
        for language in LANGUAGES:
            path = ROOT / f'module/config/i18n/{language}.json'
            self.assertNotIn('CloudUpload', json.loads(path.read_text(encoding='utf-8'))['DropRecord'])

    def test_cloud_upload_module_is_not_importable(self):
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module('module.statistics.cloud_upload')

    def test_azurstats_line_options_are_kept(self):
        """原 AzurStats 的线路选择与客户端 ID 仍是用户可改的配置项。"""
        arguments = load_argument_yaml()
        self.assertEqual(arguments['API']['value'], 'default')
        self.assertEqual(arguments['API']['option'], ['default', 'cn_gz_reverse_proxy'])
        self.assertIn('AzurStatsID', arguments)
        self.assertEqual(GeneratedConfig.DropRecord_API, 'default')
        self.assertEqual(load_template()['API'], 'default')

    def test_research_and_commission_keep_all_four_modes(self):
        arguments = load_argument_yaml()
        for name in ('ResearchRecord', 'CommissionRecord'):
            with self.subTest(name=name):
                self.assertEqual(arguments[name]['value'], 'do_not')
                self.assertEqual(sorted(arguments[name]['option']), sorted(RECORD_OPTIONS))
                self.assertEqual(getattr(GeneratedConfig, f'DropRecord_{name}'), 'do_not')
                self.assertEqual(load_template()[name], 'do_not')

    def test_opsi_records_keep_parsing_defaults(self):
        arguments = load_argument_yaml()
        for name in OPSI_RECORD_ARGS:
            with self.subTest(name=name):
                self.assertEqual(arguments[name]['value'], 'upload')
                self.assertEqual(sorted(arguments[name]['option']), sorted(RECORD_OPTIONS))
                self.assertEqual(getattr(GeneratedConfig, f'DropRecord_{name}'), 'upload')
                self.assertEqual(load_template()[name], 'upload')

    def test_screenshot_only_scenes_stay_two_valued(self):
        arguments = load_argument_yaml()
        for name in ('CombatRecord', 'MeowfficerBuy'):
            with self.subTest(name=name):
                self.assertEqual(arguments[name]['value'], 'do_not')
                self.assertEqual(sorted(arguments[name]['option']), sorted(SAVE_ONLY_OPTIONS))

    def test_i18n_covers_the_local_modes(self):
        words = json.loads((ROOT / 'module/config/i18n/zh-CN.json').read_text(encoding='utf-8'))['DropRecord']
        for name in ('ResearchRecord', 'CommissionRecord', *OPSI_RECORD_ARGS):
            with self.subTest(name=name):
                for option in RECORD_OPTIONS:
                    self.assertIn(option, words[name])


class DropRecordBehaviourTest(unittest.TestCase):
    def test_local_collection_matrix(self):
        """`save` 只决定落盘；`local` / `analyze` 才是本地统计开关。"""
        cases = (
            # genre, method, save, local, analyze
            ('research', 'do_not', False, False, False),
            ('research', 'save', True, False, True),
            ('research', 'upload', False, False, True),
            ('research', 'save_and_upload', True, False, True),
            ('commission', 'do_not', False, False, False),
            ('commission', 'save', True, False, False),
            ('commission', 'upload', False, False, False),
            ('opsi_abyssal', 'do_not', False, False, False),
            ('opsi_abyssal', 'save', True, True, False),
            ('opsi_abyssal', 'upload', False, True, False),
            ('opsi_hazard1_leveling', 'upload', False, False, False),
        )
        for genre, method, save, local, analyze in cases:
            with self.subTest(genre=genre, method=method):
                drop = new_drop(genre, method)
                self.assertEqual(drop.save, save)
                self.assertEqual(drop.local, local)
                self.assertEqual(drop.analyze, analyze)
                self.assertEqual(bool(drop), save or local or analyze)

    def test_drop_image_has_no_cloud_state(self):
        drop = new_drop('research', 'upload')
        for attribute in ('upload', 'cloud_capture_valid', 'collected_at', '_commission_kind'):
            with self.subTest(attribute=attribute):
                self.assertFalse(hasattr(drop, attribute))

    def test_research_commit_reports_only_local_identity(self):
        """科研入库只传实例与截图名，没有云端配置或采集时间。"""
        drop = new_drop('research', 'upload')
        drop.add(np.zeros((720, 1280, 3), np.uint8))
        with patch('module.statistics.research_drop.record_research_drop') as record, \
                patch('module.statistics.azurstats.pack') as pack:
            drop.__exit__(None, None, None)
        self.assertFalse(pack.called, '不存图也不入明细库时不应拼接截图')
        record.assert_called_once()
        self.assertEqual(record.call_args.kwargs['instance'], 'isolated')
        self.assertNotIn('config', record.call_args.kwargs)
        self.assertNotIn('collected_at', record.call_args.kwargs)

    def test_saved_screenshot_still_packs_the_frames(self):
        """选了保存就要真的拼接截图并交给后台线程，不能因为去掉云端就少存图。"""
        # 显式关掉本地解析：这里只验证存图分支，不加载大世界场景模板。
        drop = new_drop('opsi_abyssal', 'save', local=False)
        drop.add(np.zeros((720, 1280, 3), np.uint8))
        with patch('module.statistics.azurstats.pack', return_value='packed') as pack, \
                patch('module.statistics.azurstats.threading.Thread') as thread:
            drop.__exit__(None, None, None)
        self.assertTrue(pack.called)
        self.assertEqual(thread.call_args.kwargs['args'][0], 'packed')
        self.assertEqual(thread.call_args.kwargs['target'].__name__, '_save')


class ResearchListArchiveTest(unittest.TestCase):
    def archive_call(self, method):
        from module.research.selector import ResearchSelector
        selector = SimpleNamespace(
            config=SimpleNamespace(DropRecord_ResearchRecord=method),
            stat=MagicMock(),
            device=SimpleNamespace(image='frame'),
        )
        ResearchSelector.research_list_archive(selector)
        return selector.stat.new.call_args

    def test_selection_list_is_archived_only_when_screenshots_are_saved(self):
        for method in ('save', 'save_and_upload'):
            with self.subTest(method=method):
                call = self.archive_call(method)
                self.assertIsNotNone(call)
                self.assertEqual(call.args, ('research_refresh',))
                self.assertEqual(call.kwargs, {'method': method})

    def test_no_archive_without_screenshot_saving(self):
        for method in ('do_not', 'upload'):
            with self.subTest(method=method):
                self.assertIsNone(self.archive_call(method))


if __name__ == '__main__':
    unittest.main()

"""验证掉落记录截图的保留天数清理策略。

只跑纯文件系统逻辑：临时目录里造出截图文件并改写修改时间，
`DropRecord_SaveFolder` 与委托收益截图目录都指向临时目录，
不依赖模拟器、也不碰真实截图。
"""

import os
import shutil
import tempfile
import time
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.statistics import drop_cleanup


class DropCleanupTestCase(unittest.TestCase):
    """准备临时目录，并隔离模块级节流缓存与截图目录常量。"""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='drop_cleanup_test_')
        self.save_folder = os.path.join(self.root, 'screenshots')
        self.commission_folder = os.path.join(self.root, 'commission_rewards')
        os.makedirs(self.save_folder)
        os.makedirs(self.commission_folder)

        self._saved_cleanup = drop_cleanup._LAST_CLEANUP
        # 避免测试过程中真的去扫日志目录
        drop_cleanup._LAST_CLEANUP = float('inf')
        self._patch = patch.object(
            drop_cleanup, 'COMMISSION_REWARD_FOLDER', self.commission_folder)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        drop_cleanup._LAST_CLEANUP = self._saved_cleanup
        shutil.rmtree(self.root, ignore_errors=True)

    def config(self, days=0, instance='alas', folder=None,
               method='delete', zip_method='zip'):
        """构造只带掉落记录相关字段的配置对象。

        method 默认 delete，让不关心处理方式的用例保持「过期即删除」的旧断言；
        生产默认值是配置里的 zip，由 TestBackupMethods 覆盖。
        """
        return SimpleNamespace(
            DropRecord_SaveFolder=self.save_folder if folder is None else folder,
            DropRecord_RetentionDays=days,
            DropRecord_BackUpMethod=method,
            DropRecord_ZipMethod=zip_method,
            config_name=instance,
        )

    def make_file(self, path, age_seconds):
        """按给定年龄写出文件，返回其路径。"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(b'x')
        mtime = time.time() - age_seconds
        os.utime(path, (mtime, mtime))
        return path

    def drop_image(self, name, age_seconds):
        """造一个掉落截图：文件名是 13 位毫秒时间戳。"""
        return self.make_file(
            os.path.join(self.save_folder, 'commission', name), age_seconds)

    def reward_image(self, name, age_seconds, instance='alas'):
        """造一个委托收益截图：文件名是保存时间戳，落在月份目录下。"""
        return self.make_file(
            os.path.join(
                self.commission_folder, instance, '2020-01', name),
            age_seconds)


class TestRetentionSetting(DropCleanupTestCase):
    def test_days_is_read_from_config(self):
        self.assertEqual(
            drop_cleanup.drop_screenshot_retention_days(
                self.config(7)), 7)

    def test_numeric_string_is_accepted(self):
        self.assertEqual(
            drop_cleanup.drop_screenshot_retention_days(
                self.config('30')), 30)

    def test_missing_setting_keeps_everything(self):
        # 老配置里没有这一项时按「不清理」处理
        self.assertEqual(
            drop_cleanup.drop_screenshot_retention_days(SimpleNamespace()), 0)

    def test_invalid_setting_keeps_everything(self):
        self.assertEqual(
            drop_cleanup.drop_screenshot_retention_days(
                self.config('abc')), 0)


class TestCleanupDropScreenshots(DropCleanupTestCase):
    def test_zero_retention_keeps_screenshots(self):
        old = self.drop_image('1704067200000.png', 400 * 86400)
        self.assertEqual(
            drop_cleanup.cleanup_drop_screenshots(self.config(0), 0), 0)
        self.assertTrue(os.path.exists(old))

    def test_removes_expired_drop_screenshots(self):
        old = self.drop_image('1704067200000.png', 8 * 86400)
        old_with_info = self.drop_image('1704067200001_13-4.png', 8 * 86400)
        fresh = self.drop_image('1799999999999.png', 60)

        self.assertEqual(
            drop_cleanup.cleanup_drop_screenshots(self.config(7), 7), 2)
        self.assertFalse(os.path.exists(old))
        self.assertFalse(os.path.exists(old_with_info))
        self.assertTrue(os.path.exists(fresh))

    def test_keeps_files_that_are_not_ours(self):
        """模板、说明文件等非掉落截图不能被误删。"""
        template = self.make_file(
            os.path.join(self.save_folder, 'item_templates', '主炮.png'),
            400 * 86400)
        note = self.make_file(
            os.path.join(self.save_folder, 'readme.txt'), 400 * 86400)
        # 名字像截图但扩展名不对的也要留着
        other = self.make_file(
            os.path.join(self.save_folder, 'commission', '1704067200000.txt'),
            400 * 86400)

        self.assertEqual(
            drop_cleanup.cleanup_drop_screenshots(self.config(1), 1), 0)
        self.assertTrue(os.path.exists(template))
        self.assertTrue(os.path.exists(note))
        self.assertTrue(os.path.exists(other))

    def test_only_current_instance_rewards_are_cleaned(self):
        mine = self.reward_image('20200101_000000_000000_0.png', 8 * 86400)
        others = self.reward_image(
            '20200101_000000_000000_0.png', 8 * 86400, instance='other')

        self.assertEqual(
            drop_cleanup.cleanup_drop_screenshots(self.config(7), 7), 1)
        self.assertFalse(os.path.exists(mine))
        # 另一个实例的保留天数可能不同，交给它自己清理
        self.assertTrue(os.path.exists(others))

    def test_empty_month_folder_is_removed(self):
        self.reward_image('20200101_000000_000000_0.png', 8 * 86400)
        month = os.path.join(self.commission_folder, 'alas', '2020-01')
        self.assertTrue(os.path.isdir(month))

        drop_cleanup.cleanup_drop_screenshots(self.config(7), 7)
        self.assertFalse(os.path.exists(month))
        # 实例根目录要留着，下次保存还要往里写
        self.assertTrue(
            os.path.isdir(os.path.join(self.commission_folder, 'alas')))

    def test_missing_directories_are_safe(self):
        config = self.config(
            7, folder=os.path.join(self.root, 'not_created_yet'))
        self.assertEqual(drop_cleanup.cleanup_drop_screenshots(config, 7), 0)

    def test_missing_instance_name_is_safe(self):
        config = self.config(7)
        del config.config_name
        self.assertEqual(drop_cleanup.cleanup_drop_screenshots(config, 7), 0)


class TestBackupMethods(DropCleanupTestCase):
    """过期截图的处理方式：删除 / 拷贝备份 / 压缩备份。"""

    def bak_files(self, folder=None):
        bak = os.path.join(self.save_folder if folder is None else folder, 'bak')
        return sorted(os.listdir(bak)) if os.path.isdir(bak) else []

    def test_delete_removes_expired_screenshots(self):
        old = self.drop_image('1704067200000.png', 8 * 86400)
        config = self.config(7, method='delete')

        self.assertEqual(drop_cleanup.cleanup_drop_screenshots(config, 7), 1)
        self.assertFalse(os.path.exists(old))
        self.assertEqual(self.bak_files(), [])

    def test_copy_keeps_backup(self):
        old = self.drop_image('1704067200000.png', 8 * 86400)
        config = self.config(7, method='copy')

        self.assertEqual(drop_cleanup.cleanup_drop_screenshots(config, 7), 1)
        self.assertFalse(os.path.exists(old))
        self.assertEqual(self.bak_files(), ['1704067200000.png'])

    def test_zip_keeps_archive(self):
        old = self.drop_image('1704067200000.png', 8 * 86400)
        config = self.config(7, method='zip')

        self.assertEqual(drop_cleanup.cleanup_drop_screenshots(config, 7), 1)
        self.assertFalse(os.path.exists(old))
        names = self.bak_files()
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].endswith('_commission.zip'), names[0])
        with zipfile.ZipFile(
                os.path.join(self.save_folder, 'bak', names[0])) as z:
            self.assertEqual(z.namelist(), ['1704067200000.png'])

    def test_invalid_config_values_fall_back_to_zip_backup(self):
        """处理方式/压缩格式非法时按默认的压缩备份处理。"""
        old = self.drop_image('1704067200000.png', 8 * 86400)
        config = self.config(7, method='shred', zip_method='rar')

        self.assertEqual(drop_cleanup.cleanup_drop_screenshots(config, 7), 1)
        self.assertFalse(os.path.exists(old))
        names = self.bak_files()
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].endswith('.zip'), names[0])

    def test_backup_folder_is_never_cleaned(self):
        """bak 里的备份不能被当成过期内容重复处理。"""
        bak = os.path.join(self.save_folder, 'bak')
        os.makedirs(bak)
        backup = self.make_file(
            os.path.join(bak, '1704067200000.png'), 400 * 86400)

        config = self.config(1, method='delete')
        self.assertEqual(drop_cleanup.cleanup_drop_screenshots(config, 1), 0)
        self.assertTrue(os.path.exists(backup))

    def test_commission_rewards_go_to_instance_bak(self):
        reward = self.reward_image('20200101_000000_000000_0.png', 8 * 86400)
        config = self.config(7, method='zip')

        self.assertEqual(drop_cleanup.cleanup_drop_screenshots(config, 7), 1)
        self.assertFalse(os.path.exists(reward))
        names = self.bak_files(os.path.join(self.commission_folder, 'alas'))
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].endswith('_alas_2020-01.zip'), names[0])


class TestCleanupIfDue(DropCleanupTestCase):
    def setUp(self):
        super().setUp()
        drop_cleanup._LAST_CLEANUP = 0.0  # 让首次调用一定执行清理

    def test_uses_configured_retention_days(self):
        old = self.drop_image('1704067200000.png', 3 * 86400)
        self.assertEqual(
            drop_cleanup.cleanup_drop_screenshots_if_due(self.config(1)), 1)
        self.assertFalse(os.path.exists(old))

    def test_disabled_setting_does_not_scan(self):
        kept = self.drop_image('1704067200000.png', 400 * 86400)
        self.assertEqual(
            drop_cleanup.cleanup_drop_screenshots_if_due(self.config(0)), 0)
        self.assertTrue(os.path.exists(kept))

    def test_second_call_is_throttled(self):
        self.drop_image('1704067200000.png', 3 * 86400)
        self.assertEqual(
            drop_cleanup.cleanup_drop_screenshots_if_due(self.config(1)), 1)

        still_there = self.drop_image('1704067200001.png', 3 * 86400)
        # 节流期内不再扫描，文件仍然留着
        self.assertEqual(
            drop_cleanup.cleanup_drop_screenshots_if_due(self.config(1)), 0)
        self.assertTrue(os.path.exists(still_there))

    def test_invalid_setting_does_not_delete(self):
        kept = self.drop_image('1704067200000.png', 400 * 86400)
        self.assertEqual(
            drop_cleanup.cleanup_drop_screenshots_if_due(self.config('abc')), 0)
        self.assertTrue(os.path.exists(kept))


class TestDropRecordWiring(unittest.TestCase):
    """掉落记录提交时会顺带触发清理。"""

    def test_new_triggers_cleanup(self):
        from module.statistics import azurstats

        stat = azurstats.AzurStats(
            config=SimpleNamespace(DropRecord_RetentionDays=7))
        with patch.object(
            azurstats, 'cleanup_drop_screenshots_if_due'
        ) as cleanup:
            stat.new('commission', method='do_not')

        cleanup.assert_called_once_with(stat.config)


class TestCommissionScreenshotSwitch(unittest.TestCase):
    """委托收益截图开关与保留天数的联动（直接驱动 RewardCommission 的方法）。"""

    def make_commission(self, method, retention=0):
        return SimpleNamespace(
            config=SimpleNamespace(
                DropRecord_CommissionIncomeScreenshot=method,
                DropRecord_RetentionDays=retention,
            ),
            # 张数上限的裁剪方法，用假对象记录是否被调用
            _prune_commission_reward_screenshots=Mock(),
        )

    def save(self, fake):
        """调用保存方法（重定向掉落盘）：返回路径列表与 save_image 的假实现。"""
        from module.commission.commission import RewardCommission

        with patch('os.makedirs'), \
                patch('module.commission.commission.save_image') as save:
            paths = RewardCommission._save_commission_reward_screenshots(
                fake, [object()], 'alas')
        return paths, save

    def test_disabled_switch_skips_saving(self):
        fake = self.make_commission('do_not')
        paths, save = self.save(fake)

        self.assertEqual(paths, [])
        save.assert_not_called()
        fake._prune_commission_reward_screenshots.assert_not_called()

    def test_retention_days_replaces_count_cap(self):
        fake = self.make_commission('save', retention=7)
        paths, _ = self.save(fake)

        self.assertEqual(len(paths), 1)
        fake._prune_commission_reward_screenshots.assert_not_called()

    def test_default_keeps_count_cap(self):
        fake = self.make_commission('save', retention=0)
        self.save(fake)

        fake._prune_commission_reward_screenshots.assert_called_once_with('alas')


class TestCommissionCountCapSkipsBackup(unittest.TestCase):
    """张数兜底（未填保留天数时）不能把 bak 里的备份算进去或删掉。"""

    def make_base(self):
        root = tempfile.mkdtemp(prefix='commission_prune_')
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return os.path.join(root, 'alas')

    def prune(self, base, max_keep):
        from module.commission.commission import RewardCommission

        RewardCommission._prune_commission_reward_screenshots(
            'alas', max_keep=max_keep, base=base)

    def test_backup_folder_is_ignored(self):
        base = self.make_base()
        bak = os.path.join(base, 'bak')
        os.makedirs(bak)
        backup = os.path.join(bak, '20200101_000000_000000_0.png')
        with open(backup, 'wb') as f:
            f.write(b'x')

        # max_keep=0 时若不跳过 bak，备份会被算作超量并删掉
        self.prune(base, max_keep=0)

        self.assertTrue(os.path.isfile(backup))
        self.assertTrue(os.path.isdir(bak))

    def test_normal_screenshots_still_pruned(self):
        base = self.make_base()
        month = os.path.join(base, '2020-01')
        os.makedirs(month)
        for name in ('20200101_000000_000000_0.png', '20200102_000000_000000_0.png'):
            with open(os.path.join(month, name), 'wb') as f:
                f.write(b'x')

        self.prune(base, max_keep=1)

        self.assertEqual(len(os.listdir(month)), 1)
        self.assertTrue(os.path.isdir(base))


class TestConfigWiring(unittest.TestCase):
    """用真实配置对象校验键名与取值口径。

    上面的用例都用 SimpleNamespace 假配置，键名写错也会静默回落默认值；
    这一组走真实的 config_update + bind，确保配置项真的叫这些名字。
    """

    def make_config(self, **groups):
        """按 tests/test_backup.py 的既有手法在内存里构造配置。"""
        from module.config.config import AzurLaneConfig

        config = AzurLaneConfig('template')
        config.auto_update = False
        config.data = config.config_update({'Alas': groups})
        config.bind('Alas')
        return config

    def test_defaults_match_argument_definition(self):
        config = self.make_config()

        self.assertEqual(config.DropRecord_RetentionDays, 0)
        self.assertEqual(config.DropRecord_BackUpMethod, 'zip')
        self.assertEqual(config.DropRecord_ZipMethod, 'zip')
        self.assertEqual(config.Error_SaveErrorRetentionDays, 30)
        self.assertEqual(config.Error_SaveErrorBackUpMethod, 'zip')
        self.assertEqual(config.Error_SaveErrorZipMethod, 'zip')

    def test_old_config_is_filled_with_new_defaults(self):
        """存量配置没有这几项时应补成默认值，而不是读不到。"""
        config = self.make_config(DropRecord={'SaveFolder': './screenshots'})

        self.assertEqual(config.DropRecord_BackUpMethod, 'zip')
        self.assertEqual(config.Error_SaveErrorRetentionDays, 30)

    def test_cleanup_reads_values_from_real_config(self):
        root = tempfile.mkdtemp(prefix='drop_wiring_')
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        folder = os.path.join(root, 'screenshots')
        genre = os.path.join(folder, 'commission')
        os.makedirs(genre)
        old = os.path.join(genre, '1704067200000.png')
        with open(old, 'wb') as f:
            f.write(b'x')
        stale = time.time() - 8 * 86400
        os.utime(old, (stale, stale))

        config = self.make_config(DropRecord={
            'SaveFolder': folder,
            'RetentionDays': 7,
            'BackUpMethod': 'zip',
            'ZipMethod': 'zip',
        })

        with patch.object(
                drop_cleanup, 'COMMISSION_REWARD_FOLDER',
                os.path.join(root, 'commission_rewards')):
            self.assertEqual(
                drop_cleanup.cleanup_drop_screenshots(config, 7), 1)

        self.assertFalse(os.path.exists(old))
        names = os.listdir(os.path.join(folder, 'bak'))
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].endswith('_commission.zip'), names[0])


if __name__ == '__main__':
    unittest.main()

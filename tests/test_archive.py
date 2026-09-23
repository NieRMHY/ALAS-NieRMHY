"""验证过期条目的三种处理方式：删除 / 拷贝备份 / 压缩备份。"""

import os
import shutil
import tarfile
import tempfile
import time
import unittest
import zipfile
from types import SimpleNamespace

from module.base import archive


class ArchiveTestCase(unittest.TestCase):
    """在临时目录里造出过期文件与目录，隔离真实路径。"""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='archive_test_')
        self.bak = os.path.join(self.root, 'bak')

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make_file(self, name, content=b'x', age_seconds=0):
        """按给定年龄写出文件（name 可含子目录），返回其路径。"""
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(content)
        if age_seconds:
            mtime = time.time() - age_seconds
            os.utime(path, (mtime, mtime))
        return path

    def make_folder(self, name, files=('log.txt',)):
        """造一个含若干文件的目录，返回其路径。"""
        folder = os.path.join(self.root, name)
        os.makedirs(folder, exist_ok=True)
        for file in files:
            with open(os.path.join(folder, file), 'w', encoding='utf-8') as f:
                f.write('x')
        return folder


class TestReadConfig(ArchiveTestCase):
    def test_days_from_config(self):
        self.assertEqual(archive.read_days(SimpleNamespace(A=7), 'A'), 7)
        self.assertEqual(archive.read_days(SimpleNamespace(A='30'), 'A'), 30)

    def test_bad_days_fall_back_to_disabled(self):
        self.assertEqual(archive.read_days(SimpleNamespace(), 'A'), 0)
        self.assertEqual(archive.read_days(SimpleNamespace(A='abc'), 'A'), 0)
        self.assertEqual(archive.read_days(SimpleNamespace(A=None), 'A'), 0)

    def test_method_defaults_on_invalid_value(self):
        self.assertEqual(
            archive.read_method(SimpleNamespace(A='zip'), 'A', 'delete'), 'zip')
        self.assertEqual(
            archive.read_method(SimpleNamespace(A='nope'), 'A', 'delete'), 'delete')
        self.assertEqual(
            archive.read_method(SimpleNamespace(), 'A', 'delete'), 'delete')

    def test_zip_method_defaults_on_invalid_value(self):
        self.assertEqual(
            archive.read_zip_method(SimpleNamespace(A='bz2'), 'A', 'zip'), 'bz2')
        self.assertEqual(
            archive.read_zip_method(SimpleNamespace(A='rar'), 'A', 'zip'), 'zip')


class TestDelete(ArchiveTestCase):
    def test_files_and_folders_are_removed(self):
        file = self.make_file('a.png')
        folder = self.make_folder('1704067200000')

        self.assertEqual(
            archive.expire([file, folder], self.bak, 'delete', 'zip', 'alas'), 2)
        self.assertFalse(os.path.exists(file))
        self.assertFalse(os.path.exists(folder))
        # 删除方式不创建备份目录
        self.assertFalse(os.path.exists(self.bak))


class TestCopyBackup(ArchiveTestCase):
    def test_files_are_copied_then_removed(self):
        file = self.make_file('a.png', b'hello')

        self.assertEqual(archive.expire([file], self.bak, 'copy', 'zip', 'alas'), 1)
        self.assertFalse(os.path.exists(file))
        with open(os.path.join(self.bak, 'a.png'), 'rb') as f:
            self.assertEqual(f.read(), b'hello')

    def test_folders_are_copied_then_removed(self):
        folder = self.make_folder('1704067200000', files=('log.txt', '1.png'))

        self.assertEqual(archive.expire([folder], self.bak, 'copy', 'zip', 'alas'), 1)
        self.assertFalse(os.path.exists(folder))
        self.assertTrue(
            os.path.isfile(os.path.join(self.bak, '1704067200000', 'log.txt')))

    def test_existing_backup_is_not_overwritten(self):
        """重名备份保留先到的那份，不覆盖。"""
        with open(os.path.join(self.root, 'a.png'), 'wb') as f:
            f.write(b'old')
        os.makedirs(self.bak)
        with open(os.path.join(self.bak, 'a.png'), 'wb') as f:
            f.write(b'keep')

        file = self.make_file('a.png', b'new')
        self.assertEqual(archive.expire([file], self.bak, 'copy', 'zip', 'alas'), 1)
        with open(os.path.join(self.bak, 'a.png'), 'rb') as f:
            self.assertEqual(f.read(), b'keep')


class TestZipBackup(ArchiveTestCase):
    def test_files_are_archived_then_removed(self):
        first = self.make_file('a.png', b'aaa', age_seconds=3 * 86400)
        second = self.make_file('b.png', b'bbb', age_seconds=86400)

        self.assertEqual(
            archive.expire([first, second], self.bak, 'zip', 'zip', 'commission'), 2)
        self.assertFalse(os.path.exists(first))
        self.assertFalse(os.path.exists(second))

        names = os.listdir(self.bak)
        self.assertEqual(len(names), 1)
        # 命名规则：<最早日期>~<最晚日期>_<来源标识>.zip
        old_date = time.strftime(
            '%Y-%m-%d', time.localtime(time.time() - 3 * 86400))
        self.assertTrue(names[0].startswith(f'{old_date}~'), names[0])
        self.assertTrue(names[0].endswith('_commission.zip'), names[0])
        with zipfile.ZipFile(os.path.join(self.bak, names[0])) as z:
            self.assertEqual(sorted(z.namelist()), ['a.png', 'b.png'])

    def test_folder_is_archived_with_its_files(self):
        folder = self.make_folder('1704067200000', files=('log.txt',))

        self.assertEqual(archive.expire([folder], self.bak, 'zip', 'zip', 'alas'), 1)
        self.assertFalse(os.path.exists(folder))
        name = os.listdir(self.bak)[0]
        with zipfile.ZipFile(os.path.join(self.bak, name)) as z:
            self.assertEqual(z.namelist(), ['1704067200000/log.txt'])

    def test_tar_formats(self):
        cases = (
            ('bz2', '.tar.bz2'),
            ('gzip', '.tar.gz'),
            ('xz', '.tar.xz'),
        )
        for zip_method, suffix in cases:
            with self.subTest(zip_method=zip_method):
                bak = os.path.join(self.root, f'bak_{zip_method}')
                file = self.make_file(f'{zip_method}.png', b'x')

                self.assertEqual(
                    archive.expire([file], bak, 'zip', zip_method, 'x'), 1)
                name = os.listdir(bak)[0]
                self.assertTrue(name.endswith(suffix), name)
                with tarfile.open(os.path.join(bak, name)) as tar:
                    self.assertEqual(tar.getnames(), [f'{zip_method}.png'])

    def test_same_name_does_not_overwrite_existing_archive(self):
        for index in range(2):
            file = self.make_file(f'{index}.png', b'x')
            self.assertEqual(
                archive.expire([file], self.bak, 'zip', 'zip', 'commission'), 1)
        self.assertEqual(len(os.listdir(self.bak)), 2)


class TestSafety(ArchiveTestCase):
    def test_paths_inside_backup_folder_are_skipped(self):
        """备份目录里的内容不能再被处理（拷贝会保留原修改时间）。"""
        file = self.make_file(os.path.join('bak', 'a.png'), b'hello')

        self.assertEqual(archive.expire([file], self.bak, 'delete', 'zip', 'alas'), 0)
        self.assertTrue(os.path.exists(file))

    def test_empty_list_is_noop(self):
        self.assertEqual(archive.expire([], self.bak, 'zip', 'zip', 'alas'), 0)
        self.assertFalse(os.path.exists(self.bak))

    def test_unknown_method_falls_back_to_delete(self):
        file = self.make_file('a.png')
        self.assertEqual(archive.expire([file], self.bak, 'shred', 'zip', 'alas'), 1)
        self.assertFalse(os.path.exists(file))

    def test_unusable_backup_folder_keeps_originals(self):
        """备份目录不可用时保留原条目，不做删除。"""
        with open(self.bak, 'w', encoding='utf-8') as f:  # bak 被占成普通文件
            f.write('x')
        file = self.make_file('a.png')

        self.assertEqual(archive.expire([file], self.bak, 'zip', 'zip', 'alas'), 0)
        self.assertTrue(os.path.exists(file))

    def test_no_stray_placeholder_after_archive(self):
        """取名字用的占位文件会被真正的压缩包取代。"""
        file = self.make_file('a.png')
        self.assertEqual(archive.expire([file], self.bak, 'zip', 'zip', 'alas'), 1)

        names = os.listdir(self.bak)
        self.assertEqual(len(names), 1)
        with zipfile.ZipFile(os.path.join(self.bak, names[0])) as z:
            self.assertEqual(z.namelist(), ['a.png'])

    def test_unreadable_path_does_not_break_the_rest(self):
        """单个条目失败不中断整轮清理。"""
        missing = os.path.join(self.root, 'not_exists.png')
        file = self.make_file('a.png')

        self.assertEqual(
            archive.expire([missing, file], self.bak, 'delete', 'zip', 'alas'), 1)
        self.assertFalse(os.path.exists(file))


if __name__ == '__main__':
    unittest.main()

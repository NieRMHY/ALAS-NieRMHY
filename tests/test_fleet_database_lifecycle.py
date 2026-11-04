"""Instance lifecycle preserves fleet backups without adopting another instance's data."""
import json
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from module.api.config_service import ConfigService, ROOT
from module.api.protocol import ApiError
from module.runtime.fleet_database import FleetDatabase
from tests.platform_capabilities import supports_symlinks


class FleetDatabaseLifecycleTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for relative in ('module/config/argument/args.json', 'module/config/argument/menu.json',
                         'module/config/i18n/zh-CN.json', 'config/template.json'):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        self.configs = ConfigService(root)
        self.configs.create('pilot')
        self.database = FleetDatabase(self.configs.path('pilot'))
        from module.runtime import dock_data, fleet_tech
        self.database.patch_technology([dict(group_type=10102, owned=True)], {'1': 3},
            fleet_tech.revision(dock_data.technology_record(self.database.load())))
        self.database.patch_cards([dict(name='杜威', group_type=10102, level=100, review=True)],
                                  dock_data.read_snapshot(self.database.load())['revision'])

    def test_delete_archives_sqlite_and_json_and_recreation_is_empty(self):
        self.configs.delete('pilot', self.configs.read('pilot')[1])
        backup = self.configs.directory / 'backup'
        json_backup, = backup.glob('*.json')
        fleet_backup, = backup.glob('*.fleet.sqlite3')
        self.assertEqual(fleet_backup.name, f'{json_backup.stem}.fleet.sqlite3')
        self.assertIn('Alas', json.loads(json_backup.read_text(encoding='utf-8')))
        with closing(sqlite3.connect(fleet_backup)) as connection:
            self.assertEqual(connection.execute(
                "SELECT owned FROM technology_progress WHERE group_type='10102'").fetchone()[0], 1)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM ships WHERE review=1").fetchone()[0], 1)
        self.assertFalse(self.database.path.exists())
        self.configs.create('pilot')
        self.assertEqual(self.database.load(), {'snapshot': None, 'technology': {}, 'pending_revision': None})
        self.assertFalse(self.database.path.exists())

    def test_clone_configuration_does_not_copy_fleet_records(self):
        self.configs.create('clone', source='pilot')
        clone = FleetDatabase(self.configs.path('clone'))
        self.assertEqual(clone.load(), {'snapshot': None, 'technology': {}, 'pending_revision': None})
        self.assertFalse(clone.path.exists())
        self.assertTrue(self.database.load()['technology']['progress']['10102']['owned'])

    def test_create_refuses_orphan_database_without_changing_it(self):
        self.configs.path('pilot').unlink()
        original = self.database.path.read_bytes()
        with self.assertRaises(ApiError) as error:
            self.configs.create('pilot')
        self.assertEqual(error.exception.code, 'ALREADY_EXISTS')
        self.assertEqual(self.database.path.read_bytes(), original)
        self.assertFalse(self.configs.path('pilot', exists=False).exists())

    def test_failed_config_unlink_restores_database(self):
        path = self.configs.path('pilot')
        original = self.database.load()
        unlink = Path.unlink

        def fail_config_delete(target, *args, **kwargs):
            if target == path:
                raise PermissionError('blocked config deletion')
            return unlink(target, *args, **kwargs)

        with patch.object(Path, 'unlink', fail_config_delete):
            with self.assertRaises(PermissionError):
                self.configs.delete('pilot', self.configs.read('pilot')[1])
        self.assertTrue(path.exists())
        self.assertEqual(self.database.load(), original)
        self.assertFalse(list((self.configs.directory / 'backup').glob('*.fleet.sqlite3')))

    def test_failed_fleet_archive_does_not_remove_scheduler_or_config(self):
        original = self.database.load()
        replace = Path.replace

        def fail_fleet_archive(path, *args, **kwargs):
            if path == self.database.path:
                raise PermissionError('blocked fleet backup')
            return replace(path, *args, **kwargs)

        with patch.object(Path, 'replace', fail_fleet_archive), \
                patch('module.scheduler.store.ProgramStore.archive') as archive:
            with self.assertRaises(PermissionError):
                self.configs.delete('pilot', self.configs.read('pilot')[1])
        archive.assert_not_called()
        self.assertTrue(self.configs.path('pilot').exists())
        self.assertEqual(self.database.load(), original)

    def test_failed_program_archive_restores_fleet_database(self):
        original = self.database.load()
        with patch('module.scheduler.store.ProgramStore.archive', side_effect=OSError('blocked program backup')):
            with self.assertRaises(OSError):
                self.configs.delete('pilot', self.configs.read('pilot')[1])
        self.assertTrue(self.configs.path('pilot').exists())
        self.assertEqual(self.database.load(), original)
        self.assertFalse(list((self.configs.directory / 'backup').glob('*.fleet.sqlite3')))

    @unittest.skipUnless(supports_symlinks(), 'OS does not grant symbolic-link creation privileges')
    def test_delete_refuses_database_symlink_and_preserves_config(self):
        original = self.database.path.with_suffix('.original')
        self.database.path.replace(original)
        self.database.path.symlink_to(original)
        with patch('module.scheduler.store.ProgramStore.archive') as archive:
            with self.assertRaises(ValueError):
                self.configs.delete('pilot', self.configs.read('pilot')[1])
        archive.assert_not_called()
        self.assertTrue(self.configs.path('pilot').exists())
        self.assertTrue(original.exists())
        self.assertTrue(self.database.path.is_symlink())

    def test_waiting_api_writer_cannot_recreate_deleted_database(self):
        from module.api.fleet_tech_service import FleetTechService
        from module.api.dock_service import DockService

        for kind in ('dock', 'technology'):
            with self.subTest(kind=kind):
                if not self.configs.path('pilot', exists=False).exists():
                    self.configs.create('pilot')
                service = DockService(self.configs) if kind == 'dock' else FleetTechService(self.configs)
                report = service.report('pilot')
                checked = threading.Event()
                failures = []
                path = self.configs.path
                parent = threading.get_ident()

                def observe_path(*args, **kwargs):
                    value = path(*args, **kwargs)
                    if threading.get_ident() != parent:
                        checked.set()
                    return value

                def write():
                    try:
                        if kind == 'dock':
                            service.patch('pilot', report['revision'], [dict(name='拉菲', level=100)])
                        else:
                            service.patch('pilot', report['revision'], [], {'1': 2})
                    except BaseException as exc:
                        failures.append(exc)

                with patch.object(self.configs, 'path', observe_path):
                    with self.configs.lock:
                        worker = threading.Thread(target=write)
                        worker.start()
                        self.assertTrue(checked.wait(timeout=5))
                        self.configs.delete('pilot', self.configs.read('pilot')[1])
                    worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(len(failures), 1)
                self.assertIsInstance(failures[0], ApiError)
                self.assertEqual(failures[0].code, 'NOT_FOUND')
                self.assertFalse(self.database.path.exists())

"""大世界掉落截图开关按任务取值的回归。

背景：原先只有一个 `Alas.DropRecord.OpsiRecord` 管着所有大世界任务的掉落截图，
现在拆成 8 个开关——侵蚀1练级、耄耋相接、大世界每日、隐秘海域、深渊海域、
塞壬要塞、每月开荒各一个，`OpsiOther` 兜底没列出的任务。跨月每日跟大世界每日、
档案坐标跟隐秘海域、月度Boss跟深渊海域共用开关，共用只影响存图与否，掉落统计
仍按各自的 genre 归类。这里锁定四件事：旧配置迁移时旧值被铺给每个新开关、
运行期按当前任务取到该读的开关（含共用）、没列出的任务落到 `OpsiOther`、
共用任务不占独立开关。耄耋相接的开关还必须在 `upload` 档位继续打开本地解析
——统计页的短猫收益靠它。
"""

import unittest

import inflection

from module.config.config import AzurLaneConfig, Function
from module.config.config_generated import GeneratedConfig
from module.config.config_updater import ConfigUpdater
from module.config.redirect_utils.utils import OPSI_RECORD_ARGS, opsi_record_redirect
from module.config.deep import deep_get
from module.config.utils import filepath_args, read_file
from module.os.config import OPSI_DROP_RECORD_SHARED, OPSI_DROP_RECORD_TASKS, opsi_drop_record
from module.statistics.azurstats import AzurStats


class FakeConfigTestCase(unittest.TestCase):
    """用真实的 bind() 造配置对象，不落盘、不连游戏。"""

    def make_config(self, task, values=None):
        """造一个绑定了 `task` 的配置，DropRecord 组的取值由 `values` 指定。

        Args:
            task (str): 当前任务名，会成为 `config.task.command`。
            values (dict): DropRecord 组下要覆盖的取值，其余开关按 do_not 填。

        Returns:
            AzurLaneConfig: 只填了 DropRecord 与 Scheduler.Command 的配置对象。
        """
        record = {arg: 'do_not' for arg in OPSI_RECORD_ARGS}
        record.update(values or {})
        record['RetentionDays'] = 0

        config = AzurLaneConfig.__new__(AzurLaneConfig)
        config.bound = {}
        config.modified = {}
        config.overridden = {}
        config.auto_update = False
        config.data = {
            'Alas': {'DropRecord': record, 'Scheduler': {'Command': 'Alas'}},
        }
        if task != 'Alas':
            config.data[task] = {'Scheduler': {'Command': task}}
        config.task = Function(config.data[task])
        config.bind(config.task)
        return config


class TestOpsiRecordRedirect(unittest.TestCase):
    def test_old_value_is_copied_to_every_switch(self):
        """旧值是什么，7 个新开关就都是什么，不添不改。"""
        for value in ('do_not', 'save', 'upload', 'save_and_upload'):
            with self.subTest(value=value):
                self.assertEqual(
                    list(opsi_record_redirect(value)), [value] * len(OPSI_RECORD_ARGS))

    def test_switches_exist_and_old_argument_is_gone(self):
        """改名要成套：7 个新开关都得进参数定义和生成类，旧键不能再留。"""
        args = read_file(filepath_args())['Alas']['DropRecord']
        for arg in OPSI_RECORD_ARGS:
            with self.subTest(arg=arg):
                self.assertIn(arg, args)
                self.assertTrue(hasattr(GeneratedConfig, f'DropRecord_{arg}'))
        self.assertNotIn('OpsiRecord', args)

    def test_config_redirect_fans_out_stored_value(self):
        old = {'Alas': {'DropRecord': {'OpsiRecord': 'save_and_upload'}}}
        new = ConfigUpdater().config_redirect(old, {})
        for arg in OPSI_RECORD_ARGS:
            with self.subTest(arg=arg):
                self.assertEqual(deep_get(new, keys=f'Alas.DropRecord.{arg}'), 'save_and_upload')

    def test_config_redirect_keeps_values_already_migrated(self):
        """已经迁移过的配置再加载一次，用户改过的新开关不能被旧值覆盖回去。

        `config_redirect` 的既有语义是「目标已有值就不覆盖」，所以这里的 new
        要按 `config_update` 的实际形态带上老配置里已有的值。
        """
        old = {'Alas': {'DropRecord': {'OpsiRecord': 'upload', 'OpsiAbyssal': 'do_not'}}}
        new = {'Alas': {'DropRecord': {'OpsiAbyssal': 'do_not'}}}
        result = ConfigUpdater().config_redirect(old, new)
        self.assertEqual(deep_get(result, keys='Alas.DropRecord.OpsiAbyssal'), 'do_not')
        self.assertEqual(deep_get(result, keys='Alas.DropRecord.OpsiObscure'), 'upload')


class TestOpsiDropRecordLookup(FakeConfigTestCase):
    def test_each_task_reads_its_own_switch(self):
        values = {
            'OpsiHazard1Leveling': 'save',
            'OpsiMeowfficerFarming': 'save_and_upload',
            'OpsiDaily': 'do_not',
            'OpsiObscure': 'save',
            'OpsiAbyssal': 'upload',
            'OpsiStronghold': 'save',
            'OpsiExplore': 'save_and_upload',
        }
        for task, expect in values.items():
            with self.subTest(task=task):
                config = self.make_config(task, values)
                self.assertEqual(opsi_drop_record(config), expect)

    def test_shared_tasks_read_the_host_switch(self):
        """跨月每日跟大世界每日、档案坐标跟隐秘海域、月度Boss跟深渊坐标共用开关。"""
        values = {
            'OpsiDaily': 'save_and_upload',
            'OpsiObscure': 'save',
            'OpsiAbyssal': 'do_not',
        }
        for task, expect in (('OpsiCrossMonth', 'save_and_upload'),
                             ('OpsiArchive', 'save'),
                             ('OpsiMonthBoss', 'do_not')):
            with self.subTest(task=task):
                config = self.make_config(task, values)
                self.assertEqual(opsi_drop_record(config), expect)

    def test_unlisted_tasks_fall_back_to_other(self):
        """没列进任何一项的大世界任务走 OpsiOther。"""
        for task in ('OpsiScheduling', 'OpsiPreventActionPointOverflow', 'OpsiDaemon', 'Alas'):
            with self.subTest(task=task):
                config = self.make_config(task, {'OpsiOther': 'save'})
                self.assertEqual(opsi_drop_record(config), 'save')

    def test_task_list_matches_argument_names(self):
        """任务清单里的每个任务都要有同名开关，否则运行期读到的是生成类的默认值。"""
        args = read_file(filepath_args())['Alas']['DropRecord']
        for task in OPSI_DROP_RECORD_TASKS:
            with self.subTest(task=task):
                self.assertIn(task, args, f'{task} 没有对应的掉落截图开关')

    def test_shared_tasks_have_no_switch_of_their_own(self):
        """共用开关的任务不占单独一项，界面上只出现有独立开关的任务。"""
        args = read_file(filepath_args())['Alas']['DropRecord']
        for task in OPSI_DROP_RECORD_SHARED:
            with self.subTest(task=task):
                self.assertNotIn(task, args)


class TestMigrationThroughConfigUpdate(unittest.TestCase):
    """走真实的 config_update：旧配置里的单一开关要把 7 个新开关一起点亮。"""

    def make_config(self, old):
        """按 tests/test_drop_cleanup.py 的既有手法在内存里构造配置。"""
        config = AzurLaneConfig('template')
        config.auto_update = False
        config.data = config.config_update({'Alas': old})
        config.bind('Alas')
        return config

    def test_old_config_gets_every_switch(self):
        config = self.make_config({'DropRecord': {'OpsiRecord': 'save_and_upload'}})
        for arg in OPSI_RECORD_ARGS:
            with self.subTest(arg=arg):
                self.assertEqual(getattr(config, f'DropRecord_{arg}'), 'save_and_upload')

    def test_already_migrated_keys_keep_user_values(self):
        """迁移过的开关保持用户改过的值，只有还缺的那些由旧值补齐。

        实例先升到上一版、用户又改过几项，然后才升到本版时走的就是这条路。
        """
        config = self.make_config({'DropRecord': {
            'OpsiRecord': 'save',
            'OpsiAbyssal': 'do_not',
            'OpsiMeowfficerFarming': 'save_and_upload',
        }})
        self.assertEqual(config.DropRecord_OpsiAbyssal, 'do_not')
        self.assertEqual(config.DropRecord_OpsiMeowfficerFarming, 'save_and_upload')
        self.assertEqual(config.DropRecord_OpsiExplore, 'save')

    def test_old_config_keeps_other_drop_settings(self):
        config = self.make_config({'DropRecord': {'OpsiRecord': 'save', 'RetentionDays': 3}})
        self.assertEqual(config.DropRecord_RetentionDays, 3)
        self.assertEqual(config.DropRecord_CombatRecord, 'do_not')

    def test_fresh_config_falls_back_to_defaults(self):
        """全新配置没有旧键，7 个开关拿参数定义里的默认值。"""
        config = self.make_config({'DropRecord': {'RetentionDays': 3}})
        for arg in OPSI_RECORD_ARGS:
            with self.subTest(arg=arg):
                self.assertEqual(getattr(config, f'DropRecord_{arg}'), 'upload')


class TestMeowfficerStatisticsStayWired(FakeConfigTestCase):
    """短猫掉落截图这个开关就是掉落统计的数据源，档位语义不能漂移。

    2026-09-25 起改口径：除侵蚀1练级外的所有大世界任务都解析入库，
    且「保存」与「上传」都统计，区别只在要不要把截图落盘（与科研同口径）。
    """

    def test_method_matrix_drives_save_and_local(self):
        cases = (
            ('do_not', False, False),
            ('save', True, True),
            ('upload', False, True),
            ('save_and_upload', True, True),
        )
        for value, save, local in cases:
            with self.subTest(value=value):
                config = self.make_config(
                    'OpsiMeowfficerFarming', {'OpsiMeowfficerFarming': value})
                method = opsi_drop_record(config)
                self.assertEqual(method, value)
                drop = AzurStats(config).new('opsi_meowfficer_farming', method=method)
                self.assertIs(drop.save, save)
                self.assertIs(drop.local, local)
                self.assertIs(bool(drop), save or local)

    def test_other_tasks_are_recorded_too(self):
        """别的大世界任务同样入库：不再是「只对短猫相接生效」。"""
        for task in ('OpsiAbyssal', 'OpsiDaily', 'OpsiObscure', 'OpsiStronghold'):
            for value in ('save', 'upload'):
                with self.subTest(task=task, value=value):
                    config = self.make_config(task, {task: value})
                    method = opsi_drop_record(config)
                    drop = AzurStats(config).new(
                        inflection.underscore(task), method=method)
                    self.assertTrue(drop.local)
                    self.assertIs(drop.save, value == 'save')

    def test_hazard1_leveling_stays_out_of_drop_statistics(self):
        """侵蚀1练级不进掉落统计：任何档位都不解析，「保存」只落盘截图。"""
        config = self.make_config('OpsiHazard1Leveling', {'OpsiHazard1Leveling': 'upload'})
        drop = AzurStats(config).new('opsi_hazard1_leveling', method=opsi_drop_record(config))
        self.assertFalse(drop.save)
        self.assertFalse(drop.local)
        self.assertFalse(bool(drop))

        config = self.make_config('OpsiHazard1Leveling', {'OpsiHazard1Leveling': 'save'})
        drop = AzurStats(config).new('opsi_hazard1_leveling', method=opsi_drop_record(config))
        self.assertTrue(drop.save)
        self.assertFalse(drop.local)


if __name__ == '__main__':
    unittest.main()

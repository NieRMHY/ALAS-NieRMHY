"""智能调度代理隐秘、深渊和要塞时的行动力保留回归。"""

import unittest
from unittest.mock import patch

from module.config.config import AzurLaneConfig, Function, TaskEnd
from module.os.tasks.scheduling import OpsiScheduling
from module.os_handler.action_point import ActionPointLimit


class TestScheduledCoinTaskPreserve(unittest.TestCase):
    """保留真实配置绑定和代理上下文，仅替换游戏交互。"""

    TASK_METHODS = (
        ('OpsiObscure', 'clear_obscure'),
        ('OpsiAbyssal', 'clear_abyssal'),
        ('OpsiStronghold', 'clear_stronghold'),
    )

    def make_runner(self):
        runner = OpsiScheduling.__new__(OpsiScheduling)
        config = AzurLaneConfig.__new__(AzurLaneConfig)
        config.bound = {}
        config.modified = {}
        config.overridden = {}
        config.auto_update = False
        config.OS_ACTION_POINT_PRESERVE = 200
        config.data = {
            task_name: {'Scheduler': {'Command': task_name}}
            for task_name in ('OpsiScheduling', *(name for name, _ in self.TASK_METHODS))
        }
        config.task = Function(config.data['OpsiScheduling'])
        config.bind(config.task)
        runner.config = config
        return runner

    def assert_restored(self, runner, owner, bound):
        self.assertEqual(runner.config.OS_ACTION_POINT_PRESERVE, 200)
        self.assertIs(runner.config.task, owner)
        self.assertEqual(runner.config.bound, bound)
        self.assertFalse(runner.is_running_smart_scheduling_task())

    def test_fresh_child_read_honors_scheduling_preserve(self):
        # 决策读数高于保留值，子任务弹窗的更新读数已低于保留值时必须停止，
        # 不能沿用上次侵蚀 1 留在共享配置上的 200 行动力下限。
        for task_name, method_name in self.TASK_METHODS:
            with self.subTest(task=task_name):
                runner = self.make_runner()
                owner, bound = runner.config.task, dict(runner.config.bound)
                runner._action_point_current = 90
                runner._action_point_total = 990

                def clear_task():
                    self.assertEqual(runner.config.task.command, task_name)
                    self.assertTrue(runner.is_running_smart_scheduling_task())
                    runner.handle_action_point(None, None, cost=40)

                setattr(runner, method_name, clear_task)
                with (
                    patch.object(runner, '_is_in_action_point', return_value=True),
                    patch.object(runner, 'action_point_safe_get'),
                    patch.object(runner, 'action_point_quit') as quit_popup,
                ):
                    with self.assertRaises(ActionPointLimit) as caught:
                        runner._run_scheduled_coin_task_once(task_name, ap_preserve=1000)

                self.assertEqual(caught.exception.preserve, 1000)
                self.assertEqual(caught.exception.total, 990)
                quit_popup.assert_called_once_with()
                self.assert_restored(runner, owner, bound)

    def test_normal_and_no_content_returns_restore_preserve(self):
        for task_name, method_name in self.TASK_METHODS:
            for no_content in (False, True):
                with self.subTest(task=task_name, no_content=no_content):
                    runner = self.make_runner()
                    owner, bound = runner.config.task, dict(runner.config.bound)

                    def clear_task():
                        self.assertEqual(runner.config.OS_ACTION_POINT_PRESERVE, 1000)
                        if no_content:
                            runner._smart_scheduling_no_content_task = task_name

                    setattr(runner, method_name, clear_task)
                    result = runner._run_scheduled_coin_task_once(task_name, ap_preserve=1000)

                    self.assertEqual(result, not no_content)
                    self.assert_restored(runner, owner, bound)

    def test_task_end_and_failure_restore_preserve(self):
        for task_name, method_name in self.TASK_METHODS:
            for error in (TaskEnd('结束任务'), RuntimeError('游戏处理失败')):
                with self.subTest(task=task_name, error=type(error).__name__):
                    runner = self.make_runner()
                    owner, bound = runner.config.task, dict(runner.config.bound)

                    def clear_task():
                        self.assertEqual(runner.config.OS_ACTION_POINT_PRESERVE, 1000)
                        raise error

                    setattr(runner, method_name, clear_task)
                    with self.assertRaises(type(error)) as caught:
                        runner._run_scheduled_coin_task_once(task_name, ap_preserve=1000)

                    self.assertIs(caught.exception, error)
                    self.assert_restored(runner, owner, bound)

    def test_zero_preserve_is_applied_and_restored(self):
        for task_name, method_name in self.TASK_METHODS:
            with self.subTest(task=task_name):
                runner = self.make_runner()
                owner, bound = runner.config.task, dict(runner.config.bound)
                observed = []
                setattr(runner, method_name, lambda: observed.append(runner.config.OS_ACTION_POINT_PRESERVE))

                self.assertTrue(runner._run_scheduled_coin_task_once(task_name, ap_preserve=0))

                self.assertEqual(observed, [0])
                self.assert_restored(runner, owner, bound)


if __name__ == '__main__':
    unittest.main()

"""岛屿模块的静态健康检查（Add by MHY）。

CI 的 lint 命令是 ruff --select E9,F63,F7,F82 --ignore F821,F722 —— **F821（未定义
名字）被显式忽略**，所以「用了某个名字却没导入」「引用了别的函数的局部变量」这类
错误不会被 CI 拦住，只能等真机抛 NameError。真机已经踩过两次：

- island_season_plan.py 引用 _read_screen 的局部变量 offset → 每轮崩一次，
  触发重启游戏 + 报警邮件
- island_away_cook.py 写了 notify_title 却没导入 → 通知一触发就崩

这里对岛屿模块单独跑一次 F821，把这类问题挡在提交前。
"""
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, '.')

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ('module/island/', 'module/island_season_plan/')


class TestNoUndefinedNames(unittest.TestCase):
    def test_ruff_available(self):
        self.assertIsNotNone(shutil.which('ruff'),
                             '找不到 ruff，无法做未定义名字检查')

    def test_island_modules_have_no_undefined_names(self):
        ruff = shutil.which('ruff')
        if not ruff:
            self.skipTest('ruff 不可用')
        result = subprocess.run(
            [ruff, 'check', *TARGETS, '--select', 'F821', '--output-format', 'concise'],
            cwd=ROOT, capture_output=True, text=True,
        )
        # 无问题时 ruff 也会往 stdout 打印 "All checks passed!"，所以看返回码
        self.assertEqual(result.returncode, 0,
                         '岛屿模块存在未定义名字（真机会抛 NameError）：\n' + result.stdout)


if __name__ == '__main__':
    unittest.main()

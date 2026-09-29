"""推送标题格式统一测试（Add by MHY）。

邮件标题统一为 <实例名> [类别] 简介，例如 <ALAS> [警告] 敏感任务出错。
之前格式五花八门：ALAS <X> 警告 / AzurPilot <X> xxx / 裸中文标题 /
[ALAS <X>]xxx / DEBUG TEST <X>，混在一起分不清来源。
"""
import glob
import os
import sys
import unittest

sys.path.insert(0, '.')

from module.notify import notify_title

# 旧的标题写法（出现即视为回归）。
# 注意：[ALAS info] / [Alas info] 是大世界调度内部传给格式化函数的标记，
# 会在 module/os/tasks/scheduling.py 里被剥掉并套用统一格式，不算旧标题。
LEGACY_PATTERNS = ('ALAS <{', 'AzurPilot <{', 'DEBUG TEST <{', '[ALAS <{')


class TestNotifyTitle(unittest.TestCase):
    def test_format(self):
        self.assertEqual(notify_title('ALAS', '警告', '敏感任务出错'),
                         '<ALAS> [警告] 敏感任务出错')
        self.assertEqual(notify_title('ALAS', '岛屿', '赛季任务可以提交了'),
                         '<ALAS> [岛屿] 赛季任务可以提交了')

    def test_instance_name_embedded(self):
        """实例名要写进标题，多实例时能区分"""
        self.assertIn('<BOT2>', notify_title('BOT2', '好感', '已达阈值'))


class TestOpsiSchedulingFormat(unittest.TestCase):
    def test_formatter_strips_internal_prefix(self):
        """大世界调度的内部标记会被剥掉并套统一格式"""
        src = open('module/os/tasks/scheduling.py', encoding='utf-8').read()
        self.assertIn("notify_title(instance_name, '大世界'", src)
        self.assertNotIn('[ALAS <{instance_name}>]', src)


class TestNoLegacyTitles(unittest.TestCase):
    def test_codebase_uses_unified_title(self):
        """代码里不应再出现旧格式标题（新增通知一律走 notify_title）"""
        offenders = []
        paths = ['alas.py'] + glob.glob('module/**/*.py', recursive=True)
        for path in paths:
            if not os.path.isfile(path):
                continue
            with open(path, encoding='utf-8') as f:
                for line_no, line in enumerate(f, 1):
                    if 'title' not in line.lower():
                        continue
                    if path.endswith('notify/notify.py'):
                        continue
                    for pattern in LEGACY_PATTERNS:
                        if pattern in line:
                            offenders.append(f'{path}:{line_no} {line.strip()[:80]}')
        self.assertEqual(offenders, [],
                         '以下位置仍在使用旧标题格式，请改用 module.notify.notify_title：\n'
                         + '\n'.join(offenders))


if __name__ == '__main__':
    unittest.main()

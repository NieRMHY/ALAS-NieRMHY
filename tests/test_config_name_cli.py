"""调度器入口实例名解析回归。

`python alas.py [实例名]` 是 AUTO-MAS 等外部调度器按实例拉起调度器的契约入口，
错误参数必须快速失败而不是回退到默认实例，否则外部工具会悄悄跑错配置。
"""

import unittest
from unittest.mock import patch

from module.config.utils import DEFAULT_CONFIG_NAME, parse_config_name


class ParseConfigNameTests(unittest.TestCase):
    """以固定的实例列表校验参数解析，不依赖真实 config 目录。"""

    instances = ['ap', 'alas2', '茗', 'ap.fpy']

    def parse(self, argv):
        with patch(
            'module.config.utils.alas_instance', return_value=list(self.instances)
        ):
            return parse_config_name(argv)

    def test_no_argument_falls_back_to_default(self):
        self.assertEqual(self.parse([]), DEFAULT_CONFIG_NAME)

    def test_known_instance_is_returned(self):
        self.assertEqual(self.parse(['alas2']), 'alas2')
        self.assertEqual(self.parse(['茗']), '茗')

    def test_mod_instance_keeps_its_dot(self):
        self.assertEqual(self.parse(['ap.fpy']), 'ap.fpy')

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(self.parse(['  alas2  ']), 'alas2')

    def test_more_than_one_argument_is_rejected(self):
        with self.assertRaises(ValueError):
            self.parse(['ap', 'alas2'])

    def test_unknown_instance_is_rejected(self):
        with self.assertRaises(ValueError):
            self.parse(['not_an_instance'])

    def test_path_separators_are_rejected(self):
        for name in ['../ap', '..', '.', 'a/b', 'a\\b', 'C:ap', 'ap*']:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.parse([name])

    def test_empty_name_is_rejected(self):
        with self.assertRaises(ValueError):
            self.parse(['   '])

    def test_missing_config_directory_defers_to_oobe_check(self):
        with patch(
            'module.config.utils.alas_instance', side_effect=FileNotFoundError
        ):
            self.assertEqual(parse_config_name(['ap']), 'ap')


if __name__ == '__main__':
    unittest.main()

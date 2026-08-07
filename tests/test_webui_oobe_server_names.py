"""OOBE 服务器名称选项的回归测试。"""

import unittest

from module.webui.fake_pil_module import remove_fake_pil_module

# 此测试只验证纯辅助方法，移除可能由其他 WebUI 测试注入的伪 PIL 模块。
remove_fake_pil_module()

from module.webui.oobe import OOBEWizard


class TestOOBEServerNames(unittest.TestCase):
    """验证 OOBE 按地区展示的服务器名称。"""

    def setUp(self):
        # 不执行构造函数，避免读取部署配置或建立 PyWebIO 会话。
        self.wizard = object.__new__(OOBEWizard)

    def test_tw_server_names_include_all_servers_without_disabled_option(self):
        items = self.wizard._server_name_items_for_region("tw")

        self.assertEqual(
            [value for value, _, _ in items],
            ["tw-0", "tw-1", "tw-2", "tw-3", "tw-4"],
        )
        self.assertEqual(
            [label for _, label, _ in items],
            [
                "[TW] 珍珠港",
                "[TW] 珊瑚海",
                "[TW] 中途島",
                "[TW] 瓜達康納爾",
                "[TW] 雷伊泰灣",
            ],
        )
        self.assertNotIn("disabled", {value for value, _, _ in items})

    def test_tw_prefix_and_default_server_name(self):
        self.assertEqual(OOBEWizard._server_prefixes_for_region("tw"), ("tw",))
        self.assertEqual(self.wizard._default_server_name_for_region("tw"), "tw-0")

    def test_existing_region_prefixes_remain_unchanged(self):
        expected_prefixes = {
            "cn": ("cn_android", "cn_ios", "cn_channel"),
            "en": ("en",),
            "jp": ("jp",),
        }

        for region, prefixes in expected_prefixes.items():
            with self.subTest(region=region):
                self.assertEqual(OOBEWizard._server_prefixes_for_region(region), prefixes)


if __name__ == "__main__":
    unittest.main()

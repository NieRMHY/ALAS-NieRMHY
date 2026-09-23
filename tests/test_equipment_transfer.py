"""装备码跨任务交接、配置保护与卸装失败的回归。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import yaml

from module.campaign.gems_farming import GemsEquipmentHandler
from module.equipment.equipment_code import EMPTY_CODE, EquipmentCodeHandler
from module.exception import RequestHumanTakeover


# 仅用于无设备的流程测试，不代表实际游戏装备。
CV_CODE = 'MTExLzIyMi8zMzMvMC8wXDA='
DD_CODE = 'NDQ0LzU1NS82NjYvMC8wXDA='


def handler_with_store(store, ship='bogue'):
    handler = object.__new__(GemsEquipmentHandler)
    handler.config = SimpleNamespace(
        task=SimpleNamespace(command='ThreeOilLowCost'), Emulator_ControlMethod='minitouch',
        cross_get=lambda keys: store['raw'],
        cross_set=lambda keys, value: store.update(raw=value),
    )
    handler._code_enter = Mock()
    handler.current_ship = Mock(return_value=ship)
    handler._code_export = Mock(return_value=CV_CODE)
    handler._code_apply = Mock(return_value=True)
    return handler


class EquipmentTransferTests(unittest.TestCase):
    def test_saved_bogue_survives_task_recreation_and_equips_unconfigured_ranger(self):
        store = {'raw': 'bogue: null\nranger: null'}
        first = handler_with_store(store)
        self.assertTrue(first.code_clear())
        self.assertTrue(first.code_apply())
        # 与实际日志一致：切换任务后重新创建处理器，内存缓存已不存在。
        resumed = handler_with_store(store)
        self.assertIsNone(resumed.last_code)
        self.assertTrue(resumed.code_clear())
        resumed._code_export.assert_not_called()
        resumed.current_ship.return_value = 'ranger'
        self.assertTrue(resumed.code_apply())
        resumed._code_apply.assert_called_with(code=CV_CODE)
        self.assertIsNone(resumed.last_code)

    def test_each_clear_replaces_cache_and_target_scheme_has_priority(self):
        store = {'raw': yaml.safe_dump({'bogue': CV_CODE, 'ranger': DD_CODE, 'DD': DD_CODE})}
        handler = handler_with_store(store)
        handler.last_code = DD_CODE
        self.assertTrue(handler.code_clear())
        self.assertEqual(handler.last_code, CV_CODE)
        self.assertTrue(handler.code_apply(name='ranger'))
        handler._code_apply.assert_called_with(code=DD_CODE)
        self.assertIsNone(handler.last_code)
        self.assertTrue(handler.code_clear(name='DD'))
        self.assertEqual(handler.last_code, DD_CODE)

    def test_failed_clear_and_unsupported_control_discard_previous_cache(self):
        for supported in (True, False):
            handler = handler_with_store({'raw': yaml.safe_dump({'bogue': CV_CODE})})
            handler.last_code = DD_CODE
            handler.equipment_code_supported = Mock(return_value=supported)
            handler._code_apply.return_value = False
            self.assertFalse(handler.code_clear())
            self.assertIsNone(handler.last_code)
            if not supported:
                handler._code_enter.assert_not_called()

    def test_missing_or_invalid_export_never_clears_equipment(self):
        for value in (None, '', '   ', 123, [], 'invalid'):
            with self.subTest(value=value):
                handler = handler_with_store({'raw': ''})
                handler.last_code = DD_CODE
                handler._code_export.return_value = value
                self.assertFalse(handler.code_clear())
                handler._code_apply.assert_not_called()
                self.assertIsNone(handler.last_code)

    def test_save_failure_leaves_equipment_and_store_untouched(self):
        store = {'raw': 'ranger: null'}
        handler = handler_with_store(store)
        handler.config.cross_set = Mock(side_effect=OSError('只读文件系统'))
        self.assertFalse(handler.code_clear())
        handler._code_apply.assert_not_called()
        self.assertEqual(store['raw'], 'ranger: null')
        self.assertIsNone(handler.last_code)

    def test_invalid_yaml_or_document_shape_never_overwrites_other_schemes(self):
        for raw in ('bogue: [', 'bogue: ' + CV_CODE + '\n---\n- broken', '42', '[1, 2]'):
            with self.subTest(raw=raw):
                store = {'raw': raw}
                handler = handler_with_store(store)
                with self.assertRaises(RequestHumanTakeover):
                    handler.code_clear()
                handler._code_apply.assert_not_called()
                handler._code_export.assert_not_called()
                self.assertEqual(store['raw'], raw)

    def test_missing_blank_and_invalid_target_codes_use_current_transfer_only(self):
        for value in (None, '', '  ', 123, [], {}, 'invalid'):
            with self.subTest(value=value):
                handler = handler_with_store({'raw': yaml.safe_dump({'bogue': CV_CODE, 'ranger': value})})
                self.assertTrue(handler.code_clear())
                self.assertTrue(handler.code_apply(name='ranger'))
                handler._code_apply.assert_called_with(code=CV_CODE)
                handler._code_apply.reset_mock()
                self.assertFalse(handler.code_apply(name='ranger'))
                handler._code_apply.assert_not_called()

    def test_successful_export_preserves_other_configured_schemes(self):
        store = {'raw': yaml.safe_dump({'DD': DD_CODE, 'bogue': None})}
        handler = handler_with_store(store)
        self.assertTrue(handler.code_clear())
        self.assertEqual(yaml.safe_load(store['raw']), {'DD': DD_CODE, 'bogue': CV_CODE})

    def test_explicit_empty_code_remains_valid(self):
        handler = handler_with_store({'raw': yaml.safe_dump({'bogue': EMPTY_CODE})})
        self.assertTrue(handler.code_clear())
        self.assertTrue(handler.code_apply())
        handler._code_apply.assert_called_with(code=EMPTY_CODE)

    def test_export_timeout_does_not_reuse_clipboard(self):
        handler = object.__new__(EquipmentCodeHandler)
        handler.handle_info_bar = Mock()
        handler.set_fastinput_ime = Mock()
        handler.loop = Mock(return_value=iter(range(2)))
        handler.info_bar_count = Mock(return_value=0)
        handler.appear_then_click = Mock(return_value=True)
        handler._clipboard_get = Mock(return_value=DD_CODE)
        self.assertIsNone(handler._code_export())
        handler._clipboard_get.assert_not_called()
        handler.loop.return_value = iter(range(2))
        handler.info_bar_count.side_effect = [0, 1]
        self.assertEqual(handler._code_export(), DD_CODE)

    def test_generic_clear_without_export_keeps_original_behavior(self):
        handler = object.__new__(EquipmentCodeHandler)
        handler.config = SimpleNamespace(Emulator_ControlMethod='minitouch', EquipmentCode_ExportToConfig=False)
        handler._code_enter = Mock()
        handler.current_ship = Mock(return_value='DD')
        handler._code_export = Mock()
        handler._code_apply = Mock(return_value=True)
        handler.last_code = CV_CODE
        self.assertTrue(handler.code_clear())
        handler._code_export.assert_not_called()
        self.assertIsNone(handler.last_code)


if __name__ == '__main__':
    unittest.main()

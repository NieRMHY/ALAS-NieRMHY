"""强化保留普通航母的开关回归；使用模拟画面状态和临时配置，不连接游戏。"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.api.config_service import ConfigService, ROOT
from module.api.protocol import ApiError, ConfigChange
from module.config.config import AzurLaneConfig
from module.config.config_updater import ConfigUpdater
from module.retire.enhancement import (
    EMPTY_ENHANCE_SLOT_PLUS, ENHANCE_CONFIRM, EQUIP_CONFIRM, Enhancement,
)


class SingleCommonCVTests(unittest.TestCase):
    def run_choose(self, skip=True, keep_cv=True, second_empty=True, first_cv=True, empty=False,
                   swipe=False, ship_count=5):
        instance = Enhancement.__new__(Enhancement)
        instance.config = SimpleNamespace(
            Enhance_KeepCommonCV=skip,
            is_task_enabled=Mock(return_value=keep_cv),
            cross_get=Mock(return_value='any'),
        )
        instance.device = Mock(image=object(), click_record=[])
        instance.equip_side_navbar_ensure = Mock(return_value=True)
        instance.wait_until_appear = Mock()
        instance.appear_then_click = Mock(return_value=True)
        instance.appear = Mock(side_effect=lambda button, **kwargs: (
            button is EQUIP_CONFIRM
            and any(call.args[0] is ENHANCE_CONFIRM
                    for call in instance.appear_then_click.call_args_list)
        ))
        instance.info_bar_count = Mock(return_value=empty)
        instance.handle_popup_confirm = Mock(return_value=False)
        instance.equip_view_next = Mock(return_value=swipe)
        instance._enhance_get_deselect_cv = Mock(return_value=object() if first_cv else None)
        instance._enhance_deselect_cv = Mock()
        instance._enhance_confirm = Mock()
        with patch.object(EMPTY_ENHANCE_SLOT_PLUS, 'match', side_effect=lambda image, offset: (
            empty if offset == (20, 20) else second_empty
        )):
            result = instance._enhance_choose(ship_count=ship_count)
        return instance, result

    def test_enabled_skips_single_common_cv(self):
        instance, result = self.run_choose()
        self.assertEqual(result, (False, 5))
        instance.equip_view_next.assert_called_once()
        instance._enhance_confirm.assert_not_called()
        instance._enhance_deselect_cv.assert_not_called()

    def test_disabled_uses_single_common_cv(self):
        instance, result = self.run_choose(skip=False)
        self.assertEqual(result, (True, 5))
        instance._enhance_confirm.assert_called_once()
        instance._enhance_deselect_cv.assert_not_called()
        instance.equip_view_next.assert_not_called()

    def test_enabled_keeps_swipe_and_check_limit(self):
        instance, result = self.run_choose(swipe=True, ship_count=1)
        self.assertEqual(result, (False, 0))
        instance.equip_view_next.assert_called_once()
        instance._enhance_confirm.assert_not_called()

    def test_material_combinations_follow_preservation_setting(self):
        for skip in (True, False):
            for second_empty, first_cv in ((False, True), (True, False)):
                with self.subTest(skip=skip, second_empty=second_empty, first_cv=first_cv):
                    instance, result = self.run_choose(
                        skip=skip, second_empty=second_empty, first_cv=first_cv)
                    self.assertTrue(result[0])
                    if skip:
                        instance._enhance_deselect_cv.assert_called_once()
                    else:
                        instance._enhance_deselect_cv.assert_not_called()
                        instance._enhance_get_deselect_cv.assert_not_called()
                        instance.config.is_task_enabled.assert_not_called()

    def test_without_cv_preservation_uses_normal_enhancement(self):
        for skip in (True, False):
            with self.subTest(skip=skip):
                instance, result = self.run_choose(skip=skip, keep_cv=False)
                self.assertTrue(result[0])
                instance._enhance_get_deselect_cv.assert_not_called()
                instance._enhance_deselect_cv.assert_not_called()

    def test_empty_materials_still_fail(self):
        for skip in (True, False):
            with self.subTest(skip=skip):
                instance, result = self.run_choose(skip=skip, empty=True)
                self.assertFalse(result[0])
                instance._enhance_confirm.assert_not_called()
                instance.equip_view_next.assert_called_once()


class SingleCommonCVConfigTests(unittest.TestCase):
    def test_existing_config_defaults_to_enabled_and_preserves_false(self):
        updater = ConfigUpdater()
        for old, expected in (({}, True), ({'KeepCommonCV': False}, False)):
            with self.subTest(expected=expected):
                updated = updater.config_update({'General': {'Enhance': old}})
                self.assertIs(updated['General']['Enhance']['KeepCommonCV'], expected)

    def test_legacy_setting_migrates_without_overriding_new_setting(self):
        updater = ConfigUpdater()
        for old, expected in (
            ({'SkipSingleCommonCV': False}, False),
            ({'SkipSingleCommonCV': True}, True),
            ({'SkipSingleCommonCV': False, 'KeepCommonCV': True}, True),
            ({'SkipSingleCommonCV': True, 'KeepCommonCV': False}, False),
        ):
            with self.subTest(old=old):
                updated = updater.config_update({'General': {'Enhance': old}})
                self.assertIs(updated['General']['Enhance']['KeepCommonCV'], expected)
                self.assertNotIn('SkipSingleCommonCV', updated['General']['Enhance'])

    def test_webui_schema_save_and_runtime_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ('config/template.json', 'module/config/argument/args.json',
                             'module/config/argument/menu.json', 'module/config/i18n/zh-CN.json'):
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)
            shutil.copyfile(root / 'config/template.json', root / 'config/testpilot.json')
            service = ConfigService(root)
            field = service.schema()['args']['General']['Enhance']['KeepCommonCV']
            self.assertEqual(field['type'], 'checkbox')
            self.assertIs(field['value'], True)
            key = 'General.Enhance.KeepCommonCV'
            path = str(root / 'config/testpilot.json')
            legacy = json.loads(Path(path).read_text(encoding='utf-8'))
            legacy['General']['Enhance'].pop('KeepCommonCV')
            legacy['General']['Enhance']['SkipSingleCommonCV'] = False
            Path(path).write_text(json.dumps(legacy), encoding='utf-8')
            before = Path(path).read_bytes()
            self.assertIs(service.get('testpilot')['values']['General']['Enhance']['KeepCommonCV'], False)
            self.assertEqual(Path(path).read_bytes(), before)
            service.patch('testpilot', None, [ConfigChange(path=key, value=True)])
            self.assertIs(service.get('testpilot')['values']['General']['Enhance']['KeepCommonCV'], True)
            service.patch('testpilot', None, [ConfigChange(path=key, value=False)])
            self.assertIs(service.get('testpilot')['values']['General']['Enhance']['KeepCommonCV'], False)
            with self.assertRaises(ApiError):
                service.validate(key, 'false')
            with patch('module.config.config.filepath_config', return_value=path), patch(
                'module.config.config_updater.filepath_config', return_value=path
            ), patch.object(AzurLaneConfig, 'config_override'):
                config = AzurLaneConfig('testpilot', task='Main')
                self.assertIs(config.Enhance_KeepCommonCV, False)
                self.assertEqual(config.bound['Enhance_KeepCommonCV'], key)

    def test_all_translations_are_complete(self):
        for language in ('zh-CN', 'en-US', 'ja-JP', 'zh-TW'):
            with self.subTest(language=language):
                data = json.loads((ROOT / 'module/config/i18n' / f'{language}.json').read_text(encoding='utf-8'))
                field = data['Enhance']['KeepCommonCV']
                for text in field.values():
                    self.assertTrue(text)
                    self.assertNotIn('Enhance.KeepCommonCV.', text)

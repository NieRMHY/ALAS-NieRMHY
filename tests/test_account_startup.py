"""账号恢复与推荐游戏配置共用设备就绪后的启动流程，不接触真实模拟器。"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

from alas import AzurLaneAutoScript
from module.api.account_service import device_for, restore_worker
from module.api.protocol import ApiError
from module.device.app_control import AppControl
from module.device.device import Device
from module.exception import EmulatorNotRunningError, RequestHumanTakeover


class AccountStartupTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.device = Device.__new__(Device)
        self.device.config = SimpleNamespace(config_name='synthetic', Error_HandleError=True,
                                             Emulator_GameSettings=True, EmulatorInfo_Emulator='test',
                                             is_template_config=True, is_actual_task=False)
        self.device.package = 'com.bilibili.azurlane'
        self.device.serial = '127.0.0.1:16416'
        self.device.adb_binary = 'resolved-adb'
        self.device.stuck_record_clear = Mock()
        self.device.click_record_clear = Mock()
        self.restore = self.enterContext(patch('module.api.account_service.restore_worker',
                                              side_effect=lambda *args, **kwargs: self.events.append('restore')))
        self.settings = self.enterContext(patch('module.game_setting.player_prefs.apply_recommended_game_settings',
                                               side_effect=lambda *args, **kwargs: self.events.append('settings')))
        self.launch = self.enterContext(patch.object(AppControl, 'app_start',
                                                    side_effect=lambda: self.events.append('launch')))

    def test_scheduler_constructor_does_not_restore_or_initialize_device(self):
        script = AzurLaneAutoScript('synthetic')
        self.restore.assert_not_called()
        self.assertNotIn('device', script.__dict__)
        self.assertNotIn('config', script.__dict__)

    def test_cold_emulator_connects_before_restore_and_settings_and_launch(self):
        attempts = 0
        def connect(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            self.events.append('connect')
            if attempts == 1:
                raise EmulatorNotRunningError('合成离线')
        with patch('module.device.connection.Connection.__init__', side_effect=connect), \
                patch.object(Device, 'emulator_instance', new_callable=PropertyMock, return_value=object()), \
                patch.object(Device, 'emulator_start', side_effect=lambda **kwargs: self.events.append('emulator-start')), \
                patch.object(Device, 'screenshot_interval_set'), patch.object(Device, 'method_check'):
            Device.__init__(self.device, self.device.config)
        self.restore.assert_not_called()
        self.device.app_start()
        self.assertEqual(['connect', 'emulator-start', 'connect', 'restore', 'settings', 'launch'], self.events)
        self.restore.assert_called_once_with('synthetic', device=self.device)

    def test_each_game_start_restores_once_before_recommended_settings(self):
        self.device.app_start()
        self.device.app_start()
        self.assertEqual(['restore', 'settings', 'launch'] * 2, self.events)
        self.assertEqual(2, self.restore.call_count)

    def test_restore_still_runs_when_recommended_settings_are_disabled(self):
        self.device.config.Emulator_GameSettings = False
        self.device.app_start()
        self.assertEqual(['restore', 'launch'], self.events)
        self.settings.assert_not_called()

    def test_restore_failure_blocks_settings_and_game_launch(self):
        self.restore.side_effect = ApiError('ACCOUNT_DEVICE_FAILED', '合成故障')
        with self.assertRaises(ApiError):
            self.device.app_start()
        self.settings.assert_not_called()
        self.launch.assert_not_called()

    def test_disabled_app_control_never_restores(self):
        self.device.config.Error_HandleError = False
        with self.assertRaises(RequestHumanTakeover):
            self.device.app_start()
        self.restore.assert_not_called()

    def test_disabled_vault_does_not_create_account_adb_device(self):
        from module.api import account_service
        with patch.object(account_service, 'vault') as vault, \
                patch.object(account_service, 'device_for') as device:
            vault.startup_key.return_value = None
            restore_worker('synthetic', device=self.device)
        vault.restore.assert_not_called()
        device.assert_not_called()

    def test_restore_uses_connected_serial_and_adb_instead_of_configured_address(self):
        configs = Mock()
        configs.read.return_value = ({'Alas': {'Emulator': {'PackageName': 'com.bilibili.azurlane',
                                                         'Serial': 'configured-address'}}}, None)
        with patch('module.api.account_service.AccountDevice') as account_device:
            device_for(configs, 'synthetic', device=self.device)
        account_device.assert_called_once_with('127.0.0.1:16416', 'resolved-adb')

import os
import time

import numpy as np

# os.chdir('../')
print(os.getcwd())
import module.config.server as server

# 设置默认服务器为国服以防报错
server.server = 'cn'

from module.config.config import AzurLaneConfig
from module.device.device import Device


class EmulatorChecker(Device):
    """模拟器截图与点击性能压力测试工具。"""

    def stress_test(self):
        """循环执行截图并统计平均耗时与标准差。"""
        record = []
        count = 0
        self._screenshot_adb()
        while 1:
            t0 = time.time()
            self._screenshot_adb()
            # self._screenshot_uiautomator2()
            # self._screenshot_ascreencap()
            # self._click_adb(1270, 360)
            # self._click_uiautomator2(1270, 360)

            cost = time.time() - t0
            record.append(cost)
            count += 1
            print(count, np.round(np.mean(record), 3), np.round(np.std(record), 3))


class Config:
    SERIAL = '127.0.0.1:5555'
    # SERIAL = '127.0.0.1:62001'
    # SERIAL = '127.0.0.1:7555'
    # SERIAL = 'emulator-5554'
    # SERIAL = '127.0.0.1:21503'

    # 速度对比：aScreenCap >> uiautomator2 > ADB
    DEVICE_SCREENSHOT_METHOD = 'aScreenCap'  # 可选: ADB, uiautomator2, aScreenCap

    # 速度对比：uiautomator2 >> ADB
    DEVICE_CONTROL_METHOD = 'uiautomator2'  # 可选: ADB, uiautomator2


az = EmulatorChecker(AzurLaneConfig('template').merge(Config()))
az.stress_test()

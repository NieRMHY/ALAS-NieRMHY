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
    """模拟器与设备后端截图/点击性能压力测试工具。"""

    def _screenshot_azurpilot_android(self):
        """兼容别名：调用 azurpilot_android 特权桥截图。"""
        return self.screenshot_azurpilot_android()

    def _click_azurpilot_android(self, x, y):
        """兼容别名：调用 azurpilot_android 特权桥点击。"""
        return self.click_azurpilot_android(x, y)

    def stress_test(self, method=None, limit=0):
        """循环执行截图压力测试并统计平均耗时、标准差、FPS 与带宽吞吐。

        Args:
            method (str, optional): 待测试的截图方法名称。若为 None 则使用配置中的 Emulator_ScreenshotMethod。
            limit (int): 测试次数上限，0 表示无限循环。
        """
        record = []
        count = 0
        target_method = method or self.config.Emulator_ScreenshotMethod
        func = self.screenshot_methods.get(target_method, self.screenshot_adb)
        print(f'[*] 开始压测截图后端: {target_method} (limit={limit or "无限"})')

        # 预热首帧
        func()

        t_session_start = time.time()
        while 1:
            t0 = time.time()
            func()
            # 候选后端调用示例：
            # self._screenshot_adb()
            # self._screenshot_uiautomator2()
            # self._screenshot_ascreencap()
            # self._screenshot_azurpilot_android()
            # self._click_adb(1270, 360)
            # self._click_uiautomator2(1270, 360)
            # self._click_azurpilot_android(1270, 360)

            cost = time.time() - t0
            record.append(cost)
            count += 1

            total_elapsed = time.time() - t_session_start
            fps = count / total_elapsed if total_elapsed > 0 else 0
            # 1280x720x3 字节 = 2.6367 MB/帧
            mb_s = (count * 1280 * 720 * 3) / (1024 * 1024 * total_elapsed) if total_elapsed > 0 else 0

            avg = np.round(np.mean(record), 4)
            std = np.round(np.std(record), 4)
            print(f'[{count:4d}] 单帧耗时: {cost*1000:6.1f}ms | 平均: {avg*1000:6.1f}ms (±{std*1000:5.1f}ms) | 实时吞吐: {fps:5.1f} FPS ({mb_s:6.1f} MB/s)')

            if limit and count >= limit:
                print(f'[+] 压测完成，共执行 {count} 次。最终均值: {avg*1000:.2f}ms, 平均帧率: {fps:.1f} FPS, 平均带宽: {mb_s:.1f} MB/s')
                break


class Config:
    SERIAL = '127.0.0.1:5555'
    # SERIAL = 'azurpilot_android'
    # SERIAL = '127.0.0.1:62001'
    # SERIAL = '127.0.0.1:7555'
    # SERIAL = 'emulator-5554'
    # SERIAL = '127.0.0.1:21503'

    # 速度对比：azurpilot_android / aScreenCap >> uiautomator2 > ADB
    DEVICE_SCREENSHOT_METHOD = 'aScreenCap'  # 可选: ADB, uiautomator2, aScreenCap, azurpilot_android

    # 速度对比：azurpilot_android / uiautomator2 >> ADB
    DEVICE_CONTROL_METHOD = 'uiautomator2'  # 可选: ADB, uiautomator2, azurpilot_android


if __name__ == '__main__':
    az = EmulatorChecker(AzurLaneConfig('template').merge(Config()))
    az.stress_test()

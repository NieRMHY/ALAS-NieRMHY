"""WSA（Windows Subsystem for Android）截图与控制后端模块。

继承 Connection，封装 WSA 特有的多显示屏检测（display id）、应用启动、前台应用检测和屏幕分辨率重置逻辑。
"""

import re
from functools import partial

from adbutils.errors import AdbError

from module.device.connection import Connection
from module.device.method.retry import retry_backend, recover_adb, recover_unknown
from module.device.method.utils import PackageNotInstalled
from module.logger import logger


def _retry_recover(self, error, trial):
    if isinstance(error, (ConnectionResetError, AdbError)):
        return recover_adb(self, error)
    if isinstance(error, PackageNotInstalled):
        logger.error(error)
        return self.detect_package
    return recover_unknown(error)


retry = partial(retry_backend, recover=_retry_recover, label='设备-WSA')


class WSA(Connection):
    """WSA 平台特定的连接与操作实现类。"""

    @retry
    def app_current_wsa(self):
        """获取 WSA 中当前处于前台焦点的应用包名。

        Returns:
            str: 前台应用包名。

        Raises:
            OSError: 无法获取前台应用时抛出。
        """
        # 尝试: adb shell dumpsys activity top
        _activityRE = re.compile(
            r'ACTIVITY (?P<package>[^\s]+)/(?P<activity>[^/\s]+) \w+ pid=(?P<pid>\d+)'
        )
        output = self.adb_shell(['dumpsys', 'activity', 'top'])
        ms = _activityRE.finditer(output)
        ret = None
        for m in ms:
            ret = m.group('package')
            if ret == self.package:
                return ret
        if ret:  # 获取最后匹配的结果
            return ret
        raise OSError("Couldn't get focused app")

    @retry
    def app_start_wsa(self, package_name=None, display=0):
        """在 WSA 指定显示器上启动目标应用。

        Args:
            package_name (str | None): 目标应用包名，默认使用当前绑定的 package。
            display (int): 目标显示屏 ID。

        Returns:
            bool: 启动成功返回 True。

        Raises:
            PackageNotInstalled: 目标应用包未安装时抛出。
        """
        if not package_name:
            package_name = self.package
        self.adb_shell(['svc', 'power', 'stayon', 'true'])
        activity_name = self.get_main_activity_name(package_name=package_name)
        result = self.adb_shell(['am', 'start', '--display', display, f'{package_name}/{activity_name}'])
        if 'Activity not started' in result or 'does not exist' in result:
            logger.error(result)
            raise PackageNotInstalled(package_name)
        else:
            return True

    @retry
    def get_main_activity_name(self, package_name=None):
        """获取目标应用包的主 Activity 名称。

        Args:
            package_name (str | None): 目标应用包名。

        Returns:
            str: 主 Activity 名称。

        Raises:
            PackageNotInstalled: 未能解析到主 Activity 或应用未安装时抛出。
        """
        if not package_name:
            package_name = self.package
        try:
            output = self.adb_shell(['dumpsys', 'package', package_name])
            _activityRE = re.compile(
                r'\w+ ' + package_name + r'/(?P<activity>[^/\s]+) filter'
            )
            ms = _activityRE.finditer(output)
            ret = next(ms).group('activity')
            return ret
        except StopIteration:
            raise PackageNotInstalled(package_name)

    @retry
    def get_display_id(self):
        """获取游戏运行所在的 WSA 显示屏 ID。

        Returns:
            int: 游戏的 display id，未找到或运行在默认 display 0 时返回 0。
        """
        try:
            get_dump_sys_display = str(self.adb_shell(['dumpsys', 'display']))
            display_id_list = re.findall(r'systemapp:' + self.package + ':' + '(.+?)', get_dump_sys_display, re.S)
            display_id = int(display_id_list[0])
            return display_id
        except IndexError:
            return 0  # 当游戏运行在 display 0 上时，其 display id 无法被找到

    @retry
    def display_resize_wsa(self, display):
        """调整 WSA 指定显示屏的分辨率为 1280x720。

        Args:
            display (int): 目标显示屏 ID。
        """
        logger.warning('display ' + str(display) + ' should be resized')
        self.adb_shell(['wm', 'size', '1280x720', '-d', str(display)])

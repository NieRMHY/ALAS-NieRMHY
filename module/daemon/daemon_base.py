"""守护模式基类。

继承 ModuleBase 并禁用卡死检测，为所有守护任务提供基础功能。
守护模式用于后台持续运行，不会因超时自动停止。
"""

from module.base.base import ModuleBase


class DaemonBase(ModuleBase):
    """守护模式运行基类。

    继承 ModuleBase 并禁用设备的卡死检测机制，适用于后台长周期运行的任务。
    """

    def __init__(self, *args, **kwargs):
        """初始化守护进程基类并禁用卡死检测。"""
        super().__init__(*args, **kwargs)
        self.device.disable_stuck_detection()

"""游戏管理器。

提供强制停止游戏进程的功能，并支持可选的自动重启。
继承 LoginHandler 以复用登录和重启逻辑。
"""

from module.handler.login import LoginHandler
from module.logger import logger


class GameManager(LoginHandler):
    """游戏进程管理器。

    提供停止游戏应用进程及按需自动重启的能力。
    """

    def run(self):
        """执行游戏管理任务：停止游戏进程，并根据配置决定是否立即重启。"""
        logger.hr('强制停止碧蓝航线', level=1)
        self.device.app_stop()
        logger.info('[守护-管理] 强制停止完成')

        if self.config.GameManager_AutoRestart:
            LoginHandler(config=self.config, device=self.device).app_restart()


if __name__ == '__main__':
    GameManager('alas', task='GameManager').run()

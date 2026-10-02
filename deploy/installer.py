from deploy.patch import pre_checks

pre_checks()

from deploy.adb import AdbManager
from deploy.alas import AlasManager
from deploy.app import AppManager
from deploy.config import ExecutionError
from deploy.git import GitManager
from deploy.pip import PipManager


class Installer(GitManager, PipManager, AdbManager, AppManager, AlasManager):
    """集成安装器，统筹 Git 更新、进程清理、依赖安装、前端构建及 ADB 服务。"""

    def install(self):
        """执行完整的安装与环境部署流程。"""
        from deploy.atomic import atomic_failure_cleanup
        atomic_failure_cleanup('./config')
        try:
            self.git_install()
            self.alas_kill()
            self.pip_install()
            self.app_update()
            self.adb_install()
        except ExecutionError:
            exit(1)


if __name__ == '__main__':
    Installer().install()

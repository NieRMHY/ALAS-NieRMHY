from deploy.Windows.config import DeployConfig, ExecutionError
from deploy.Windows.logger import Progress, logger
from deploy.uv import command_output, log_command_output, sync_project_venv, venv_python
from deploy.Windows.utils import cached_property


class PipManager(DeployConfig):
    """Windows 下依赖管理类，负责调用 uv 同步 Python 虚拟环境依赖。"""

    @cached_property
    def pip(self):
        """获取 pip 命令行调用前缀。

        Returns:
            str: 格式为 python -m pip 的命令字符串。
        """
        return f'"{self.python}" -m pip'

    @cached_property
    def python_site_packages(self):
        """获取 site-packages 路径（兼容保留）。

        Returns:
            str: 空字符串。
        """
        return ""

    def pip_install(self):
        """同步并更新 Python 运行依赖，并通知安装器进度。

        Raises:
            ExecutionError: 当依赖同步命令失败时抛出。
        """
        logger.hr('Update Dependencies', 0)
        if not self.InstallDependencies:
            logger.info('InstallDependencies is disabled, skip')
            Progress.UpdateDependency()
            return
        try:
            result = sync_project_venv(capture_output=True)
        except Exception as exc:
            logger.critical(f'uv sync failed: {exc}')
            log_command_output(logger, command_output(exc))
            raise ExecutionError from exc
        else:
            log_command_output(logger, result.output)
        Progress.UpdateDependency()

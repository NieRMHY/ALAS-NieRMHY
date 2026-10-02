import sys

from deploy.config import DeployConfig, ExecutionError
from deploy.logger import logger
from deploy.uv import command_output, log_command_output, sync_project_venv, venv_python
from deploy.utils import cached_property


class PipManager(DeployConfig):
    """Python 依赖管理器，基于 uv 维护虚拟环境依赖。"""

    @cached_property
    def python(self) -> str:
        """获取当前虚拟环境或系统中的 Python 解释器路径。

        Returns:
            str: 格式化为正斜杠的 Python 可执行文件路径。
        """
        python = venv_python()
        if python.exists():
            return str(python).replace("\\", "/")
        return sys.executable.replace("\\", "/")

    def pip_install(self):
        """同步并安装项目所需的 Python 依赖。

        Raises:
            ExecutionError: 当依赖同步命令执行失败时抛出。
        """
        logger.hr("Update Dependencies", 0)
        if not self.InstallDependencies:
            logger.info("InstallDependencies is disabled, skip")
            return

        try:
            result = sync_project_venv(capture_output=True)
        except Exception as exc:
            logger.critical(f"uv sync failed: {exc}")
            log_command_output(logger, command_output(exc))
            raise ExecutionError from exc
        else:
            log_command_output(logger, result.output)

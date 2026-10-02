import os
import time
import typing as t

from deploy.Windows.config import DeployConfig
from deploy.Windows.logger import Progress, logger
from deploy.Windows.utils import DataProcessInfo, cached_property, iter_process


class AlasManager(DeployConfig):
    """Windows 下 AzurPilot 进程管理器，支持进程枚举与定向终止。"""

    @cached_property
    def alas_folder(self):
        """获取当前 AzurPilot 相关的 Python 可执行路径与项目根路径列表。

        Returns:
            list[str]: 路径字符串列表。
        """
        return [
            self.filepath(self.PythonExecutable),
            self.root_filepath
        ]

    @cached_property
    def self_pid(self):
        """获取当前进程 PID。

        Returns:
            int: 进程 ID。
        """
        return os.getpid()

    def list_process(self) -> t.List[DataProcessInfo]:
        """枚举当前系统正在运行的所有进程。

        Returns:
            list[DataProcessInfo]: 进程信息列表。
        """
        logger.info('List process')
        process = list(iter_process())
        logger.info(f'Found {len(process)} processes')
        return process

    def iter_process_by_names(self, names, in_alas=False) -> t.Iterable[DataProcessInfo]:
        """按进程名遍历匹配的进程。

        Args:
            names (str, list[str]): 进程名，如 'alas.exe'。
            in_alas (bool): 是否只返回属于当前 AzurPilot 实例的进程。

        Yields:
            DataProcessInfo: 匹配的进程信息。
        """
        if not isinstance(names, list):
            names = [names]
        try:
            for proc in self.list_process():

                if not (proc.name and proc.name in names):
                    continue
                if proc.pid == self.self_pid:
                    continue
                if in_alas:
                    cmdline = proc.cmdline.replace(r"\\", "/").replace("\\", "/")
                    for folder in self.alas_folder:
                        if folder in cmdline:
                            yield proc
                else:
                    yield proc
        except Exception as e:
            logger.info(str(e))
            return False

    def kill_process(self, process: DataProcessInfo):
        """强制终止指定进程树。

        Args:
            process (DataProcessInfo): 待终止的进程信息对象。
        """
        self.execute(f'taskkill /f /t /pid {process.pid}', allow_failure=True, output=False)

    def alas_kill(self):
        """终止当前正在运行的 AzurPilot 相关 Python 进程。

        Returns:
            bool: 是否成功终止所有相关进程。
        """
        for _ in range(10):
            logger.hr(f'Kill existing AzurPilot', 0)
            proc_list = list(self.iter_process_by_names(['python.exe'], in_alas=True))
            if not len(proc_list):
                Progress.KillExisting()
                return True
            for proc in proc_list:
                logger.info(proc)
                self.kill_process(proc)

        logger.warning('Unable to kill existing AzurPilot, skip')
        Progress.KillExisting()
        return False


if __name__ == '__main__':
    self = AlasManager()
    start = time.time()
    self.alas_kill()
    print(time.time() - start)

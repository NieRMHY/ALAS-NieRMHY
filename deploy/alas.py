import pickle

from deploy.config import DeployConfig
from deploy.logger import logger
from deploy.utils import *


class AlasManager(DeployConfig):
    """AzurPilot 进程管理器，负责定位和终止已有进程。"""

    @cached_property
    def alas_folder(self):
        """获取属于当前实例的程序根目录与 Python 路径列表。

        Returns:
            list[str]: 包含 Python 可执行路径与项目根路径的列表。
        """
        return [
            self.filepath("PythonExecutable"),
            self.root_filepath
        ]

    @cached_property
    def self_pid(self):
        """获取当前进程的 PID。

        Returns:
            int: 进程 ID。
        """
        return os.getpid()

    def iter_process_by_name(self, name):
        """按进程名遍历匹配的进程。

        通过 WMI 查询系统进程列表，返回属于当前 AzurPilot 实例的进程信息。

        Args:
            name (str): 进程名，如 'alas.exe'。

        Yields:
            tuple[str, str, str]: (可执行文件路径, 进程名, 进程ID)。
        """
        for _ in range(2):
            try:
                from win32com.client import GetObject
            except ModuleNotFoundError:
                # pywin32 未安装
                logger.info('pywin32 not installed, skip')
                return False
            except (pickle.UnpicklingError, EOFError) as e:
                # win32com 缓存损坏，尝试删除 dicts.dat 后重试
                logger.error(f'{type(e).__name__}: {e}')
                import sys
                import win32api
                gen_path = os.path.join(win32api.GetTempPath(), "gen_py",
                                        "%d.%d" % (sys.version_info[0], sys.version_info[1]))
                file = os.path.join(gen_path, "dicts.dat")
                file = os.path.abspath(file).replace('\\', '/')
                if os.path.exists(file):
                    logger.info(f'win32com dicts.dat exists, removing: {file}')
                    os.remove(file)
                    continue
                else:
                    logger.warning(f'Cannot find win32com dicts.dat')
                    continue
        try:
            _ = GetObject
        except UnboundLocalError:
            logger.warning('Unable to import win32com.client, please fix it manually, '
                           'see https://github.com/LmeSzinc/AzurLaneAutoScript/issues/2382')
            exit(1)

        try:
            wmi = GetObject('winmgmts:')
            processes = wmi.InstancesOf('Win32_Process')
            for p in processes:
                executable_path = p.Properties_["ExecutablePath"].Value
                process_name = p.Properties_("Name").Value
                process_id = p.Properties_["ProcessID"].Value

                if executable_path is not None and process_name == name and process_id != self.self_pid:
                    executable_path = executable_path.replace(r'\\', '/').replace('\\', '/')
                    for folder in self.alas_folder:
                        if folder in executable_path:
                            yield executable_path, process_name, process_id
        except Exception as e:
            # WMI 查询可能抛出 pywintypes.com_error 等异常
            logger.info(str(e))
            return False

    def kill_by_name(self, name):
        """按进程名终止进程。

        Args:
            name (str): 进程名。
        """
        logger.hr(f'Kill {name}', 1)
        for row in self.iter_process_by_name(name):
            logger.info(' '.join(map(str, row)))
            self.execute(f'taskkill /f /pid {row[2]}', allow_failure=True, output=False)

    def alas_kill(self):
        """终止当前正在运行的 AzurPilot 相关进程（alas.exe 和 python.exe）。"""
        logger.hr(f'Kill existing AzurPilot', 0)
        self.kill_by_name('alas.exe')
        self.kill_by_name('python.exe')

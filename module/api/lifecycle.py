"""运行服务生命周期管理模块。

管理与界面会话解耦的后端服务生命周期，包含定时任务处理器、OCR 进程、SSH 隧道以及调度器工作进程的启动与清理。
"""

from module.logger import logger
from module.ocr.rpc import stop_ocr_server_process
from module.runtime.process_manager import ProcessManager
from module.runtime.remote_access import RemoteAccess
from module.runtime.setting import State
from module.runtime.startup_memory import record_running
from module.runtime.task_handler import TaskHandler

task_handler = TaskHandler()


def startup(runs=None):
    """初始化共享进程登记与可选后台服务。

    启动自动检查更新任务、定时更新计划、OCR 独立服务（若配置启用）、
    SSH 远程访问保活以及指定实例的调度器进程。

    Args:
        runs (list[str], optional): 随 WebUI 启动自动运行的实例名称列表。默认为 None。
    """
    from module.runtime.updater import updater
    State.init()
    updater.event = State.manager.Event()
    if updater.delay > 0:
        task_handler.add(updater.check_update_loop(), 1)
    task_handler.add(updater.schedule_update(), 86400)
    task_handler.start()
    if State.deploy_config.StartOcrServer:
        from module.ocr.rpc import start_ocr_server_process
        start_ocr_server_process(State.deploy_config.OcrServerPort)
    if State.deploy_config.EnableRemoteAccess:
        task_handler.add(RemoteAccess.keep_ssh_alive(), 60)
    ProcessManager.restart_processes(instances=runs, ev=updater.event)


def clearup():
    """逐项停止服务，即使某项失败也继续回收其他工作进程。

    依次停止定时任务、OCR 服务进程、SSH 隧道进程及所有活跃的调度器实例，
    并将运行状态记录到启动记忆中。

    Returns:
        bool: 全部服务成功回收返回 True，存在异常或残留返回 False。
    """
    with State.cleanup_lock:
        if State._clearup:
            return True
        actions = [task_handler.stop, stop_ocr_server_process, RemoteAccess.kill_ssh_process]
        success = True
        try:
            running = ProcessManager.running_instances()
            actions.extend(instance.stop for instance in running)
            record_running(instance.config_name for instance in running)
        except Exception:
            logger.exception('无法枚举运行进程，保留共享状态供父监督器回收')
            success = False
        for action in actions:
            try:
                success = (action() is not False) and success
            except Exception:
                logger.exception('运行服务资源回收失败')
                success = False
        if success:
            State.clearup()
        return success

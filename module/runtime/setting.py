"""WebUI 设置与状态管理模块，维护界面偏好和持久化状态。
包括主题配置、展开折叠状态、依赖同步标记，
以及预览资源路径定义和缓存管理机制。"""

# 此文件专门用于管理 Web 界面自身的偏好设置及持久化状态类文件。
# 包括界面主题、常用项展开折叠状态以及各类预览占位图、图标资源的路径定义与缓存管理机制。
import multiprocessing
import os
import threading
from multiprocessing.managers import SyncManager
from typing import TYPE_CHECKING, Callable, Generic, TypeVar

from deploy.atomic import atomic_remove, atomic_write

if TYPE_CHECKING:
    from module.config.config_updater import ConfigUpdater
    from module.runtime.config import DeployConfig

T = TypeVar("T")


# 代码更新后，父监督器必须先完成独立环境同步，才能创建新的 WebUI 子进程。
DEPENDENCY_SYNC_PENDING_FILE = "./config/webui-dependency-sync-pending"


def mark_dependency_sync_pending() -> None:
    """持久化依赖同步待处理状态，供新父进程在启动前恢复。"""
    atomic_write(DEPENDENCY_SYNC_PENDING_FILE, "pending\n")


def is_dependency_sync_pending() -> bool:
    """返回当前启动前是否必须执行依赖同步。"""
    return os.path.isfile(DEPENDENCY_SYNC_PENDING_FILE)


def clear_dependency_sync_pending() -> None:
    """仅在父监督器确认依赖同步成功后清除待处理状态。"""
    atomic_remove(DEPENDENCY_SYNC_PENDING_FILE)


class cached_class_property(Generic[T]):
    """类级别只读属性描述符装饰器，带类型支持并缓存计算结果。

    实现类级别的只读属性，在操作的类上缓存计算结果。
    支持类继承，描述符不会被缓存隐藏；值存储在带下划线的前缀名下。

    Attributes:
        __func__: 被包装的属性获取函数。
        __cache_name__: 在类命名空间中用于缓存结果的属性名称。
    """

    class AliasConflict(ValueError):
        """当包装函数名称与生成的缓存属性名冲突时引发的异常。"""
        pass

    def __init__(self, func: Callable[..., T]):
        """初始化 cached_class_property 描述符。

        Args:
            func: 计算属性值的类方法或可调用对象。

        Raises:
            AliasConflict: 当函数名称与缓存属性名称冲突时抛出。
        """
        self.__func__ = func
        self.__cache_name__ = '_{}_'.format(func.__name__.strip('_'))
        if self.__cache_name__ == func.__name__:
            raise self.AliasConflict(self.__cache_name__)

    def __get__(self, instance, cls=None) -> T:
        """获取描述符属性值，首次访问时计算并缓存。

        Args:
            instance: 访问属性的实例对象（类访问时为 None）。
            cls: 访问属性的目标类。

        Returns:
            计算并缓存的属性值。
        """
        if cls is None:
            cls = type(instance)

        try:
            return vars(cls)[self.__cache_name__]
        except KeyError:
            result = self.__func__(cls)
            setattr(cls, self.__cache_name__, result)
            return result


class State:
    """WebUI 共享全局状态与运行时单例容器。

    管理 WebUI 的生命周期、进程管理器、主题与占位图配置、
    以及跨进程/跨线程同步事件。

    Attributes:
        _init: 是否已完成初始化。
        _clearup: 是否已完成清理。
        cleanup_lock: 清理操作的互斥线程锁。
        restart_lock: 重启流程的可重入线程锁。
        _restart_requested: 是否已发出重启请求。
        restart_event: 通知父进程重启 WebUI 的线程事件。
        dependency_sync_event: 通知依赖同步服务开始同步的线程事件。
        manager: 用于跨进程共享数据的 SyncManager 实例。
        process_registry: 跨进程共享的 worker 进程登记字典。
        electron: 是否运行在 Electron 宿主环境中。
        webui_host: WebUI 绑定的主机地址。
        theme: 当前界面主题名称。
        placeholder_images: 预览占位图文件名列表。
        placeholder_index: 当前选中的占位图索引。
    """

    _init = False
    _clearup = False
    cleanup_lock = threading.Lock()
    restart_lock = threading.RLock()
    _restart_requested = False

    restart_event: threading.Event = None
    dependency_sync_event: threading.Event = None
    manager: SyncManager = None
    process_registry = None
    electron: bool = False
    webui_host: str = None
    theme: str = "default"
    last_screenshot_base64: str = None
    placeholder_images: list = [
        "screen1.jpg",
        "screen2.jpg",
        "screen3.jpg",
    ]
    placeholder_index: int = 0

    @classmethod
    def get_placeholder_url(cls) -> str:
        """获取当前预览占位图的相对静态资源 URL。

        Returns:
            占位图相对于 WebUI 根路径的静态 URL 字符串。
        """
        try:
            idx = getattr(cls.deploy_config, "PlaceholderIndex", None)
            if idx is not None:
                try:
                    idx = int(idx)
                    cls.placeholder_index = idx % len(cls.placeholder_images)
                except Exception:
                    pass
        except Exception:
            pass

        name = cls.placeholder_images[cls.placeholder_index % len(cls.placeholder_images)]
        return f"static/assets/spa/{name}"

    @classmethod
    def toggle_placeholder(cls) -> str:
        """切换到下一个占位图并返回其 URL。

        Returns:
            切换后的占位图相对静态资源 URL。
        """
        return cls.advance_placeholder()

    @classmethod
    def advance_placeholder(cls) -> str:
        """递增占位图索引，更新部署配置并返回新 URL。

        Returns:
            新占位图相对静态资源 URL。
        """
        cls.placeholder_index = (cls.placeholder_index + 1) % len(cls.placeholder_images)
        try:
            cls.deploy_config.PlaceholderIndex = cls.placeholder_index
        except Exception:
            pass
        name = cls.placeholder_images[cls.placeholder_index]
        return f"static/assets/spa/{name}"
    
    @classmethod
    def init(cls):
        """初始化全局跨进程管理器并认领 worker 所有权。

        Raises:
            Exception: 当无法认领 worker 登记所有权或 Manager 初始化失败时抛出。
        """
        cls._clearup = False
        cls._restart_requested = False
        manager = multiprocessing.Manager()
        cls.manager = manager
        # 浏览器会话可能在独立进程中运行，因此 worker 需要跨进程注册表而非会话局部对象。
        cls.process_registry = manager.dict()
        from module.runtime.worker_registry import claim_owner

        try:
            claim_owner(os.getpid())
        except Exception as e:
            # 认领失败说明旧的登记残留无法在当前进程内自愈（例如旧所有者或其
            # worker 仍存活）。记录具体原因再清场，避免留下无主的 Manager
            # 子进程，随后向上抛出由启动方处理。
            from module.logger import logger

            logger.exception(
                f"[WebUI] 无法认领 worker 登记所有权，后端中止启动: {e}"
            )
            cls.process_registry = None
            cls.manager = None
            cls._init = False
            try:
                manager.shutdown()
            except Exception:
                pass
            raise
        cls._init = True

    @classmethod
    def clearup(cls):
        """清理跨进程管理器并释放 worker 登记所有权。

        Raises:
            RuntimeError: 当仍有存活的 worker 进程未回收时抛出。
        """
        if cls._clearup:
            return
        from module.runtime.worker_registry import clear_owner, filter_live_workers, get_workers

        workers = get_workers(os.getpid())
        live_workers = filter_live_workers(workers)
        if live_workers:
            raise RuntimeError(f"仍有存活的 worker 登记未回收: {sorted(live_workers)}")
        cls._clearup = True
        manager = cls.manager
        try:
            if manager is not None:
                manager.shutdown()
        finally:
            cls.manager = None
            cls.process_registry = None
            clear_owner(os.getpid())

    @cached_class_property
    def deploy_config(self) -> "DeployConfig":
        """获取或创建 DeployConfig 部署配置单例。

        Returns:
            DeployConfig 部署配置实例。
        """
        from module.runtime.config import DeployConfig

        return DeployConfig()

    @cached_class_property
    def config_updater(self) -> "ConfigUpdater":
        """获取或创建 ConfigUpdater 配置更新器单例。

        Returns:
            ConfigUpdater 配置更新器实例。
        """
        from module.config.config_updater import ConfigUpdater

        return ConfigUpdater()

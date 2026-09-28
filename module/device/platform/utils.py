"""平台层通用工具模块。

提供 cached_property 属性缓存装饰器（带泛型支持）和 iter_folder 目录遍历辅助函数。
"""

import os
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class cached_property(Generic[T]):
    """带泛型类型提示的实例属性缓存装饰器。

    在实例上首次计算属性值后将其缓存至实例字典（`__dict__`），后续访问直接返回缓存值。
    删除属性可重置缓存。

    参考自: https://github.com/pydanny/cached-property
    """

    def __init__(self, func: Callable[..., T]):
        """初始化属性缓存装饰器。

        Args:
            func: 被装饰的属性计算方法。
        """
        self.func = func

    def __get__(self, obj, cls) -> T:
        """获取或计算缓存的属性值。

        Args:
            obj: 所属类的实例对象。
            cls: 所属类。

        Returns:
            计算并缓存的属性值。
        """
        if obj is None:
            return self

        value = obj.__dict__[self.func.__name__] = self.func(obj)
        return value


def iter_folder(folder, is_dir=False, ext=None):
    """遍历指定文件夹下的所有文件或子目录。

    Args:
        folder (str): 目标文件夹路径。
        is_dir (bool): 是否仅遍历子目录。
        ext (str | None): 过滤的文件扩展名，如 `.yaml`。

    Yields:
        str: 统一使用正斜杠的规范化文件或目录路径。
    """
    try:
        files = os.listdir(folder)
    except FileNotFoundError:
        return

    for file in files:
        sub = os.path.join(folder, file)
        if is_dir:
            if os.path.isdir(sub):
                yield sub.replace('\\\\', '/').replace('\\', '/')
        elif ext is not None:
            if not os.path.isdir(sub):
                _, extension = os.path.splitext(file)
                if extension == ext:
                    yield os.path.join(folder, file).replace('\\\\', '/').replace('\\', '/')
        else:
            yield os.path.join(folder, file).replace('\\\\', '/').replace('\\', '/')

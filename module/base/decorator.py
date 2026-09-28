"""装饰器工具模块。

提供基于配置的方法分发装饰器 Config.when()，以及 cached_property、
timer、function_drop、run_once 等常用装饰器，用于控制方法的执行行为。
"""

import random
import re
from functools import wraps
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class Config:
    """根据配置调用同名不同实现的装饰器。

    func_list 结构示例:
    func_list = {
        'func1': [
            {'options': {'ENABLE': True}, 'func': 1},
            {'options': {'ENABLE': False}, 'func': 1}
        ]
    }
    """
    func_list = {}

    @classmethod
    def when(cls, **kwargs):
        """配置条件装饰器。

        根据运行时配置值决定分发哪个同名函数的具体实现。

        Args:
            **kwargs: AzurLaneConfig 中的任意配置项键值对。

        Examples:
            @Config.when(USE_ONE_CLICK_RETIREMENT=True)
            def retire_ships(self, amount=None, rarity=None):
                pass

            @Config.when(USE_ONE_CLICK_RETIREMENT=False)
            def retire_ships(self, amount=None, rarity=None):
                pass
        """
        from module.logger import logger
        options = kwargs

        def decorate(func):
            name = func.__name__
            data = {'options': options, 'func': func}
            if name not in cls.func_list:
                cls.func_list[name] = [data]
            else:
                override = False
                for record in cls.func_list[name]:
                    if record['options'] == data['options']:
                        record['func'] = data['func']
                        override = True
                if not override:
                    cls.func_list[name].append(data)

            @wraps(func)
            def wrapper(self, *args, **kwargs):
                """条件分发包装函数。

                Args:
                    self: ModuleBase 实例。
                    *args: 位置参数。
                    **kwargs: 关键字参数。

                Returns:
                    Any: 目标函数执行结果。
                """
                for record in cls.func_list[name]:

                    flag = [value is None or self.config.__getattribute__(key) == value
                            for key, value in record['options'].items()]
                    if not all(flag):
                        continue

                    return record['func'](self, *args, **kwargs)

                logger.warning(f'[装饰器] 没有选项适合 {name}，使用最后定义的函数')
                return func(self, *args, **kwargs)

            return wrapper

        return decorate


class cached_property(Generic[T]):
    """带类型支持的缓存属性装饰器。

    来源: https://github.com/pydanny/cached-property
    原始实现: https://github.com/bottlepy/bottle/commit/fa7733e075da0d790d809aa3d2f53071897e6f76

    每个实例只计算一次属性值，之后替换为普通属性。
    删除该属性后会重置缓存。
    """

    def __init__(self, func: Callable[..., T]):
        """初始化缓存属性描述符。

        Args:
            func (Callable[..., T]): 待计算属性的方法。
        """
        self.func = func

    def __get__(self, obj, cls) -> T:
        """获取属性值，未缓存时计算并缓存。

        Args:
            obj: 宿主对象实例。
            cls: 宿主类。

        Returns:
            T: 属性值。
        """
        if obj is None:
            return self

        value = obj.__dict__[self.func.__name__] = self.func(obj)
        return value


def del_cached_property(obj, name):
    """安全地删除缓存属性。

    Args:
        obj: 目标对象。
        name (str): 属性名称。
    """
    try:
        del obj.__dict__[name]
    except KeyError:
        pass


def has_cached_property(obj, name):
    """检查属性是否已被缓存。

    Args:
        obj: 目标对象。
        name (str): 属性名称。

    Returns:
        bool: 如果属性已缓存则返回 True，否则返回 False。
    """
    return name in obj.__dict__


def set_cached_property(obj, name, value):
    """设置缓存属性。

    Args:
        obj: 目标对象。
        name (str): 属性名称。
        value: 属性值。
    """
    obj.__dict__[name] = value


def function_drop(rate=0.5, default=None):
    """随机丢弃函数调用，用于模拟模拟器卡死的测试场景。

    Args:
        rate (float): 丢弃概率，取值范围 0 到 1。
        default: 被丢弃时返回的默认值。
    """
    from module.logger import logger

    def decorate(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if random.uniform(0, 1) > rate:
                return func(*args, **kwargs)
            else:
                cls = ''
                arguments = [str(arg) for arg in args]
                if len(arguments):
                    matched = re.search('<(.*?) object at', arguments[0])
                    if matched:
                        cls = matched.group(1) + '.'
                        arguments.pop(0)
                arguments += [f'{k}={v}' for k, v in kwargs.items()]
                arguments = ', '.join(arguments)
                logger.info(f'[装饰器] 已丢弃: {cls}{func.__name__}({arguments})')
                return default

        return wrapper

    return decorate


def run_once(f):
    """确保函数只执行一次，无论被调用多少次。

    Args:
        f (Callable): 待包装的函数。

    Returns:
        Callable: 包装后的只运行一次的函数。
    """

    def wrapper(*args, **kwargs):
        if not wrapper.has_run:
            wrapper.has_run = True
            return f(*args, **kwargs)

    wrapper.has_run = False
    return wrapper

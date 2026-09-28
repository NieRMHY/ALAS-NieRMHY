"""重试装饰器模块。

从 retry 库复制并修改，提供带退避（backoff）、抖动（jitter）和可配置异常处理的
重试装饰器，用于自动重试失败的操作。
"""

import functools
import random
import time
from functools import partial

from module.logger import logger as logging_logger

"""
从 `retry` 库复制并修改。
"""

try:
    from decorator import decorator
except ImportError:
    def decorator(caller):
        """将 caller 转换为装饰器。

        与 decorator 模块不同，不会保留函数签名。

        Args:
            caller (Callable): 调用函数，签名如 caller(f, *args, **kwargs)。

        Returns:
            Callable: 转换后的装饰器函数。
        """

        def decor(f):
            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                return caller(f, *args, **kwargs)

            return wrapper

        return decor


def __retry_internal(f, exceptions=Exception, tries=-1, delay=0, max_delay=None, backoff=1, jitter=0,
                     logger=logging_logger):
    """执行函数并在失败时重试。

    Args:
        f (Callable): 要执行的函数。
        exceptions (type[Exception] | tuple[type[Exception], ...]): 需要捕获的异常或异常元组。默认为 Exception。
        tries (int): 最大尝试次数。默认为 -1（无限次）。
        delay (int | float): 重试之间的初始延迟秒数。默认为 0。
        max_delay (int | float | None): 延迟的最大值。默认为 None（无限制）。
        backoff (int | float | tuple): 重试延迟的乘数因子。默认为 1（无退避）。
            如果是数字则为固定值，如果是元组 (min, max) 则为随机范围。
        jitter (int | float | tuple): 重试延迟的额外秒数。默认为 0。
            如果是数字则为固定值，如果是元组 (min, max) 则为随机范围。
        logger (logging.Logger | None): 失败时记录日志的 Logger 对象。
            默认为 logging_logger，为 None 则禁用日志。

    Returns:
        Any: f 函数的返回值。

    Raises:
        Exception: 达到最大尝试次数后抛出最后一次捕获的异常。
    """
    _tries, _delay = tries, delay
    while _tries:
        try:
            return f()
        except exceptions as e:
            _tries -= 1
            if not _tries:
                # 与原版不同，抛出原始异常
                raise e

            if logger is not None:
                # 与原版不同，显示异常详情
                logger.exception(e)
                logger.warning(f'{type(e).__name__}({e}), 重试，等待 {_delay} 秒...')

            time.sleep(_delay)
            _delay *= backoff

            if isinstance(jitter, tuple):
                _delay += random.uniform(*jitter)
            else:
                _delay += jitter

            if max_delay is not None:
                _delay = min(_delay, max_delay)


def retry(exceptions=Exception, tries=-1, delay=0, max_delay=None, backoff=1, jitter=0, logger=logging_logger):
    """返回一个重试装饰器。

    Args:
        exceptions (type[Exception] | tuple[type[Exception], ...]): 需要捕获的异常或异常元组。默认为 Exception。
        tries (int): 最大尝试次数。默认为 -1（无限次）。
        delay (int | float): 重试之间的初始延迟秒数。默认为 0。
        max_delay (int | float | None): 延迟的最大值。默认为 None（无限制）。
        backoff (int | float | tuple): 重试延迟的乘数因子。默认为 1（无退避）。
            如果是数字则为固定值，如果是元组 (min, max) 则为随机范围。
        jitter (int | float | tuple): 重试延迟的额外秒数。默认为 0。
            如果是数字则为固定值，如果是元组 (min, max) 则为随机范围。
        logger (logging.Logger | None): 失败时记录日志的 Logger 对象。
            默认为 logging_logger，为 None 则禁用日志。

    Returns:
        Callable: 重试装饰器包装函数。
    """

    @decorator
    def retry_decorator(f, *fargs, **fkwargs):
        args = fargs if fargs else list()
        kwargs = fkwargs if fkwargs else dict()
        return __retry_internal(partial(f, *args, **kwargs), exceptions, tries, delay, max_delay, backoff, jitter,
                                logger)

    return retry_decorator


def retry_call(f, fargs=None, fkwargs=None, exceptions=Exception, tries=-1, delay=0, max_delay=None, backoff=1,
               jitter=0,
               logger=logging_logger):
    """调用函数并在失败时重新执行。

    Args:
        f (Callable): 要执行的函数。
        fargs (list | tuple | None): 函数的位置参数。
        fkwargs (dict | None): 函数的关键字参数。
        exceptions (type[Exception] | tuple[type[Exception], ...]): 需要捕获的异常或异常元组。默认为 Exception。
        tries (int): 最大尝试次数。默认为 -1（无限次）。
        delay (int | float): 重试之间的初始延迟秒数。默认为 0。
        max_delay (int | float | None): 延迟的最大值。默认为 None（无限制）。
        backoff (int | float | tuple): 重试延迟的乘数因子。默认为 1（无退避）。
        jitter (int | float | tuple): 重试延迟的额外秒数。默认为 0。
            如果是数字则为固定值，如果是元组 (min, max) 则为随机范围。
        logger (logging.Logger | None): 失败时记录日志的 Logger 对象。
            默认为 logging_logger，为 None 则禁用日志。

    Returns:
        Any: f 函数的返回值。
    """
    args = fargs if fargs else list()
    kwargs = fkwargs if fkwargs else dict()
    return __retry_internal(partial(f, *args, **kwargs), exceptions, tries, delay, max_delay, backoff, jitter, logger)

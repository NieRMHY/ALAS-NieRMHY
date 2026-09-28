"""pkg_resources 轻量兼容补丁模块。

由于导入完整的 pkg_resources 耗时过长（约 0.4 ~ 1.0 秒），本模块提供轻量实现，
仅返回 adbutils 和 uiautomator2 所需的包分发与资源定位信息。

使用方式：
    在导入 adbutils 和 uiautomator2 之前预先导入本模块。
"""

import os
import re
import sys

from module.base.decorator import cached_property
from module.logger import logger

# 注入 sys.modules，模拟已导入 pkg_resources
try:
    sys.modules['pkg_resources'] = sys.modules['module.device.pkg_resources']
except KeyError:
    logger.error('[设备-补丁] 修补pkg_resources失败，补丁模块不存在')


def removesuffix(s, suffix):
    """移除字符串或字节串末尾的指定后缀。

    兼容 Python 3.9 之前的版本。

    Args:
        s (str | bytes): 目标字符串或字节串。
        suffix (str | bytes): 待移除的后缀。

    Returns:
        str | bytes: 移除后缀后的字符串或字节串。
    """
    # suffix 为空时 s[:-0] 会导致空字符串，故需特别判断
    if suffix and s.endswith(suffix):
        return s[:-len(suffix)]
    return s


class FakeDistributionObject:
    """伪造的包分发对象，模拟 pkg_resources.Distribution。

    Attributes:
        dist (str): 包名称。
        version (str): 包版本号。
    """

    def __init__(self, dist, version):
        """初始化包分发对象。

        Args:
            dist (str): 包名称。
            version (str): 版本号。
        """
        self.dist = dist
        self.version = version

    def __str__(self):
        return f'{self.__class__.__name__}({self.dist}={self.version})'

    __repr__ = __str__


class PackageCache:
    """已安装 Python 包信息缓存管理类。"""

    @cached_property
    def site_packages(self):
        """获取 site-packages 目录的绝对路径。

        Returns:
            str: site-packages 文件夹路径。
        """
        # 借用 requests 模块定位 site-packages 目录
        import requests
        path = os.path.abspath(os.path.join(requests.__file__, '../../'))
        return path

    @cached_property
    def dict_installed_packages(self):
        """扫描并解析 site-packages 中已安装的包信息。

        Returns:
            dict[str, FakeDistributionObject]: 包名到伪分发对象的映射字典。
        """
        dic = {}
        for file in os.listdir(self.site_packages):
            # 匹配形如 mxnet_cu101-1.6.0.dist-info 或 adbutils-0.11.0-py3.7.egg-info
            res = re.match(r'^([a-zA-Z0-9._]+)-([a-zA-Z0-9._]+)-', file)
            if res:
                version = removesuffix(res.group(2), '.dist')
                obj = FakeDistributionObject(
                    dist=res.group(1),
                    version=version,
                )
                dic[obj.dist] = obj

        return dic


PACKAGE_CACHE = PackageCache()


def resource_filename(*args):
    """获取指定包资源文件的绝对路径。

    Args:
        *args: 路径层级组件。

    Returns:
        str | None: 资源文件绝对路径。
    """
    if args == ("adbutils", "binaries"):
        path = os.path.abspath(os.path.join(PACKAGE_CACHE.site_packages, *args))
        return path


def get_distribution(dist):
    """获取指定包的 Distribution 对象。

    Args:
        dist (str): 包名。

    Returns:
        FakeDistributionObject | None: 对应的分发对象。
    """
    if dist == 'adbutils':
        return PACKAGE_CACHE.dict_installed_packages.get(
            'adbutils',
            FakeDistributionObject('adbutils', '0.11.0'),
        )
    if dist == 'uiautomator2':
        return PACKAGE_CACHE.dict_installed_packages.get(
            'uiautomator2',
            FakeDistributionObject('uiautomator2', '2.16.17'),
        )


class DistributionNotFound(Exception):
    """未找到包分发信息异常。"""
    pass

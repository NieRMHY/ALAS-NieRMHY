"""子模块加载器，通过 importlib 动态加载外部桥接模块。
支持加载 MAA、FPY 等第三方战斗辅助模块，
并提供模块配置的加载接口。"""

import importlib

from module.logger import logger
from module.submodule.utils import *


def load_mod(name):
    """动态加载指定的外部子功能模块。

    Args:
        name (str): 子模块名称。

    Returns:
        module | None: 加载成功的 Python 模块对象，未找到时返回 None。
    """
    dir_name = get_mod_dir(name)
    if dir_name is None:
        logger.critical("[Submodule] 对应的功能模块不存在")  # Modify by MHY, 去傲娇语
        return

    return importlib.import_module('.' + name, 'submodule.' + dir_name)


def load_config(config_name):
    """加载指定配置名称对应的配置实例。

    根据配置前缀判断属于 ALAS 原生配置还是子模块配置并分别加载。

    Args:
        config_name (str): 配置名称。

    Returns:
        AzurLaneConfig | object: 对应的配置对象实例。
    """
    from module.config.config import AzurLaneConfig

    mod_name = get_config_mod(config_name)
    if mod_name == 'alas':
        return AzurLaneConfig(config_name, '')
    else:
        config_lib = importlib.import_module(
            '.config',
            'submodule.' + get_mod_dir(mod_name) + '.module.config')
        return config_lib.load_config(config_name, '')


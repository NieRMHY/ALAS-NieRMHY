"""Web 界面部署配置管理。

提供 DeployConfig 的 WebUI 子类，将配置变更实时写入部署文件。
通过 __setattr__ 拦截属性修改，自动同步到磁盘配置。
"""
from deploy.config import DeployConfig as _DeployConfig


class DeployConfig(_DeployConfig):
    """WebUI 部署配置管理器。

    拦截属性赋值操作并将其自动持久化同步到磁盘配置文件中。
    """

    def show_config(self):
        """显示当前配置内容（WebUI 运行环境下静默空实现）。"""
        pass

    def __setattr__(self, key: str, value):
        """拦截属性修改并将可保存字段自动持久化到部署配置中。

        Args:
            key: 属性键名。
            value: 属性新值。
        """
        if key[0].isupper() and key in getattr(self, 'config', {}):
            self.update_config({key: value})
        else:
            super().__setattr__(key, value)

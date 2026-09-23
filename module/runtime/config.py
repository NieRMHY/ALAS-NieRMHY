"""
Web界面部署配置管理。

提供 DeployConfig 的 WebUI 子类，将配置变更实时写入部署文件。
通过 __setattr__ 拦截属性修改，自动同步到磁盘配置。
"""

from deploy.config import DeployConfig as _DeployConfig


class DeployConfig(_DeployConfig):
    def show_config(self):
        pass

    def __setattr__(self, key: str, value):
        """可保存字段通过完整事务更新，落盘失败时恢复属性。"""
        if key[0].isupper() and key in getattr(self, 'config', {}):
            self.update_config({key: value})
        else:
            super().__setattr__(key, value)

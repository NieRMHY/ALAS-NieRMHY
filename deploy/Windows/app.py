"""Windows 安装器的 React 前端构建步骤。"""
from deploy.Windows.config import DeployConfig
from deploy.Windows.logger import Progress
from deploy.frontend import ensure_frontend


class AppManager(DeployConfig):
    """Windows 下前端应用管理器，负责同步并构建前端静态资源。"""

    def app_update(self):
        """构建前端，并更新安装器进度。"""
        ensure_frontend()
        Progress.UpdateAlasApp()

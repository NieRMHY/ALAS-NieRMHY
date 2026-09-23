"""Windows 安装器的 React 前端构建步骤。"""
from deploy.Windows.config import DeployConfig
from deploy.Windows.logger import Progress
from deploy.frontend import ensure_frontend


class AppManager(DeployConfig):
    def app_update(self):
        """构建前端，并更新安装器进度。"""
        ensure_frontend()
        Progress.UpdateAlasApp()

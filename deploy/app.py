"""安装器的 React 前端构建步骤。"""
from deploy.config import DeployConfig
from deploy.frontend import ensure_frontend


class AppManager(DeployConfig):
    def app_update(self):
        """同步前端产物，替代旧 app.asar 更新。"""
        ensure_frontend()

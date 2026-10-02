"""运行时环境与后台服务模块。

初始化日志配置并将部署日志输出重定向至核心 logger。
"""

# 必须最先导入，初始化日志目录
from module.logger import logger
import deploy.logger

deploy.logger.logger = logger

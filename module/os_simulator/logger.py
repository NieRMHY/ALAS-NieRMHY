"""大世界模拟器日志模块。

为大世界模拟器提供独立的日志系统，包括 tqdm 输出重定向器
（用于非控制台环境）和模拟器专用日志器（基于文件轮转），
确保模拟运行过程可追溯且不影响主程序日志。
"""
import logging
import os
from datetime import datetime

from module.logger import file_formatter

class TqdmToLogger:
    """tqdm 进度条日志重定向辅助类。

    将 tqdm 进度输出重定向到指定的日志记录器，适用于非控制台或 Web 运行环境。

    Attributes:
        logger (logging.Logger): 接收输出的目标日志器。
    """

    def __init__(self, logger):
        """初始化重定向器。

        Args:
            logger (logging.Logger): 目标日志器。
        """
        self.logger = logger

    def write(self, buf):
        """写入进度文本到日志器。

        Args:
            buf (str): 待写入的字符串缓冲区。
        """
        msg = buf.strip('\r\n\t ')
        if msg:
            self.logger.info(msg)

    def flush(self):
        """刷新缓冲区操作（空实现以兼容流接口）。"""
        pass


class OSSLogger:
    """大世界模拟器专用日志记录器。

    初始化独立的文件日志处理器，并将日志向上传播至控制台。
    """

    def __init__(self):
        """初始化大世界模拟器日志处理器。"""
        self.logger = logging.getLogger('alas.OSSimulator')
        self.logger.setLevel(logging.INFO)
        
        # 仅在未初始化 handler 时添加，防止重复
        if not self.logger.handlers:
            os.makedirs('./log/oss', exist_ok=True)
            self.logger_path = f'./log/oss/{datetime.now().strftime("%Y-%m-%d")}.log'
            fh = logging.FileHandler(self.logger_path, encoding='utf-8')
            fh.setFormatter(file_formatter)
            self.logger.addHandler(fh)
            # 通过 propagate 让日志显示在原有项目的控制台流中
            self.logger.propagate = True

    def __getattr__(self, name):
        """委托属性访问到底层日志器。

        Args:
            name (str): 属性名称。

        Returns:
            Any: 底层日志器的对应属性。
        """
        return getattr(self.logger, name)
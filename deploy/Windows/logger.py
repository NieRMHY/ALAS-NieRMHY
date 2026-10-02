"""Windows 安装器日志与百分比进度上报模块。"""
import logging
import os
import sys

os.chdir(os.path.join(os.path.dirname(__file__), '../../'))

logger = logging.getLogger("deploy")
_logger = logger

formatter = logging.Formatter(fmt="%(message)s")
hdlr = logging.StreamHandler(stream=sys.stdout)
hdlr.setFormatter(formatter)
logger.addHandler(hdlr)
logger.setLevel(logging.INFO)


def hr(title, level=3):
    """输出带修饰边框的分隔标题。

    Args:
        title (str): 标题文本。
        level (int): 标题级别（0: 大框, 1: 双横线, 2: 单横线, 3: 尖括号）。
    """
    if logger is not _logger:
        return logger.hr(title, level)

    title = str(title).upper()
    if level == 0:
        middle = "|" + " " * 20 + title + " " * 20 + "|"
        border = "+" + "-" * (len(middle) - 2) + "+"
        logger.info(border)
        logger.info(middle)
        logger.info(border)
    if level == 1:
        logger.info("=" * 20 + " " + title + " " + "=" * 20)
    if level == 2:
        logger.info("-" * 20 + " " + title + " " + "-" * 20)
    if level == 3:
        logger.info(f"<<< {title} >>>")


def attr(name, text):
    """格式化输出属性名称与取值。

    Args:
        name (str): 属性名称。
        text (str): 属性内容。
    """
    print(f'[{name}] {text}')


logger.hr = hr
logger.attr = attr


class Percentage:
    """百分比进度回调类。"""

    def __init__(self, progress):
        """初始化百分比进度节点。

        Args:
            progress (int): 进度数值（0-100）。
        """
        self.progress = progress

    def __call__(self, *args, **kwargs):
        """记录当前进度百分比到日志。"""
        logger.info(f'Process: [ {self.progress}% ]')


class Progress:
    """安装器各阶段对应的百分比进度预设定义。"""
    Start = Percentage(0)
    ShowDeployConfig = Percentage(10)

    GitInit = Percentage(12)
    GitSetConfig = Percentage(13)
    GitSetRepo = Percentage(15)
    GitFetch = Percentage(40)
    GitReset = Percentage(45)
    GitCheckout = Percentage(48)
    GitShowVersion = Percentage(50)

    GitLatestCommit = Percentage(25)
    GitDownloadPack = Percentage(40)

    KillExisting = Percentage(60)
    UpdateDependency = Percentage(70)
    UpdateAlasApp = Percentage(75)

    AdbReplace = Percentage(80)
    AdbConnect = Percentage(95)

    # 必须有一个 100% 的完成状态
    Finish = Percentage(100)

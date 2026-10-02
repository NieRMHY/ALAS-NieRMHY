"""部署与安装阶段的基础日志输出模块。"""
import logging
import os
import sys

os.chdir(os.path.join(os.path.dirname(__file__), '../'))

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

"""大世界配置重定向工具。

包含 action_point_redirect 等函数，用于将旧版大世界处理器的布尔配置值
迁移转换为新版的数值格式。
"""


def action_point_redirect(value):
    """大世界行动点配置值重定向转换。

    Args:
        value (bool): 旧版布尔配置值。如果为 True 则返回 5，否则返回 0。

    Returns:
        int: 新版对应的行动点数值。
    """
    if value is True:
        return 5
    else:
        return 0

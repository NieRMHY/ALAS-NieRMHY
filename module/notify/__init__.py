"""通知模块。"""

def notify_title(config_name, category, summary):
    """统一推送标题格式：<实例名> [类别] 简介（实现见 notify.notify）。"""
    from module.notify.notify import notify_title as _notify_title
    return _notify_title(config_name, category, summary)


def handle_notify(*args, **kwargs):
    """处理推送通知请求。

    延迟导入 onepush 模块，避免在未使用通知功能时加载依赖。

    Args:
        *args: 传递给底层 handle_notify 的位置参数。
        **kwargs: 传递给底层 handle_notify 的关键字参数。

    Returns:
        Any: 底层 handle_notify 的执行结果。
    """
    from module.notify.notify import handle_notify
    return handle_notify(*args, **kwargs)


def notify_webui(*args, **kwargs):
    """推送通知到 WebUI 本地端口。

    延迟导入 notify 模块，将通知转发给 WebUI 启动器接收。

    Args:
        *args: 传递给底层 notify_webui 的位置参数。
        **kwargs: 传递给底层 notify_webui 的关键字参数。

    Returns:
        Any: 底层 notify_webui 的执行结果。
    """
    from module.notify.notify import notify_webui
    return notify_webui(*args, **kwargs)


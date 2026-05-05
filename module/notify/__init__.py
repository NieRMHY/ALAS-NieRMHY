def handle_notify(*args, **kwargs):
    # Lazy import onepush
    from module.notify.notify import handle_notify
    return handle_notify(*args, **kwargs)


def notify_webui(*args, **kwargs):
    from module.notify.notify import notify_webui
    return notify_webui(*args, **kwargs)

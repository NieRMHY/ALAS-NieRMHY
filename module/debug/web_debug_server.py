import threading

from module.logger import logger


# 由调用方注入的调试处理器，未注入时所有端点只回执不动作。
DEBUG_HANDLER = None

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8765


def _trigger(method):
    """调用调试处理器上的指定方法，未注入处理器时静默跳过。"""
    if DEBUG_HANDLER is not None:
        getattr(DEBUG_HANDLER, method)()


def _register_routes(app, jsonify):
    @app.route('/debug/gem')
    def debug_gem():
        _trigger('trigger_gem_test')
        return jsonify({'status': 'ok', 'action': 'gem_test'})

    @app.route('/debug/cube')
    def debug_cube():
        _trigger('trigger_cube_test')
        return jsonify({'status': 'ok', 'action': 'cube_test'})

    @app.route('/debug/big')
    def debug_big():
        _trigger('trigger_big_success')
        return jsonify({'status': 'ok', 'action': 'big_success'})

    @app.route('/debug/notify')
    def debug_notify():
        _trigger('trigger_notify_only')
        return jsonify({'status': 'ok', 'action': 'notify_test'})


def run_server(host=DEFAULT_HOST, port=DEFAULT_PORT):
    from flask import Flask, jsonify

    app = Flask(__name__)
    _register_routes(app, jsonify)
    app.run(host=host, port=port, debug=False, use_reloader=False)


def start_debug_server(handler, host=DEFAULT_HOST, port=DEFAULT_PORT):
    """在后台线程启动调试服务。

    flask 为可选依赖：未安装时记录告警并返回 False，不影响调度器运行。
    安装方式：`uv run --with flask python alas.py`。

    Args:
        handler: 具备 trigger_* 方法的调试处理器，通常为 CommissionDebugHandler。
        host (str): 监听地址，默认仅本机回环。
        port (int): 监听端口。

    Returns:
        bool: 是否成功启动。
    """
    global DEBUG_HANDLER

    try:
        from flask import Flask  # noqa: F401
    except ImportError:
        logger.warning(
            '未安装 flask，调试服务未启动。'
            '如需启用请使用 `uv run --with flask python alas.py` 启动调度器'
        )
        return False

    DEBUG_HANDLER = handler

    thread = threading.Thread(
        target=run_server,
        kwargs={'host': host, 'port': port},
        daemon=True,
    )
    thread.start()

    logger.info(f'调试服务已启动：http://{host}:{port}/debug/{{gem,cube,big,notify}}')
    return True

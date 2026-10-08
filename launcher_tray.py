"""ALAS 系统托盘启动器（无窗口后台运行）。

由 pythonw 启动，拉起 gui.py WebUI 子进程，在系统托盘显示图标，
菜单可「打开 WebUI / 退出」。退出时终止整个 gui.py 进程树
（含 multiprocessing worker），确保彻底结束。
"""
import os
import sys
import subprocess
import webbrowser
from datetime import datetime
from urllib.parse import urlsplit

from PIL import Image
import pystray


ROOT = os.path.dirname(os.path.abspath(__file__))
WEBUI_URL = "http://127.0.0.1:22267"


def log(message):
    # Modify by MHY, pythonw 没有控制台，异常与崩溃不留痕迹，排查只能靠猜。
    # 统一写 log/launcher.txt，失败也不影响启动。
    try:
        path = os.path.join(ROOT, "log", "launcher.txt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except Exception:
        pass


def webui_alive(timeout=1.5):
    """探测 WebUI 是否真的在监听端口。

    只信互斥量是不够的：更新链的 alas_kill 杀 python.exe（gui.py）却杀不到
    pythonw 启动器，残留的启动器仍持有互斥量，此时单看互斥量会把「WebUI 已死」
    误判成「已在运行」，双击快捷方式只会打开一个打不开的死页面。

    Returns:
        bool: 端口可连接返回 True。
    """
    url = urlsplit(WEBUI_URL)
    try:
        import socket
        with socket.create_connection((url.hostname or "127.0.0.1", url.port or 80), timeout=timeout):
            return True
    except OSError:
        return False


def _venv_python():
    # Modify by MHY, gui.py 的 multiprocessing worker spawn 需要有效的 console
    # 句柄，pythonw（无控制台）下 worker 会立即崩溃，故优先用 python.exe
    for rel in (".venv/Scripts/python.exe", ".venv/Scripts/pythonw.exe"):
        p = os.path.join(ROOT, *rel.split("/"))
        if os.path.exists(p):
            return p
    return sys.executable


def _kill_tree(pid):
    # Windows 用 taskkill 终止整个进程树（gui.py 主进程 + multiprocessing worker）
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        import signal
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass


def main():
    # Modify by MHY, 单实例锁：重复双击启动时若已有实例运行，直接打开浏览器，
    # 避免拉起多个 gui.py（worker bind 端口失败但仍开网页，导致出现两个网页）。
    # 用 Windows 命名互斥量，无启动窗口期，比端口检测更可靠。
    if sys.platform == "win32":
        try:
            import win32event, win32api, winerror
            _mutex = win32event.CreateMutex(None, False, "Global\\ALAS-Launcher")
            if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
                # Modify by MHY, 互斥量只说明「有启动器活着」，不代表 WebUI 活着。
                # 更新中断后 gui.py 会被杀掉而启动器残留，这里再探一次端口：
                # WebUI 真的在跑才开浏览器，否则继续往下走重新拉起 gui.py。
                if webui_alive():
                    log("已有实例在运行，打开浏览器")
                    webbrowser.open(WEBUI_URL)
                    return
                log("互斥量被残留启动器占用但 WebUI 未监听，接管并重新拉起 gui.py")
        except Exception as exc:
            log(f"互斥量检查失败，按无实例继续：{exc!r}")
    py = _venv_python()
    # Modify by MHY, CREATE_NEW_CONSOLE 给 gui.py 一个新 console，其 worker 继承有效的
    # console 句柄（pythonw 无 console 会导致 worker spawn 崩溃）；SW_HIDE 让窗口创建即
    # 隐藏，实现无窗口后台运行。不重定向 stdout/stderr，保留 worker 继承的 console 句柄。
    popen_kwargs = {"cwd": ROOT}
    # Modify by MHY, 新版 WebUI 启动链 ensure_frontend 需要 Node.js（本地解压版），
    # 前置进子进程 PATH，避免每次系统级安装 Node
    node_dir = os.path.join(ROOT, "nodejs", "node-v24.21.0-win-x64")
    if os.path.isdir(node_dir):
        popen_kwargs["env"] = {**os.environ, "PATH": node_dir + os.pathsep + os.environ.get("PATH", "")}
    if sys.platform == "win32":
        # Modify by MHY, SW_HIDE 隐藏 console 下 gui 会静默退出（uvicorn 多进程在无可见
        # console 句柄场景不稳定）；改 SW_SHOWMINNOACTIVE——窗口存在但最小化不起焦点，
        # 与 bat 前台运行同构，任务栏可点开查日志
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 7  # SW_SHOWMINNOACTIVE
        popen_kwargs["startupinfo"] = si
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    gui_proc = subprocess.Popen(
        [py, os.path.join(ROOT, "gui.py")],
        **popen_kwargs,
    )
    log(f"已拉起 gui.py (PID: {gui_proc.pid})")

    icon_path = os.path.join(ROOT, "deploy", "launcher", "icon.ico")
    if os.path.exists(icon_path):
        image = Image.open(icon_path)
    else:
        image = Image.new("RGB", (64, 64), (60, 120, 200))

    def on_open(icon, item):
        webbrowser.open(WEBUI_URL)

    def on_quit(icon, item):
        _kill_tree(gui_proc.pid)
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("打开 WebUI", on_open, default=True),
        pystray.MenuItem("退出 ALAS", on_quit),
    )
    icon = pystray.Icon("ALAS", image, "ALAS WebUI", menu)
    icon.run()


if __name__ == "__main__":
    # Modify by MHY, pythonw 下异常没有任何可见输出，统一记到日志再抛出
    try:
        main()
    except Exception:
        import traceback
        log("启动器异常退出：\n" + traceback.format_exc())
        raise

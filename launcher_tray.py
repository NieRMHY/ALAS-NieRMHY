"""AzurPilot 系统托盘启动器（无窗口后台运行）。

由 pythonw 启动，拉起 gui.py WebUI 子进程，在系统托盘显示图标，
菜单可「打开 WebUI / 退出」。退出时终止整个 gui.py 进程树
（含 multiprocessing worker），确保彻底结束。
"""
import os
import sys
import subprocess
import webbrowser

from PIL import Image
import pystray


ROOT = os.path.dirname(os.path.abspath(__file__))
WEBUI_URL = "http://127.0.0.1:22267"


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
    py = _venv_python()
    # Modify by MHY, CREATE_NEW_CONSOLE 给 gui.py 一个新 console，其 worker 继承有效的
    # console 句柄（pythonw 无 console 会导致 worker spawn 崩溃）；SW_HIDE 让窗口创建即
    # 隐藏，实现无窗口后台运行。不重定向 stdout/stderr，保留 worker 继承的 console 句柄。
    popen_kwargs = {"cwd": ROOT}
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        popen_kwargs["startupinfo"] = si
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    gui_proc = subprocess.Popen(
        [py, os.path.join(ROOT, "gui.py")],
        **popen_kwargs,
    )

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
        pystray.MenuItem("退出 AzurPilot", on_quit),
    )
    icon = pystray.Icon("AzurPilot", image, "AzurPilot WebUI", menu)
    icon.run()


if __name__ == "__main__":
    main()

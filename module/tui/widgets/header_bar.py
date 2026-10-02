"""TUI 顶部状态栏组件。"""

from datetime import datetime
from typing import Any, Dict, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label


class HeaderBar(Widget):
    """顶部标题与全局状态栏。"""

    DEFAULT_CSS = """
    HeaderBar {
        height: 3;
        dock: top;
        background: $surface;
        border-bottom: solid $primary;
        padding: 0 1;
    }
    #header-container {
        width: 100%;
        height: 100%;
        align: left middle;
    }
    #app-title {
        text-style: bold;
        color: $accent;
        margin-right: 2;
    }
    #instance-badge {
        color: $text;
        background: $panel;
        padding: 0 1;
        margin-right: 2;
    }
    #status-badge {
        padding: 0 1;
        margin-right: 2;
    }
    #emulator-info {
        color: $text-muted;
        margin-right: 2;
    }
    #clock-label {
        dock: right;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.instance_name = "alas"
        self.status = "stopped"
        self.serial = "auto"
        self.server = "cn"
        self.current_task: Optional[str] = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="header-container"):
            yield Label("⚓ AzurPilot TUI", id="app-title")
            yield Label(f"实例: {self.instance_name}", id="instance-badge")
            yield Label("⚪ 已停止", id="status-badge")
            yield Label("模拟器: -", id="emulator-info")
            yield Label(datetime.now().strftime("%H:%M:%S"), id="clock-label")

    def update_info(
        self,
        instance_name: str,
        status: str,
        emulator: Optional[Dict[str, Any]] = None,
        current_task: Optional[str] = None,
    ) -> None:
        """更新状态栏数据。"""
        self.instance_name = instance_name
        self.status = status
        self.current_task = current_task
        if emulator:
            self.serial = emulator.get("Serial", "auto")
            self.server = emulator.get("ServerName", "cn")

        # 更新标签
        inst_label = self.query_one("#instance-badge", Label)
        inst_label.update(f"实例: [{self.instance_name}]")

        status_label = self.query_one("#status-badge", Label)
        if status == "running":
            task_str = f" ({self.current_task})" if self.current_task else ""
            status_label.update(Text(f"🟢 运行中{task_str}", style="bold green"))
        elif status == "updating":
            status_label.update(Text("🔄 更新中", style="bold yellow"))
        elif status == "error":
            status_label.update(Text("🔴 异常", style="bold red"))
        else:
            status_label.update(Text("⚪ 已停止", style="dim white"))

        emu_label = self.query_one("#emulator-info", Label)
        emu_label.update(f"模拟器: {self.serial} ({self.server.upper()})")

    def tick_clock(self) -> None:
        """定时更新右侧时钟。"""
        try:
            clock_label = self.query_one("#clock-label", Label)
            clock_label.update(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass

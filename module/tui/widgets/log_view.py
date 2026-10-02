"""TUI 实时日志滚屏面板组件。"""

from typing import Any, Dict, List

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Label, RichLog


class LogView(Widget):
    """实时日志滚屏视图。"""

    DEFAULT_CSS = """
    LogView {
        height: 1fr;
        background: $surface-darken-2;
        border: solid $primary-darken-2;
        padding: 0 1;
    }
    #log-header-bar {
        height: 3;
        align: left middle;
        border-bottom: solid $primary-darken-3;
        margin-bottom: 0;
    }
    #log-title {
        text-style: bold;
        color: $accent;
        margin-right: 2;
    }
    #log-cursor-info {
        color: $text-muted;
        margin-right: 2;
    }
    .log-ctrl-btn {
        margin-left: 1;
    }
    #rich-log-container {
        height: 1fr;
        background: #0d1117;
        color: #c9d1d9;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.auto_scroll_enabled: bool = True
        self.latest_cursor: int = 0

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="log-header-bar"):
                yield Label("📜 实时日志流", id="log-title")
                yield Label("序列号: 0", id="log-cursor-info")
                yield Button("自动滚屏: 开", id="btn-toggle-scroll", variant="default", classes="log-ctrl-btn")
                yield Button("清屏 [L]", id="btn-clear-log", variant="default", classes="log-ctrl-btn")
            yield RichLog(id="rich-log-container", highlight=True, markup=True, wrap=True)

    def write_entries(self, entries: List[Dict[str, Any]], cursor: int) -> None:
        """追加多条日志条目。"""
        if not entries:
            return

        rich_log = self.query_one("#rich-log-container", RichLog)
        for entry in entries:
            level = str(entry.get("level", "INFO")).upper()
            raw_text = str(entry.get("text") or entry.get("message", "")).rstrip()
            seq = entry.get("id") or entry.get("sequence", 0)

            # 根据级别着色
            line = Text()
            line.append(f"[{seq:04d}] ", style="dim")
            if "ERROR" in level or "CRITICAL" in level:
                line.append(f"{level:<5} ", style="bold white on red")
                line.append(f"│ {raw_text}", style="bold red")
            elif "WARN" in level:
                line.append(f"{level:<5} ", style="black on yellow")
                line.append(f"│ {raw_text}", style="yellow")
            elif "DEBUG" in level:
                line.append(f"{level:<5} ", style="dim cyan")
                line.append(f"│ {raw_text}", style="dim cyan")
            else:
                line.append(f"{level:<5} ", style="green")
                line.append(f"│ {raw_text}", style="bright_white")

            rich_log.write(line)

        self.latest_cursor = cursor
        cursor_label = self.query_one("#log-cursor-info", Label)
        cursor_label.update(f"最新序列: {self.latest_cursor}")

    def clear_log(self) -> None:
        """清空日志记录。"""
        rich_log = self.query_one("#rich-log-container", RichLog)
        rich_log.clear()

    def toggle_scroll(self) -> None:
        """切换自动滚动。"""
        self.auto_scroll_enabled = not self.auto_scroll_enabled
        btn = self.query_one("#btn-toggle-scroll", Button)
        btn.label = f"自动滚屏: {'开' if self.auto_scroll_enabled else '关'}"
        rich_log = self.query_one("#rich-log-container", RichLog)
        rich_log.auto_scroll = self.auto_scroll_enabled

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """工具栏按钮点击。"""
        if event.button.id == "btn-clear-log":
            self.clear_log()
        elif event.button.id == "btn-toggle-scroll":
            self.toggle_scroll()

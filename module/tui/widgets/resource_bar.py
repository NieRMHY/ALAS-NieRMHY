"""TUI 资源看板面板组件。"""

from typing import Any, Dict, List

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label


class ResourceBar(Widget):
    """游戏与大世界资源状态条。"""

    DEFAULT_CSS = """
    ResourceBar {
        height: 3;
        background: $surface-darken-1;
        border: solid $primary-darken-3;
        padding: 0 1;
    }
    #resource-container {
        width: 100%;
        height: 100%;
        align: left middle;
    }
    .res-item {
        margin-right: 3;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        with Horizontal(id="resource-container"):
            yield Label("📊 资源看板: 暂无数据", id="res-summary")

    def update_resources(self, resources: List[Dict[str, Any]]) -> None:
        """更新资源统计数据。"""
        summary_label = self.query_one("#res-summary", Label)
        if not resources:
            summary_label.update(Text("📊 资源看板: 暂无统计数据", style="dim"))
            return

        res_text = Text()
        res_text.append("📊 资源: ", style="bold cyan")
        for idx, res in enumerate(resources):
            label = res.get("label") or res.get("name", "")
            val = res.get("value")
            limit = res.get("limit")
            val_str = str(val) if val is not None else "-"
            if limit is not None:
                val_str += f"/{limit}"

            res_text.append(f"{label}: ", style="dim")
            res_text.append(f"{val_str}", style="bold cyan")
            if idx < len(resources) - 1:
                res_text.append("  │  ", style="dim")

        summary_label.update(res_text)

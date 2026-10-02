"""TUI 侧边栏组件。

包含实例列表选择与核心生命周期操作按钮。
"""

from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Label, OptionList
from textual.widgets.option_list import Option


class Sidebar(Widget):
    """侧边栏面板。"""

    DEFAULT_CSS = """
    Sidebar {
        width: 28;
        dock: left;
        background: $panel;
        border-right: solid $primary-darken-2;
        padding: 0 1;
    }
    #instances-title {
        text-style: bold;
        color: $accent;
        margin-top: 1;
        margin-bottom: 0;
    }
    #instance-list {
        height: 10;
        background: $surface;
        border: solid $primary-darken-3;
        margin-bottom: 1;
    }
    #actions-title {
        text-style: bold;
        color: $accent;
        margin-top: 1;
        margin-bottom: 1;
    }
    .action-btn {
        width: 100%;
        margin-bottom: 1;
    }
    #hint-label {
        color: $text-muted;
        margin-top: 1;
        text-align: center;
    }
    """

    class InstanceSelected(Message):
        """实例切换事件。"""

        def __init__(self, instance_name: str) -> None:
            super().__init__()
            self.instance_name = instance_name

    class ActionTriggered(Message):
        """控制操作事件。"""

        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.instance_names: List[str] = []
        self.current_selected: str = ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("📁 配置实例 (1-9)", id="instances-title")
            yield OptionList(id="instance-list")
            yield Label("⚡ 快捷操作", id="actions-title")
            yield Button("▶ 启动调度器", id="btn-start", variant="success", classes="action-btn")
            yield Button("⏹ 停止运行", id="btn-stop", variant="error", classes="action-btn")
            yield Button("⚙ 功能配置 [C]", id="btn-config", variant="primary", classes="action-btn")
            yield Button("🎯 单任务执行", id="btn-task", variant="default", classes="action-btn")
            yield Button("🔄 刷新状态", id="btn-refresh", variant="default", classes="action-btn")
            yield Label("[Space] 启动/停止\n[C] 配置  [E] 编辑任务\n[Enter] 开关任务", id="hint-label")

    def update_instances(self, instances: List[Dict[str, Any]], current: str) -> None:
        """更新实例列表。"""
        self.instance_names = [inst["name"] for inst in instances]
        self.current_selected = current
        option_list = self.query_one("#instance-list", OptionList)
        option_list.clear_options()

        current_idx = 0
        for idx, inst in enumerate(instances):
            name = inst["name"]
            status = inst.get("status", "stopped")
            if status == "running":
                icon = "🟢"
            elif status == "error":
                icon = "🔴"
            elif status == "updating":
                icon = "🔄"
            else:
                icon = "⚪"
            label = f"{idx + 1}. {icon} {name}"
            option_list.add_option(Option(prompt=label, id=name))
            if name == current:
                current_idx = idx

        if self.instance_names and current_idx < len(self.instance_names):
            option_list.highlighted = current_idx

    def update_button_states(self, is_running: bool) -> None:
        """根据当前运行状态更新按钮文案与可用性。"""
        start_btn = self.query_one("#btn-start", Button)
        stop_btn = self.query_one("#btn-stop", Button)
        if is_running:
            start_btn.disabled = True
            stop_btn.disabled = False
        else:
            start_btn.disabled = False
            stop_btn.disabled = True

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """实例列表选项被选中时触发。"""
        if event.option_id and event.option_id != self.current_selected:
            self.current_selected = str(event.option_id)
            self.post_message(self.InstanceSelected(self.current_selected))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """按钮点击事件处理。"""
        btn_id = event.button.id
        if btn_id == "btn-start":
            self.post_message(self.ActionTriggered("start"))
        elif btn_id == "btn-stop":
            self.post_message(self.ActionTriggered("stop"))
        elif btn_id == "btn-config":
            self.post_message(self.ActionTriggered("config"))
        elif btn_id == "btn-task":
            self.post_message(self.ActionTriggered("task"))
        elif btn_id == "btn-refresh":
            self.post_message(self.ActionTriggered("refresh"))

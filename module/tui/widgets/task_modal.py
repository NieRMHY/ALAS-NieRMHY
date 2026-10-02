"""TUI 单任务选择执行模态弹窗组件。"""

from typing import List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, OptionList
from textual.widgets.option_list import Option


class TaskModal(ModalScreen[Optional[str]]):
    """独立单任务选择运行模态窗口。"""

    DEFAULT_CSS = """
    TaskModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #modal-dialog {
        width: 60;
        height: 22;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    #modal-title {
        text-style: bold;
        color: $accent;
        text-align: center;
        margin-bottom: 1;
    }
    #modal-desc {
        color: $text-muted;
        margin-bottom: 1;
        text-align: center;
    }
    #task-option-list {
        height: 11;
        border: solid $primary-darken-3;
        background: $surface-darken-1;
        margin-bottom: 1;
    }
    #modal-button-box {
        height: 3;
        align: center middle;
    }
    .modal-btn {
        margin: 0 1;
        min-width: 14;
    }
    """

    def __init__(self, tasks: List[Tuple[str, str]]) -> None:
        super().__init__()
        self.tasks = tasks
        self.selected_task: Optional[str] = tasks[0][0] if tasks else None

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Label("🎯 选择要单独执行的任务功能", id="modal-title")
            yield Label("注意：单独运行任务将在当前实例中单次触发该功能", id="modal-desc")
            yield OptionList(id="task-option-list")
            with Horizontal(id="modal-button-box"):
                yield Button("▶ 立即执行", id="btn-confirm", variant="success", classes="modal-btn")
                yield Button("✕ 取消 [Esc]", id="btn-cancel", variant="default", classes="modal-btn")

    def on_mount(self) -> None:
        """初始化选项列表。"""
        option_list = self.query_one("#task-option-list", OptionList)
        for task_code, title in self.tasks:
            label = f"{title} ({task_code})" if title != task_code else task_code
            option_list.add_option(Option(prompt=label, id=task_code))
        if self.tasks:
            option_list.highlighted = 0

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """高亮选项变动。"""
        if event.option_id:
            self.selected_task = str(event.option_id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """回车直接确认执行。"""
        if event.option_id:
            self.dismiss(str(event.option_id))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """按钮点击。"""
        if event.button.id == "btn-confirm":
            self.dismiss(self.selected_task)
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def key_escape(self) -> None:
        """按 Esc 取消退出。"""
        self.dismiss(None)

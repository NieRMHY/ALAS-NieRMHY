"""TUI 任务时间表面板组件。"""

from typing import Any, Dict, List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Label


class TaskTable(Widget):
    """任务计划队列与时间表。"""

    class TaskToggleRequested(Message):
        """用户请求切换任务启用状态事件。"""

        def __init__(self, task_name: str) -> None:
            super().__init__()
            self.task_name = task_name

    class TaskEditRequested(Message):
        """用户请求编辑任务配置事件。"""

        def __init__(self, task_name: str) -> None:
            super().__init__()
            self.task_name = task_name

    DEFAULT_CSS = """
    TaskTable {
        height: 12;
        background: $surface;
        border: solid $primary-darken-2;
        padding: 0 1;
    }
    #task-table-title {
        text-style: bold;
        color: $accent;
        margin-top: 0;
        margin-bottom: 0;
    }
    #tasks-datatable {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.task_names: List[str] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("📋 任务计划时间表 ─ [Enter] 启闭任务  [E] 编辑详细参数", id="task-table-title")
            yield DataTable(id="tasks-datatable", cursor_type="row")

    def on_mount(self) -> None:
        """挂载时初始化表头。"""
        table = self.query_one("#tasks-datatable", DataTable)
        table.add_column("状态", width=12)
        table.add_column("任务名称", width=26)
        table.add_column("计划执行时间", width=22)

    def update_tasks(self, tasks: List[Dict[str, Any]]) -> None:
        """更新任务计划列表。"""
        table = self.query_one("#tasks-datatable", DataTable)
        current_cursor = table.cursor_row
        table.clear()
        self.task_names.clear()

        if not tasks:
            table.add_row(
                Text("-", style="dim"),
                Text("暂无启用的任务计划", style="dim italic"),
                Text("-", style="dim"),
            )
            return

        for task in tasks:
            name = task.get("name", "")
            self.task_names.append(name)
            title = task.get("title", name)
            display_name = f"{title} ({name})" if title != name else name
            next_run = task.get("nextRun", "")
            time_display = next_run.replace("T", " ")[:19] if next_run else "-"

            state = task.get("state", "waiting")
            is_pending = task.get("pending", False)

            if state == "running":
                status_cell = Text("🟢 运行中", style="bold green")
                name_cell = Text(display_name, style="bold green")
            elif is_pending or state == "pending":
                status_cell = Text("🟡 待执行", style="bold yellow")
                name_cell = Text(display_name, style="yellow")
            else:
                status_cell = Text("⚪ 等待中", style="dim")
                name_cell = Text(display_name, style="white")

            table.add_row(status_cell, name_cell, Text(time_display, style="cyan" if is_pending else "white"), key=name)

        # 尽量恢复之前的光标位置
        if current_cursor is not None and 0 <= current_cursor < len(self.task_names):
            table.move_cursor(row=current_cursor)

    def get_selected_task(self) -> Optional[str]:
        """获取当前光标选中的任务代码。"""
        table = self.query_one("#tasks-datatable", DataTable)
        if table.cursor_row is not None and 0 <= table.cursor_row < len(self.task_names):
            return self.task_names[table.cursor_row]
        return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """用户在某一行回车时，派发启闭该任务的请求。"""
        selected_task = self.get_selected_task()
        if selected_task:
            self.post_message(self.TaskToggleRequested(selected_task))

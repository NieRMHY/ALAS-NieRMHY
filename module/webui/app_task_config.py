"""WebUI任务菜单和配置表单"""

from html import escape
from typing import cast

import module.webui.lang as lang
from module.webui.app_dependencies import (
    Any,
    clear,
    Dict,
    List,
    Optional,
    Output,
    State,
    T_Output_Kwargs,
    current_time,
    datetime,
    deep_get,
    deep_iter,
    deep_set,
    dict_to_kv,
    filepath_config,
    get_device_id,
    logger,
    os,
    parse_pin_value,
    pin,
    pin_on_change,
    popup,
    put_button,
    put_buttons,
    put_collapse,
    put_html,
    put_input,
    put_none,
    put_output,
    put_row,
    put_scope,
    put_text,
    queue,
    re_fullmatch,
    run_js,
    t,
    to_pin_value,
    to_server,
    toast,
    updater,
    use_scope,
)

from module.webui.app_helpers import (
    DEMO_DEVICE_ID_TEXT,
    build_copyable_device_id,
    is_demo_mode,
)
from module.webui.config_search import (
    ConfigSearchEntry,
    build_config_search_result_click_script,
    build_config_search_focus_script,
    config_search_config_signature,
    config_search_field_scope,
    search_config_entries,
    should_render_config_argument,
)


from module.webui.app_types import WebUIMixinBase


class TaskConfigMixin(WebUIMixinBase):
    """WebUI任务菜单和配置表单"""

    CONFIG_SEARCH_PIN = "config_search_keyword"
    CONFIG_SEARCH_SELECTION_PIN = "config_search_selection"
    CONFIG_SEARCH_RESULT_LIMIT = 20

    @use_scope("menu", clear=True)
    def alas_set_menu(self) -> None:
        """渲染任务菜单及配置搜索入口。"""
        put_scope("task_config_search")
        put_scope("task_config_search_results")
        put_scope("task_config_menu_items")
        self._render_config_search_control()
        self._render_task_menu_items()
        self.alas_overview()

    @use_scope("task_config_menu_items", clear=True)
    def _render_task_menu_items(self) -> None:
        """渲染未搜索时的完整任务菜单。"""
        put_buttons(
            [
                {
                    "label": t("Gui.MenuAlas.Overview"),
                    "value": "Overview",
                    "color": "menu",
                }
            ],
            onclick=[self.alas_overview],
        ).style(f"--menu-Overview--")

        for menu, task_data in self.ALAS_MENU.items():
            if task_data.get("page") == "tool":
                _onclick = self.alas_daemon_overview
            else:
                _onclick = self.alas_set_group

            if task_data.get("menu") == "collapse":
                task_btn_list = []
                for task in task_data.get("tasks", []):
                    onclick = _onclick
                    if menu == "FleetManagement":
                        onclick = {
                            "FleetScan": self.fleet_scan_page,
                            "FleetInfo": self.fleet_info_page,
                        }.get(task, _onclick)
                    task_btn_list.append(
                        put_buttons(
                            [
                                {
                                    "label": t(f"Task.{task}.name"),
                                    "value": task,
                                    "color": "menu",
                                }
                            ],
                            onclick=onclick,
                        ).style(f"--menu-{task}--")
                    )
                put_collapse(title=t(f"Menu.{menu}.name"), content=task_btn_list)
            else:
                title = t(f"Menu.{menu}.name")
                put_html(
                    '<div class="hr-task-group-box">'
                    '<span class="hr-task-group-line"></span>'
                    f'<span class="hr-task-group-text">{title}</span>'
                    '<span class="hr-task-group-line"></span>'
                    "</div>"
                )
                for task in task_data.get("tasks", []):
                    onclick = _onclick
                    if menu == "FleetManagement":
                        onclick = {
                            "FleetScan": self.fleet_scan_page,
                            "FleetInfo": self.fleet_info_page,
                        }.get(task, _onclick)
                    put_buttons(
                        [
                            {
                                "label": t(f"Task.{task}.name"),
                                "value": task,
                                "color": "menu",
                            }
                        ],
                        onclick=onclick,
                    ).style(f"--menu-{task}--").style(f"padding-left: 0.75rem")

    @use_scope("task_config_search", clear=True)
    def _render_config_search_control(self) -> None:
        """渲染搜索输入框，并注册不参与配置保存的实时回调。"""
        put_input(
            name=self.CONFIG_SEARCH_PIN,
            value="",
            placeholder=t("Gui.TaskConfig.SearchPlaceholder"),
        ).style("--task-config-search-input--")
        put_input(name=self.CONFIG_SEARCH_SELECTION_PIN, value="")
        if not getattr(self, "_config_search_callbacks_bound", False):
            pin_on_change(
                name=self.CONFIG_SEARCH_PIN,
                onchange=self._on_config_search_change,
                clear=True,
                serial_mode=True,
            )
            pin_on_change(
                name=self.CONFIG_SEARCH_SELECTION_PIN,
                onchange=self._on_config_search_result,
                clear=True,
                serial_mode=True,
            )
            self._config_search_callbacks_bound = True
        run_js(build_config_search_result_click_script(self.CONFIG_SEARCH_SELECTION_PIN))
        self._get_config_search_entries()

    def _on_config_search_change(self, value: Any) -> None:
        """根据输入值重绘搜索结果，不触碰实例配置。"""
        self._render_config_search_results(str(value or ""))

    def _on_config_search_result(self, key: Any) -> None:
        """仅允许打开当前仍可见的搜索结果。"""
        for entry in self._get_config_search_entries():
            if entry.key == str(key):
                self._open_config_search_result(entry)
                return

    @use_scope("task_config_search_results", clear=True)
    def _render_config_search_results(self, query: str) -> None:
        """显示匹配项，或在清空查询后恢复任务菜单。"""
        if not query.strip():
            self._render_task_menu_items()
            return

        clear("task_config_menu_items")
        results, total = search_config_entries(
            self._get_config_search_entries(),
            query,
            limit=self.CONFIG_SEARCH_RESULT_LIMIT,
        )
        if not results:
            put_text(t("Gui.TaskConfig.SearchNoResult")).style(
                "--task-config-search-empty--"
            )
            return

        put_text(t("Gui.TaskConfig.SearchResultCount", count=total)).style(
            "--task-config-search-count--"
        )
        for entry in results:
            self._put_config_search_result(entry)

    def _put_config_search_result(self, entry: ConfigSearchEntry) -> None:
        """渲染一个可点击的配置搜索结果。"""
        help_text = " ".join(entry.help_text.split())
        if len(help_text) > 88:
            help_text = help_text[:87].rstrip() + "..."
        help_html = (
            f'<span class="config-search-result-help">{escape(help_text)}</span>'
            if help_text
            else ""
        )
        put_html(
            '<button class="config-search-result" type="button" '
            f'data-config-search-key="{escape(entry.key)}">'
            f'<span class="config-search-result-name">{escape(entry.argument_name)}</span>'
            f'<span class="config-search-result-path">{escape(entry.task_name)} &gt; '
            f"{escape(entry.group_name)}</span>"
            f'<span class="config-search-result-key">{escape(entry.key)}</span>'
            f"{help_html}"
            "</button>"
        )

    def _open_config_search_result(self, entry: ConfigSearchEntry) -> None:
        """打开结果所在任务，并定位到对应的参数容器。"""
        self.alas_set_group(entry.task)
        run_js(
            build_config_search_focus_script(
                config_search_field_scope(entry.task, entry.group, entry.argument)
            )
        )

    def _get_config_search_entries(self) -> List[ConfigSearchEntry]:
        """按当前实例和服务器返回可见参数的内存索引。"""
        config = self.alas_config.read_file(self.alas_name)
        package_name = deep_get(config, "Alas.Emulator.PackageName", "cn")
        signature = (
            self.alas_name,
            self.alas_mod,
            lang.LANG,
            package_name,
            id(self.ALAS_ARGS),
            config_search_config_signature(config),
        )
        if getattr(self, "_config_search_signature", None) != signature:
            self._config_search_entries = self._build_config_search_entries(config)
            self._config_search_signature = signature
        return self._config_search_entries

    def _invalidate_config_search_cache(self) -> None:
        """在配置写入后丢弃可能已经过期的可见参数索引。"""
        self._config_search_entries = []
        self._config_search_signature = None

    def _build_config_search_entries(
        self, config: Dict[str, Any]
    ) -> List[ConfigSearchEntry]:
        """从当前菜单中实际可显示的参数构建搜索索引。"""
        entries: List[ConfigSearchEntry] = []
        seen_tasks = set()
        for task_data in self.ALAS_MENU.values():
            if task_data.get("page") != "setting":
                continue
            for task in task_data.get("tasks", []):
                if task in seen_tasks or task not in self.ALAS_ARGS:
                    continue
                seen_tasks.add(task)
                task_name = self._translated_text(f"Task.{task}.name", task)
                for group, group_args in deep_iter(self.ALAS_ARGS[task], depth=1):
                    group_name = group[0]
                    display_group_name = self._translated_text(
                        f"{group_name}._info.name", group_name
                    )
                    for arg_name, _, _, output_kwargs in self._iter_group_arguments(
                        task, group_name, group_args, config
                    ):
                        entries.append(
                            ConfigSearchEntry(
                                task=task,
                                group=group_name,
                                argument=arg_name,
                                task_name=task_name,
                                group_name=display_group_name,
                                argument_name=str(output_kwargs["title"]),
                                help_text=str(output_kwargs.get("help") or ""),
                            )
                        )
        return entries

    @staticmethod
    def _translated_text(key: str, fallback: str) -> str:
        """读取翻译，并在翻译缺失时保留技术名称作为可搜索回退。"""
        translated = t(key)
        return fallback if translated == key else translated

    def _iter_group_arguments(
        self,
        task: str,
        group_name: str,
        group_args: Dict[str, Any],
        config: Dict[str, Any],
    ):
        """解析当前服务器下会渲染的参数，并供表单与搜索索引共享。"""
        package_name = deep_get(config, "Alas.Emulator.PackageName", "cn")
        server = to_server(package_name if isinstance(package_name, str) else "cn")
        for arg, arg_definition in deep_iter(group_args, depth=1):
            if not isinstance(arg_definition, dict):
                continue

            arg_name = arg[0]
            output_kwargs: T_Output_Kwargs = arg_definition.copy()
            display: Optional[str] = output_kwargs.pop("display", None)
            widget_type = output_kwargs.pop("type")
            output_kwargs["widget_type"] = widget_type
            if display == "disabled":
                output_kwargs["disabled"] = True

            value = deep_get(
                config, [task, group_name, arg_name], output_kwargs["value"]
            )
            # datetime 控件只能接收文本，避免 Pin 在重绘时丢失原始时间值。
            value = str(value) if isinstance(value, datetime) else value
            output_kwargs["value"] = value

            options = output_kwargs.pop("option", [])
            available_events = deep_get(
                self.ALAS_ARGS, keys=f"{task}.{group_name}.{arg_name}.option_{server}"
            )
            if available_events is not None:
                options = [opt for opt in options if opt in available_events]
            server_options = output_kwargs.get(f"option_{server}")
            if (
                widget_type == "select"
                and isinstance(server_options, list)
                and server_options
            ):
                options = server_options
            output_kwargs["options"] = options

            if not should_render_config_argument(
                task,
                group_name,
                arg_name,
                display,
                widget_type,
                options,
                value,
            ):
                continue

            if widget_type == "select" and len(options) == 1:
                only_option = options[0]
                if only_option in output_kwargs.get("option_bold", []):
                    output_kwargs["widget_type"] = "state"
            output_kwargs["name"] = f"{task}_{group_name}_{arg_name}"
            output_kwargs["title"] = self._translated_text(
                f"{group_name}.{arg_name}.name", arg_name
            )
            output_kwargs["options_label"] = [
                t(f"{group_name}.{arg_name}.{opt}") for opt in options
            ]
            arg_help = t(f"{group_name}.{arg_name}.help")
            output_kwargs["help"] = arg_help or None
            yield arg_name, display, widget_type, output_kwargs

    @use_scope("content", clear=True)
    def alas_set_group(self, task: str) -> None:
        """
        Set arg groups from dict
        """
        config = self.alas_config.read_file(self.alas_name)
        self.init_menu(name=task)
        self.set_title(t(f"Task.{task}.name"))

        group_outputs: List[Output] = []
        navigator_outputs: List[Output] = []
        watcher_paths: List[List[str]] = []
        render_event_calculator = False

        task_help: str = t(f"Task.{task}.help")
        if task_help:
            group_outputs.append(
                put_scope(
                    "group__info",
                    content=[put_text(task_help).style("font-size: 1rem")],
                )
            )

        if task == "Alas":
            group_outputs.append(put_scope("group_StartupRun"))

        if task == "OpsiSimulator":
            group_outputs.append(put_scope("group_OpsiSimulatorRuntime"))

        for group, arg_dict in deep_iter(self.ALAS_ARGS[task], depth=1):
            group_output, group_watcher_paths, _ = self._build_config_group(
                group, arg_dict, config, task
            )
            if group_output is not None:
                group_outputs.append(group_output)
                navigator_outputs.append(self._build_navigator(group))
                watcher_paths.extend(group_watcher_paths)
                if task == "EventGeneral" and group[0] == "EventGeneral":
                    group_outputs.append(put_scope("group_EventCalculator"))
                    render_event_calculator = True

        # PyWebIO 的每个独立 output 都会形成一条 WebSocket 指令。将整个配置页
        # 作为嵌套 Output 一次发送，避免数十个控件触发数百次网络往返和重复布局。
        put_scope(
            "_groups",
            [
                put_none(),
                put_scope("groups", group_outputs),
                put_scope("navigator", navigator_outputs),
            ],
        )

        for path in watcher_paths:
            self._bind_config_watcher(path)

        # 依赖已有 DOM scope 或需要执行脚本的特殊区域，在基础配置页落地后再初始化。
        if task == "Alas":
            with use_scope("group_StartupRun"):
                self._render_startup_run_setting()
        elif task == "OpsiSimulator":
            with use_scope("group_OpsiSimulatorRuntime"):
                self._os_simulator()
        elif render_event_calculator:
            self._render_event_calculator(config)

    def _build_config_group(
        self,
        group,
        arg_dict,
        config: Dict[str, Any],
        task: str,
    ) -> tuple[Optional[Output], List[List[str]], int]:
        """构建一个配置分组，延迟到外层页面统一发送。"""
        group_name = group[0]

        output_list: List[tuple[str, Output]] = []
        watcher_paths: List[List[str]] = []
        for (
            arg_name,
            display,
            widget_type,
            resolved_kwargs,
        ) in self._iter_group_arguments(task, group_name, arg_dict, config):
            output_kwargs = resolved_kwargs.copy()
            if group_name == "Scheduler" and arg_name == "NextRun":
                # 立即运行按钮：清空 NextRun 触发调度器立即执行该任务
                run_now_path = f"{task}.Scheduler.NextRun"

                def _run_now(_path=run_now_path):
                    self.modified_config_queue.put({"name": _path, "value": ""})
                    toast(t("Gui.Text.RunNow"))

                run_now_btn = put_html(
                    f'<a href="javascript:void(0)" '
                    f'style="font-size: .75rem; cursor: pointer;">'
                    f'{t("Gui.Text.RunNow")}</a>'
                ).onclick(_run_now)
                output_kwargs["after"] = put_row(
                    [
                        run_now_btn,
                        put_text(self._time_status_text()).style(
                            "font-size: .75rem; opacity: .68;"
                        ),
                    ],
                    size="auto 1fr",
                ).style("margin: .2rem .25rem 0; gap: .5rem;")
            output_kwargs["invalid_feedback"] = t(
                "Gui.Text.InvalidFeedBack", output_kwargs["value"]
            )

            o = put_output(output_kwargs)
            if o is not None:
                output_list.append((arg_name, o))
                if display != "readonly" and widget_type != "stored":
                    watcher_paths.append([task, group_name, arg_name])

        if not output_list:
            return None, [], 0

        content: List[Output] = [put_text(t(f"{group_name}._info.name"))]
        group_help = t(f"{group_name}._info.help")
        if group_help != "":
            content.append(put_text(group_help))
        content.append(put_html('<hr class="hr-group">'))

        for arg_name, output in output_list:
            field_scope = config_search_field_scope(task, group_name, arg_name)
            content.append(put_scope(field_scope, content=[output]))

        # 在掉落记录组中显示可复制的设备ID
        if group_name == "DropRecord":
            device_id = DEMO_DEVICE_ID_TEXT if is_demo_mode() else get_device_id()
            content.append(put_html(build_copyable_device_id(device_id)))

        return (
            put_scope(f"group_{group_name}", content=content),
            watcher_paths,
            len(output_list),
        )

    @use_scope("groups")
    def set_group(self, group, arg_dict, config: Dict[str, Any], task: str) -> int:
        """兼容总览页：单独构建并发送一个配置分组。"""
        group_output, watcher_paths, output_count = self._build_config_group(
            group, arg_dict, config, task
        )
        if group_output is None:
            return 0

        group_output.show()
        for path in watcher_paths:
            self._bind_config_watcher(path)
        return output_count

    def _build_navigator(self, group) -> Output:
        """构建分组导航按钮，供配置页统一批量输出。"""
        js = f"""
            $("#pywebio-scope-groups").scrollTop(
                $("#pywebio-scope-group_{group[0]}").position().top
                + $("#pywebio-scope-groups").scrollTop() - 59
            )
        """
        return put_button(
            label=t(f"{group[0]}._info.name"),
            onclick=lambda: run_js(js),
            color="navigator",
        )

    @use_scope("navigator")
    def set_navigator(self, group):
        self._build_navigator(group).show()

    def _alas_start(self):
        self.alas.start(None, updater.event)

    def _simulator_start(self):
        if is_demo_mode():
            logger.info("[WebUI] DEMO=1，跳过大世界模拟器启动。")
            return
        self.simulator.start()

    def _bind_config_watcher(self, path: List[str]) -> None:
        """为已渲染的配置控件注册一次变更监听。"""
        pin_name = "_".join(path)
        watcher_pins = getattr(self, "_config_watcher_pins", None)
        if watcher_pins is None:
            watcher_pins = set()
            self._config_watcher_pins = watcher_pins
        if pin_name in watcher_pins:
            return

        path_text = ".".join(path)

        def put_queue(value: Any) -> None:
            self.modified_config_queue.put({"name": path_text, "value": value})

        pin_on_change(name=pin_name, onchange=put_queue)
        watcher_pins.add(pin_name)

    def _alas_thread_update_config(self) -> None:
        modified = {}
        while self.alive:
            try:
                d = self.modified_config_queue.get(timeout=10)
                config_name = self.alas_name
                config_updater = self.alas_config
            except queue.Empty:
                continue
            modified[d["name"]] = d["value"]
            while True:
                try:
                    d = self.modified_config_queue.get(timeout=1)
                    modified[d["name"]] = d["value"]
                except queue.Empty:
                    self._save_config(modified, config_name, config_updater)
                    modified.clear()
                    break

    def _save_config(
        self,
        modified: Dict[str, Any],
        config_name: str,
        config_updater: Any = State.config_updater,
    ) -> None:
        if os.environ.get("DEMO") == "1":
            return

        try:
            skip_time_record = False
            valid = []
            invalid = []
            config = config_updater.read_file(config_name)
            n = current_time()
            for p, v in deep_iter(config, depth=3):
                if p[-1].endswith("un") and not isinstance(v, bool):
                    if (v - n).days >= 31:
                        deep_set(config, p, "")
            for k, v in modified.copy().items():
                arg_def = deep_get(self.ALAS_ARGS, k, {})
                valuetype = (
                    arg_def.get("valuetype") if isinstance(arg_def, dict) else None
                )
                widget_type = arg_def.get("type") if isinstance(arg_def, dict) else None
                options = arg_def.get("option") if isinstance(arg_def, dict) else None
                # YAML 参数定义允许省略类型；运行时解析器会处理 None，
                # 这里保留原行为并向类型检查器声明该动态边界。
                v = parse_pin_value(
                    v, cast(str, valuetype), cast(str, widget_type), options
                )
                validate = deep_get(self.ALAS_ARGS, k + ".validate")
                if not len(str(v)):
                    default = deep_get(self.ALAS_ARGS, k + ".value")
                    modified[k] = default
                    deep_set(config, k, default)
                    valid.append(k)
                    pin["_".join(k.split("."))] = default

                elif not validate or re_fullmatch(validate, v):
                    deep_set(config, k, v)
                    modified[k] = v
                    valid.append(k)
                    for set_key, set_value in config_updater.save_callback(k, v):
                        modified[set_key] = set_value
                        deep_set(config, set_key, set_value)
                        valid.append(set_key)
                        pin["_".join(set_key.split("."))] = to_pin_value(set_value)
                    # ==================== 自定义弹窗逻辑 ====================
                    # 当保存侵蚀1兑换凭证保留值为 0 时弹出提示
                    try:
                        is_zero_preserve = int(cast(Any, v)) == 0
                    except (TypeError, ValueError):
                        is_zero_preserve = False
                    if (
                        k
                        in [
                            "OpsiHazard1Leveling.OpsiHazard1Leveling.OperationCoinsPreserve",
                            "OpsiScheduling.OpsiScheduling.OperationCoinsPreserve",
                        ]
                        and is_zero_preserve
                    ):
                        from pywebio.output import popup, put_html, PopupSize

                        popup(
                            "配置提示",
                            [
                                put_html(
                                    '<div style="line-height:1.8;font-size:14px;">'
                                    "保留黄币数量设为 0 可能导致黄币耗尽，无法在猫商店购买行动力箱子，行动力链条断裂。以下为侵蚀1（71）玩法的配置说明：<br><br>"
                                    "1. 收益：经验与金菜金材料。每 10 万黄币约 73 万经验（单个角色无心情加成）；账号进入游戏末期后经验溢出，收益体现为每 10 万黄币约 9.36 金菜。石油可通过 2-4 刷委托获得经验、物资、魔方、金菜、钻石等资源<br>"
                                    "2. 收益来源：黄币是基础，行动力是催化剂。71 大量消耗黄币获取行动力，短猫消耗多余行动力补充黄币，二者相辅相成，Alas 自动维持动态平衡。20 小时 71 消耗约 10 万黄币、多产出 884 行动力，再短猫 4 小时返还约 3.5 万黄币。每月黄币获取有限，71 收益亦有限<br>"
                                    "3. 前提：先完成大世界每日商店、深渊、隐秘海域等任务获取金彩材料，用多余黄币运行 71，否则本末倒置<br>"
                                    "4. 不要购买紫币：紫币主要来源是要塞，白票主要来源是月度 Boss。大世界使用 Alas 全勤时紫币白票不缺；猫商店紫币多 20% 是多 20% 白票，但 71 中白票价值体系作废，一切用黄币衡量，买紫币等于用稀缺资源兑换溢出资源<br>"
                                    "5. 71 本质：消耗 5 行动力赌 5% 猫商店刷新（外加两个装置各 4%，其一拆解可返还部分行动力），无保底机制，数学期望为正但存在波动。1000 行动力本金约 90% 概率不翻车，2000 约 98%，再高边际效应递减<br>"
                                    "6. 建议行动力买满，留有回旋余地。1 万石油投入 71 的产出高于主线图一个数量级<br>"
                                    "7. 开启 71 后 Alas 运行逻辑变化：黄币与行动力动态平衡、全局不买紫币、最少保留 100 行动力确保每日任务、月初用行动力完成隐秘海域/深渊/要塞防止溢出、月底停 71 防止浪费"
                                    "</div>"
                                )
                            ],
                            size=PopupSize.LARGE,
                        )
                    # ========================================================
                else:
                    modified.pop(k)
                    invalid.append(k)
                    logger.warning(f"[WebUI-任务配置] 无效值 {v}，键 {k}，跳过保存")
            self.pin_remove_invalid_mark(valid)
            self.pin_set_invalid_mark(invalid)
            if modified:
                toast(
                    t("Gui.Toast.ConfigSaved"),
                    duration=1,
                    position="right",
                    color="success",
                )
                logger.info(
                    f"[WebUI-任务配置] 保存配置 {filepath_config(config_name)}, {dict_to_kv(modified)}"
                )
                config_updater.write_file(config_name, config)
                self._invalidate_config_search_cache()
        except Exception as e:
            logger.exception(e)

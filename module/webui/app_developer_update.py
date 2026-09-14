"""WebUI更新和启动项设置"""

from module.webui.app_dependencies import (
    DEFAULT_CONFIG_NAME,
    State,
    Switch,
    clear,
    json,
    put_button,
    put_html,
    put_loading,
    put_row,
    put_scope,
    put_table,
    put_text,
    put_warning,
    re,
    run_js,
    t,
    updater,
    use_scope,
)


from module.webui.app_types import WebUIMixinBase


class DeveloperUpdateMixin(WebUIMixinBase):
    """WebUI更新和启动项设置"""

    # 更新器页面的全部 scope 名，供幽灵节点清理复用
    UPDATER_SCOPES = (
        "updater_info",
        "updater_loading",
        "updater_state",
        "updater_btn",
        "updater_table",
        "updater_detail",
    )

    @staticmethod
    def remove_stale_updater_scopes() -> None:
        """清除落在 content 之外的 updater_* scope 残留。

        后台 switch 任务在页面切走后仍会跑完当前一轮，此时这些 scope 已随
        content 一起被清空；PyWebIO 的 set_scope(if_exist='blank') 在前端找不到
        元素时，会把新 scope 追加到调用线程的当前 scope（任务线程只有 ROOT），
        于是在 #pywebio-scope-ROOT 下留下幽灵节点：既让下次 put_scope 撞名
        （前端渲染“scope 名称重复”灰条），又作为 ROOT 网格的额外一行把应用
        外壳挤扁、内容跑到 content 之外。渲染前清理一次，保证本页 DOM 干净。

        Pages: in: page_update
        """
        run_js(
            """
            (function () {
                var content = document.getElementById("pywebio-scope-content");
                if (!content) return;
                names.forEach(function (name) {
                    var el = document.getElementById("pywebio-scope-" + name);
                    if (el && el.parentNode && !content.contains(el)) {
                        el.parentNode.removeChild(el);
                    }
                });
            })();
            """,
            names=list(DeveloperUpdateMixin.UPDATER_SCOPES),
        )

    @use_scope("content", clear=True)
    def dev_update(self) -> None:
        self.init_menu(name="Update")
        self.set_title(t("Gui.MenuDevelop.Update"))
        self.remove_stale_updater_scopes()

        put_scope("updater_info")
        with use_scope("updater_info"):
            if State.restart_event is None:
                put_warning(t("Gui.Update.DisabledWarn"))

            put_row(
                content=[
                    put_scope("updater_loading"),
                    None,
                    put_scope("updater_state"),
                ],
                size="auto .25rem 1fr",
            )

            put_scope("updater_btn")
            put_scope("updater_table")
        put_scope("updater_detail")

        def update_table():
            """刷新提交表格；页面已切走时直接放弃，避免写出幽灵 scope。"""
            if self.page != "Update":
                return
            with use_scope("updater_table", clear=True):
                local_commit = updater.get_commit(short_sha1=True)
                upstream_commit = updater.get_commit(
                    f"origin/{updater.Branch}", short_sha1=True
                )
                put_table(
                    [
                        [t("Gui.Update.Local"), *local_commit],
                        [t("Gui.Update.Upstream"), *upstream_commit],
                    ],
                    header=[
                        "",
                        "SHA1",
                        t("Gui.Update.Author"),
                        t("Gui.Update.Time"),
                        t("Gui.Update.Message"),
                    ],
                )
            # 两次 get_commit 是 git 子进程，期间用户可能已切页；这里再判一次，
            # 否则 set_scope 会在 ROOT 下创建幽灵 updater_detail。
            if self.page != "Update":
                return
            with use_scope("updater_detail", clear=True):
                put_text(t("Gui.Update.DetailedHistory"))
                history = updater.get_commit(
                    f"origin/{updater.Branch}", n=20, short_sha1=True
                )
                put_table(
                    [commit for commit in history],
                    header=[
                        "SHA1",
                        t("Gui.Update.Author"),
                        t("Gui.Update.Time"),
                        t("Gui.Update.Message"),
                    ],
                )

        def u(state):
            # 后台 switch 在本页卸载后仍会跑完当前一轮，必须放弃写 DOM
            if state == -1 or self.page != "Update":
                return
            clear("updater_loading")
            clear("updater_state")
            clear("updater_btn")
            if state == 0:
                put_loading("border", "secondary", "updater_loading").style(
                    "--loading-border-fill--"
                )
                put_text(t("Gui.Update.UpToDate"), scope="updater_state")
                put_button(
                    t("Gui.Button.CheckUpdate"),
                    onclick=updater.check_update,
                    color="info",
                    scope="updater_btn",
                )
                update_table()
            elif state == 1:
                put_loading("grow", "success", "updater_loading").style(
                    "--loading-grow--"
                )
                put_text(t("Gui.Update.HaveUpdate"), scope="updater_state")
                put_button(
                    t("Gui.Button.ClickToUpdate"),
                    onclick=updater.run_update,
                    color="success",
                    scope="updater_btn",
                )
                update_table()
            elif state == "checking":
                put_loading("border", "primary", "updater_loading").style(
                    "--loading-border--"
                )
                put_text(t("Gui.Update.UpdateChecking"), scope="updater_state")
            elif state == "failed":
                put_loading("grow", "danger", "updater_loading").style(
                    "--loading-grow--"
                )
                put_text(t("Gui.Update.UpdateFailed"), scope="updater_state")
                put_button(
                    t("Gui.Button.RetryUpdate"),
                    onclick=updater.run_update,
                    color="primary",
                    scope="updater_btn",
                )
            elif state == "start":
                put_loading("border", "primary", "updater_loading").style(
                    "--loading-border--"
                )
                put_text(t("Gui.Update.UpdateStart"), scope="updater_state")
                put_button(
                    t("Gui.Button.CancelUpdate"),
                    onclick=updater.cancel,
                    color="danger",
                    scope="updater_btn",
                )
            elif state == "wait":
                put_loading("border", "primary", "updater_loading").style(
                    "--loading-border--"
                )
                put_text(t("Gui.Update.UpdateWait"), scope="updater_state")
                put_button(
                    t("Gui.Button.CancelUpdate"),
                    onclick=updater.cancel,
                    color="danger",
                    scope="updater_btn",
                )
            elif state == "run update":
                put_loading("border", "primary", "updater_loading").style(
                    "--loading-border--"
                )
                put_text(t("Gui.Update.UpdateRun"), scope="updater_state")
                put_button(
                    t("Gui.Button.CancelUpdate"),
                    onclick=updater.cancel,
                    color="danger",
                    scope="updater_btn",
                    disabled=True,
                )
            elif state == "reload":
                put_loading("grow", "success", "updater_loading").style(
                    "--loading-grow--"
                )
                put_text(t("Gui.Update.UpdateSuccess"), scope="updater_state")
                update_table()
            elif state == "finish":
                put_loading("grow", "success", "updater_loading").style(
                    "--loading-grow--"
                )
                put_text(t("Gui.Update.UpdateFinish"), scope="updater_state")
                update_table()
            elif state == "cancel":
                put_loading("border", "danger", "updater_loading").style(
                    "--loading-border--"
                )
                put_text(t("Gui.Update.UpdateCancel"), scope="updater_state")
                put_button(
                    t("Gui.Button.CancelUpdate"),
                    onclick=updater.cancel,
                    color="danger",
                    scope="updater_btn",
                    disabled=True,
                )
            else:
                put_text(
                    "Something went wrong, please contact develops",
                    scope="updater_state",
                )
                put_text(f"state: {state}", scope="updater_state")

        updater_switch = Switch(
            status=u, get_state=lambda: updater.state, name="updater"
        )

        update_table()
        self.task_handler.add(updater_switch.g(), delay=0.5, pending_delete=True)

        updater.check_update()

    def _render_startup_run_setting(self) -> None:
        instance = self.alas_name or DEFAULT_CONFIG_NAME
        scope_id = re.sub(r"[^0-9A-Za-z_]", "_", instance)
        switch_id = f"startup-run-switch-{scope_id}"
        status_id = f"startup-run-status-{scope_id}"
        put_html(
            f"""
            <div class="startup-run-panel">
              <div class="startup-run-row">
                <div>
                  <div class="startup-run-title">{t("Gui.StartupRun.Title")}</div>
                  <div class="startup-run-desc">{t("Gui.StartupRun.Description")}</div>
                </div>
                <label class="launcher-switch" title="{t("Gui.StartupRun.Title")}">
                  <input id="{switch_id}" type="checkbox" disabled>
                </label>
              </div>
              <div id="{status_id}" class="startup-run-status">{t("Gui.StartupRun.Loading")}</div>
            </div>
            """
        )
        run_js(
            f"""
            (function(){{
              const instance = {json.dumps(instance)};
              const switchEl = document.getElementById({json.dumps(switch_id)});
              const statusEl = document.getElementById({json.dumps(status_id)});
              const text = {{
                loading: {json.dumps(t("Gui.StartupRun.Loading"))},
                enabled: {json.dumps(t("Gui.StartupRun.Enabled"))},
                disabled: {json.dumps(t("Gui.StartupRun.Disabled"))},
                setting: {json.dumps(t("Gui.StartupRun.Setting"))},
                failed: {json.dumps(t("Gui.StartupRun.Failed"))},
                unavailable: {json.dumps(t("Gui.StartupRun.Unavailable"))}
              }};

              async function refresh() {{
                switchEl.disabled = true;
                statusEl.textContent = text.loading;
                try {{
                  const resp = await fetch('/api/deploy/startup-run?instance=' + encodeURIComponent(instance), {{cache: 'no-store'}});
                  const result = await resp.json();
                  if (!result.success) {{
                    throw new Error(result.error || 'unknown error');
                  }}
                  switchEl.checked = result.data.enabled === true;
                  switchEl.disabled = false;
                  statusEl.textContent = result.data.enabled ? text.enabled : text.disabled;
                }} catch (err) {{
                  statusEl.textContent = text.unavailable + ': ' + (err.message || err);
                }}
              }}

              switchEl.addEventListener('change', async function() {{
                const target = switchEl.checked;
                switchEl.disabled = true;
                statusEl.textContent = text.setting;
                try {{
                  const resp = await fetch('/api/deploy/startup-run', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{instance, enabled: target}})
                  }});
                  const result = await resp.json();
                  if (!result.success) {{
                    throw new Error(result.error || 'unknown error');
                  }}
                  switchEl.checked = result.data.enabled === true;
                  statusEl.textContent = result.data.enabled ? text.enabled : text.disabled;
                }} catch (err) {{
                  switchEl.checked = !target;
                  statusEl.textContent = text.failed + ': ' + (err.message || err);
                  setTimeout(refresh, 1600);
                  return;
                }}
                switchEl.disabled = false;
              }});

              refresh();
            }})();
            """
        )

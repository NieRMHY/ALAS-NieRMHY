# OOBE (Out-Of-Box Experience) 初次设置向导
# 在用户首次启动、没有配置文件时引导完成基本设置
#
# 重要：PyWebIO 的 put_html 输出原始 HTML，与 PyWebIO 组件在 DOM 中是平级兄弟节点，
# 不能互相嵌套。因此卡片布局通过 CSS 定位 PyWebIO scope 容器实现，不使用 raw HTML wrapper。
from pywebio.output import (
    clear,
    put_buttons,
    put_html,
    put_scope,
    put_text,
    use_scope,
)
from pywebio.pin import pin
from pywebio.session import run_js, set_env
from module.webui.pin import put_input

import module.webui.lang as lang
from module.config.deep import deep_set
from module.config.server import VALID_PACKAGE
from module.submodule.submodule import load_config
from module.webui.setting import State
from module.webui.utils import add_css, filepath_css

# PyWebIO scope 的 DOM ID 格式为 `pywebio-scope-{name}`
OOBE_ROOT = "oobe_root"

CSS = """
/* === 页面背景 + 居中 === */
#pywebio-scope-oobe_root {
    min-height: 100vh;
    display: flex !important;
    align-items: center;
    justify-content: center;
    padding: 24px;
    box-sizing: border-box;
}
/* === 卡片容器 === */
#pywebio-scope-oobe_content {
    background: var(--alas-content-bg, #fff);
    border-radius: 12px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.10), 0 1px 4px rgba(0,0,0,0.06);
    width: 100% !important;
    max-width: 420px;
    padding: 40px 36px 32px !important;
    box-sizing: border-box;
}
/* === 品牌区 === */
.oobe-brand { text-align: center; margin-bottom: 8px; }
.oobe-brand-icon {
    width: 56px; height: 56px; margin: 0 auto 12px;
    background: linear-gradient(135deg, #4e4c97 0%, #7b79c8 100%);
    border-radius: 14px; display: flex; align-items: center; justify-content: center;
    color: #fff; font-size: 26px; font-weight: 700; line-height: 56px;
}
.oobe-title {
    font-size: 20px; font-weight: 600;
    color: var(--alas-content-text, #1a1a2e); margin: 0 0 4px;
}
.oobe-subtitle { font-size: 13px; color: #888; margin: 0; }
/* === 步骤指示器 === */
.oobe-steps { display: flex; justify-content: center; gap: 8px; margin: 24px 0; }
.oobe-step-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: #d0d0d0; transition: all 0.25s; display: inline-block;
}
.oobe-step-dot.active { background: #4e4c97; width: 24px; border-radius: 4px; }
.oobe-step-dot.done   { background: #4e4c97; }
/* === 分隔线 === */
.oobe-divider { border: none; border-top: 1px solid #eee; margin: 20px 0; }
/* === 选中标签 === */
.oobe-selected-badge {
    display: inline-block; margin-top: 6px; font-size: 12px;
    color: #4e4c97; font-weight: 600;
}
/* === 复查表格 === */
.oobe-review-table { width: 100%; border-collapse: collapse; margin: 12px 0 20px; }
.oobe-review-table td { padding: 10px 12px; border-bottom: 1px solid #f0f0f0; font-size: 14px; }
.oobe-review-table td:first-child { color: #888; width: 42%; font-weight: 500; }
.oobe-review-table td:last-child  { color: var(--alas-content-text, #1a1a2e); }
/* === 卡片内按钮 === */
#pywebio-scope-oobe_content .btn {
    border-radius: 8px; font-size: 14px; padding: 10px 24px; min-width: 100px;
}
"""


class OOBEWizard:
    """OOBE 向导 — 居中卡片式 UI"""

    STEPS = ["welcome", "server", "emulator", "review"]

    def __init__(self, gui):
        self.gui = gui
        self.step_index = 0
        self.server = "cn"
        self.emulator_serial = "127.0.0.1:5555"
        self.package_name = "com.bilibili.azurlane"
        self.config_name = "alas"
        self.screenshot_method = "auto"
        existing_lang = getattr(State.deploy_config, "Language", None)
        if existing_lang:
            try:
                lang.set_language(existing_lang)
            except Exception:
                pass

    @use_scope("ROOT", clear=True)
    def start(self):
        set_env(title="Alas - Setup", output_animation=False)
        add_css(filepath_css("alas"))
        if self.gui.is_mobile:
            add_css(filepath_css("alas-mobile"))
        else:
            add_css(filepath_css("alas-pc"))
        if self.gui.theme == "dark":
            add_css(filepath_css("dark-alas"))
        elif self.gui.theme == "socialism":
            add_css(filepath_css("socialism-alas"))
        else:
            add_css(filepath_css("light-alas"))

        put_html(f"<style>{CSS}</style>")
        put_scope(OOBE_ROOT)
        self._render()

    # ─── 导航 ───

    def _next_step(self):
        self.step_index += 1
        run_js("window.scrollTo(0, 0);")
        self._render()

    def _prev_step(self):
        self.step_index -= 1
        self._render()

    # ─── 整体渲染 ───
    # 使用 put_scope("oobe_content") 作为卡片容器（CSS 上方通过 #pywebio-scope-oobe_content 定位）

    def _render(self):
        clear(OOBE_ROOT)
        with use_scope(OOBE_ROOT):
            put_scope("oobe_content")
            with use_scope("oobe_content"):
                self._render_brand()
                self._render_steps()
                getattr(self, f"_step_{self.STEPS[self.step_index]}")()

    # ─── 静态装饰 ───

    def _render_brand(self):
        put_html(
            '<div class="oobe-brand">'
            '<div class="oobe-brand-icon">A</div>'
            f'<p class="oobe-title">{lang.t("Gui.OOBE.WelcomeTitle")}</p>'
            f'<p class="oobe-subtitle">{lang.t("Gui.OOBE.WelcomeDescription")}</p>'
            '</div>'
        )

    def _render_steps(self):
        dots = ""
        for i in range(len(self.STEPS)):
            cls = "active" if i == self.step_index else ("done" if i < self.step_index else "")
            dots += f'<span class="oobe-step-dot {cls}"></span>'
        put_html(f'<div class="oobe-steps">{dots}</div>')

    # ─── 底部导航 ───

    def _render_footer(self, back=True, next_label=None, next_color="primary",
                       on_next=None, on_back=None):
        from pywebio.output import put_row

        cb_back = on_back or (lambda _: self._prev_step())
        cb_next = on_next or (lambda _: self._next_step())
        label = next_label or f"{lang.t('Gui.OOBE.ButtonNext')} →"

        if back:
            put_row(
                [
                    put_buttons(
                        [{"label": f"← {lang.t('Gui.OOBE.ButtonBack')}", "value": "back",
                          "color": "light"}],
                        onclick=lambda _: cb_back(None),
                    ),
                    put_buttons(
                        [{"label": label, "value": "next", "color": next_color}],
                        onclick=lambda _: cb_next(None),
                    ),
                ],
                size="auto auto",
            ).style("justify-content: space-between; margin-top: 24px;")
        else:
            put_row(
                [
                    None,
                    put_buttons(
                        [{"label": label, "value": "next", "color": next_color}],
                        onclick=lambda _: cb_next(None),
                    ),
                ],
                size="auto auto",
            ).style("justify-content: flex-end; margin-top: 24px;")

    # ─── Step 1: Language ───

    def _step_welcome(self):
        put_text(lang.t("Gui.OOBE.WelcomeSelectLanguage") + ":").style(
            "font-size:14px;font-weight:600;margin-bottom:10px;"
        )
        put_buttons(
            [
                {"label": "简体中文", "value": "zh-CN"},
                {"label": "English", "value": "en-US"},
                {"label": "日本語", "value": "ja-JP"},
                {"label": "繁體中文", "value": "zh-TW"},
            ],
            onclick=lambda l: self._on_language_selected(l),
        )
        put_html('<hr class="oobe-divider">')
        self._render_footer(back=False)

    def _on_language_selected(self, l):
        lang.set_language(l)
        lang_to_server = {"zh-CN": "cn", "en-US": "en", "ja-JP": "jp", "zh-TW": "tw"}
        if l in lang_to_server:
            self.server = lang_to_server[l]
            self.package_name = self._package_for_server(self.server)
        self._render()

    # ─── Step 2: Server ───

    def _step_server(self):
        put_text(lang.t("Gui.OOBE.ServerTitle") + ":").style(
            "font-size:14px;font-weight:600;margin-bottom:10px;"
        )
        server_labels = [
            {"label": lang.t("Gui.OOBE.ServerCN"), "value": "cn"},
            {"label": lang.t("Gui.OOBE.ServerEN"), "value": "en"},
            {"label": lang.t("Gui.OOBE.ServerJP"), "value": "jp"},
            {"label": lang.t("Gui.OOBE.ServerTW"), "value": "tw"},
        ]
        put_buttons(server_labels, onclick=lambda s: self._on_server_selected(s))
        put_html(
            f'<span class="oobe-selected-badge">'
            f'{lang.t("Gui.OOBE.ServerTitle")}: {self.server.upper()}'
            f'</span>'
        )
        put_html('<hr class="oobe-divider">')
        self._render_footer()

    def _on_server_selected(self, s):
        self.server = s
        self.package_name = self._package_for_server(s)
        self._render()

    @staticmethod
    def _package_for_server(server):
        for pkg, srv in VALID_PACKAGE.items():
            if srv == server:
                return pkg
        return "com.bilibili.azurlane"

    # ─── Step 3: Emulator ───

    def _step_emulator(self):
        put_input(
            name="oobe_serial",
            label=lang.t("Gui.OOBE.EmulatorSerial"),
            value=self.emulator_serial,
        )
        put_html('<div style="height:12px"></div>')
        put_input(
            name="oobe_package",
            label=lang.t("Gui.OOBE.EmulatorPackage"),
            value=self.package_name,
        )
        put_html('<hr class="oobe-divider">')
        self._render_footer(
            on_next=lambda _: self._collect_emulator_and_go(1),
            on_back=lambda _: self._collect_emulator_and_go(-1),
        )

    def _collect_emulator_and_go(self, direction):
        self.emulator_serial = pin.oobe_serial or self.emulator_serial
        self.package_name = pin.oobe_package or self.package_name
        if direction > 0:
            self._next_step()
        else:
            self._prev_step()

    # ─── Step 4: Review ───

    def _step_review(self):
        server_display = {"cn": "CN", "en": "EN", "jp": "JP", "tw": "TW"}.get(self.server, self.server)
        items = [
            (lang.t("Gui.OOBE.ReviewConfigName"), self.config_name),
            (lang.t("Gui.OOBE.ReviewLanguage"), lang.LANG),
            (lang.t("Gui.OOBE.ReviewServer"), server_display),
            (lang.t("Gui.OOBE.ReviewSerial"), self.emulator_serial),
            (lang.t("Gui.OOBE.ReviewPackage"), self.package_name),
        ]
        rows = "".join(
            f"<tr><td>{k}</td><td>{v}</td></tr>"
            for k, v in items
        )
        put_html(f'<table class="oobe-review-table">{rows}</table>')
        put_html('<hr class="oobe-divider">')
        self._render_footer(
            next_label=lang.t("Gui.OOBE.ButtonCreate"),
            next_color="success",
            on_next=lambda _: self._create_config_and_finish(),
        )

    # ─── Config Creation ───

    def _create_config_and_finish(self):
        try:
            config = load_config("template")
            data = config.read_file("template")
            deep_set(data, "Alas.Emulator.Serial", self.emulator_serial)
            deep_set(data, "Alas.Emulator.PackageName", self.package_name)
            deep_set(data, "Alas.Emulator.ScreenshotMethod", self.screenshot_method)
            State.config_updater.write_file(self.config_name, data)
        except Exception as e:
            from pywebio.output import put_error
            with use_scope("oobe_content"):
                put_error(f"Failed to create config: {e}")
            return

        run_js("window.location.reload();")

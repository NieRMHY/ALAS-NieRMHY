"""AzurPilot WebUI 的兼容入口和 ASGI 应用工厂。

提供 WebUI 的主应用类，通过多个 Mixin 组合实现各功能页面：
仪表盘（Dashboard）、开发者菜单、开发者设置、开发者工具、
版本更新、活动工具等。同时提供 ASGI 应用创建和路由注册。

该模块是 WebUI 的顶层入口，被 gui.py 启动时引用。
"""

from module.webui.app_dashboard import DashboardMixin
from module.webui.app_dependencies import (
    Dict,
    Frame,
    IS_ON_PHONE_CLOUD,
    List,
    ProcessManager,
    RichLog,
    State,
    argparse,
    asgi_app,
    get_localstorage_values,
    info,
    lang,
    load_webui_styles,
    local,
    logger,
    login,
    os,
    run_js,
    set_env,
    task_handler,
    time,
    updater,
    webconfig,
)
from module.webui.app_developer_menu import DeveloperMenuMixin
from module.webui.app_developer_settings import DeveloperSettingsMixin
from module.webui.app_developer_tools import DeveloperToolsMixin
from module.webui.app_developer_update import DeveloperUpdateMixin
from module.webui.app_event_tools import EventToolsMixin
from module.webui.app_helpers import (
    build_copyable_device_id,
    build_muted_notice,
    build_recommendation_box,
    build_simple_table,
    build_title_block,
    is_webui_password_set,
    read_webapp_template,
    timedelta_to_text,
)
from module.webui.app_home import HomeMixin
from module.webui.app_instances import InstanceMixin
from module.webui.app_lifecycle import clearup, startup
from module.webui.app_manage import app_manage
from module.webui.app_overview import OverviewMixin
from module.webui.app_shell import AppShellMixin
from module.webui.app_stat_action_point import ActionPointStatisticsMixin
from module.webui.app_stat_action_point_toolbar import ActionPointToolbarMixin
from module.webui.app_stat_commission import CommissionIncomeStatisticsMixin
from module.webui.app_stat_opsi import OpsiStatisticsMixin
from module.webui.app_stat_opsi_export import OpsiExportMixin
from module.webui.app_stat_resource import ResourceStatisticsMixin
from module.webui.app_stat_ship import ShipExperienceStatisticsMixin
from module.webui.app_statistics_page import StatisticsPageMixin
from module.webui.app_task_config import TaskConfigMixin


INITIAL_WEBUI_CSS = "/static/assets/gui/css/alas.css"


class AlasGUI(
    AppShellMixin,
    StatisticsPageMixin,
    ActionPointStatisticsMixin,
    ActionPointToolbarMixin,
    ResourceStatisticsMixin,
    OpsiStatisticsMixin,
    OpsiExportMixin,
    ShipExperienceStatisticsMixin,
    CommissionIncomeStatisticsMixin,
    TaskConfigMixin,
    EventToolsMixin,
    OverviewMixin,
    DashboardMixin,
    DeveloperMenuMixin,
    DeveloperUpdateMixin,
    DeveloperSettingsMixin,
    DeveloperToolsMixin,
    InstanceMixin,
    HomeMixin,
    Frame,
):
    """组合各 WebUI 视图的会话控制器。

    Mixin 的顺序明确会话能力的组合层次。统计页入口通过 ``self`` 调用具体
    视图的渲染方法，因此各视图模块既可独立维护，也保持原有会话接口不变。
    """

    ALAS_MENU: Dict[str, Dict[str, List[str]]]
    ALAS_ARGS: Dict[str, Dict[str, Dict[str, Dict[str, str]]]]
    theme = "default"
    _log = RichLog


def debug() -> None:
    """初始化 WebUI 后进入交互式调试会话。"""
    startup()
    AlasGUI().run()


def app():
    """创建供 Uvicorn 使用的 ASGI 应用工厂。

    Returns:
        Starlette: 挂载 WebUI 页面和 MCP 子应用的 ASGI 应用。
    """
    parser = argparse.ArgumentParser(description="Alas web service")
    parser.add_argument(
        "-k", "--key", type=str, help="Password of alas. No password by default"
    )
    parser.add_argument(
        "--cdn",
        action="store_true",
        help="Use jsdelivr cdn for pywebio static files (css, js). Self host cdn by default.",
    )
    parser.add_argument(
        "--run",
        nargs="+",
        type=str,
        help="Run alas by config names on startup",
    )
    args, _ = parser.parse_known_args()

    AlasGUI.set_theme(theme=State.deploy_config.Theme)
    lang.LANG = State.deploy_config.Language
    key = args.key if is_webui_password_set(args.key) else State.deploy_config.Password
    cdn: str | bool = args.cdn if args.cdn else State.deploy_config.CDN
    runs: List[str] | None = None
    if args.run:
        runs = args.run
    elif State.deploy_config.Run:
        # deploy.yaml 的旧格式仍是逗号分隔字符串，保持兼容直到配置读取器支持列表。
        tmp = State.deploy_config.Run.split(",")
        runs = [item.strip(" ['\"]") for item in tmp if item]
    # 未传入 --run 时保持 None，由进程管理器跳过启动实例。
    instances: List[str] | None = runs

    logger.hr("[WebUI] WebUI 配置")
    logger.attr("主题", State.deploy_config.Theme)
    logger.attr("语言", lang.LANG)
    logger.attr("密码", is_webui_password_set(key))
    logger.attr("CDN", cdn)
    logger.attr("云手机", IS_ON_PHONE_CLOUD)

    from deploy.atomic import atomic_failure_cleanup

    atomic_failure_cleanup("./config")
    static_path = os.getcwd()

    def _run_gui(initial_page: str = "home") -> None:
        set_env(title="AzurPilot", output_animation=False)
        load_webui_styles(
            theme=AlasGUI.theme,
            is_mobile=info.user_agent.is_mobile,
            preloaded_styles=("alas",),
        )
        localstorage = None
        if is_webui_password_set(key):
            localstorage = get_localstorage_values(
                ("password", "clarity_notice_shown", "aside")
            )
        if is_webui_password_set(key) and not login(
            key, stored_password=localstorage.get("password")
        ):
            logger.warning(f"[WebUI] {info.user_ip} 登录失败")
            time.sleep(1.5)
            run_js("location.reload();")
            return
        gui = AlasGUI()
        local.gui = gui
        gui.run(initial_page=initial_page, localstorage=localstorage)

    @webconfig(css_file=INITIAL_WEBUI_CSS)
    def index() -> None:
        _run_gui()

    @webconfig(css_file=INITIAL_WEBUI_CSS)
    def manage() -> None:
        _run_gui(initial_page="manage")

    from mcp_server_sse import app as mcp_app

    application = asgi_app(
        applications=[index, manage],
        cdn=cdn,
        static_dir=static_path,
        debug=True,
        on_startup=[
            startup,
            lambda: ProcessManager.restart_processes(
                instances=instances, ev=updater.event
            ),
        ],
        on_shutdown=[clearup],
    )
    application.mount("/mcp", mcp_app)
    return application

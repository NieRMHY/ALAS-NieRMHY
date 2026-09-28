"""委托调试处理模块。

用于在无需真实运行游戏的情况下，向统计数据库写入模拟的委托收益数据，
并测试 OnePush 与 WebUI 的消息推送链路。
"""

from module.notify.notify import handle_notify, notify_webui


class CommissionDebugHandler:
    """委托收益调试处理器。

    由 `module.debug.web_debug_server` 在调度器进程内注册，用于在不开游戏的情况下
    向本地统计库写入一条伪造的委托收益记录并触发一次推送，便于验证统计口径与通知链路。

    与远程实现的差异：本地 `handle_notify` / `notify_webui` 为模块级函数（远程挂在 bot 实例上），
    因此此处直接调用模块级函数；同时移除了远程未被使用的一次 `get_commission_reward_stats` 查询。
    """

    def __init__(self, bot):
        """初始化委托调试处理器。

        Args:
            bot (AzurLaneAutoScript): 当前运行的机器人实例。
        """
        self.bot = bot

    @property
    def instance(self):
        """获取当前配置实例名称。

        Returns:
            str: 实例标识名称。
        """
        return self.bot.config_name

    def trigger_gem_test(self):
        """触发模拟获得 50 钻石的测试记录与推送。"""
        self._send(gem=50)

    def trigger_cube_test(self):
        """触发模拟获得 5 魔方的测试记录与推送。"""
        self._send(cube=5)

    def trigger_big_success(self):
        """触发模拟大成功（120 钻石 + 3 魔方）的测试记录与推送。"""
        self._send(gem=120, cube=3)

    def trigger_notify_only(self):
        """仅验证推送链路，不写入统计库。"""
        self._notify(
            title=f'DEBUG TEST <{self.instance}>',
            content='仅推送测试，未写入统计库',
        )

    def _send(self, gem=0, cube=0):
        """向数据库写入委托收益并发送调试通知。

        Args:
            gem (int): 钻石数量。
            cube (int): 魔方数量。
        """
        from module.statistics.cl1_database import db as cl1_db

        items = {'Gem': gem, 'Cube': cube}
        cl1_db.add_commission_income(self.instance, items, commission_count=1)

        self._notify(
            title=f'DEBUG TEST <{self.instance}>',
            content=f'钻石 x {gem}\n魔方 x {cube}',
        )

    def _notify(self, title, content):
        """调用 OnePush 与 WebUI 发送通知。

        Args:
            title (str): 消息标题。
            content (str): 消息正文。
        """
        handle_notify(
            self.bot.config.Error_OnePushConfig,
            title=title,
            content=content,
        )
        notify_webui(
            self.instance,
            title='DEBUG TEST',
            content=content,
        )

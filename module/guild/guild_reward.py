"""大舰队奖励任务入口，统一调度大厅、后勤和作战三个子任务。
从主页面进入大舰队，依次执行各子任务后返回。
"""

from module.guild.lobby import GuildLobby
from module.guild.logistics import GuildLogistics
from module.guild.operations import GuildOperations
from module.ui.page import page_guild, page_main


class RewardGuild(GuildLobby, GuildLogistics, GuildOperations):
    """大舰队日常奖励综合执行类。

    整合大厅签到与公共事件、后勤整备、舰队作战与作战报告领取。
    """

    def run(self):
        """执行大舰队日常奖励领取与任务流程。

        依次处理大厅、后勤、作战模块，全部完成后返回主界面并延迟至次日刷新。

        Pages:
            in: page_main 或任意页面
            out: page_main
        """
        if not self.config.GuildLogistics_Enable and not self.config.GuildOperation_Enable:
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        self.ui_ensure(page_guild)

        # Lobby
        self.guild_lobby()

        # Logistics
        if self.config.GuildLogistics_Enable:
            self.guild_logistics()

        # Operation
        if self.config.GuildOperation_Enable:
            self.guild_operations()

        self.ui_goto(page_main)

        # Scheduler
        self.config.task_delay(server_update=True)

import module.config.server as server

from module.island.assets import *
from module.island.project_data import *
from module.island.project import IslandProjectRun
from module.island.transport import IslandTransportRun
from module.logger import logger
from module.ui.page import page_island_phone, page_main


class Island(IslandProjectRun, IslandTransportRun):
    @staticmethod
    def island_config_to_names(config):
        """
        将岛屿配置布尔列表转换为对应的名称列表。

        Args:
            config (list[bool]): 岛屿收取配置，每个元素对应一个岛屿

        Returns:
            list[str]: 需要收取的岛屿名称列表
        """
        if any(config):
            return [name for add, name in zip(config, list(name_to_slot.keys())) if add]
        else:
            return []

    def island_run(self, transport=True, project=True, names=None):
        """
        执行岛屿日常任务，包括货运委托和生产项目。

        Args:
            transport (bool): 是否执行货运委托
            project (bool): 是否执行生产项目
            names (list[str]): 需要收取的岛屿名称列表
        """
        future_finish = []
        if transport:
            if self.island_transport_enter():
                future_finish.extend(self.island_transport_run())
                self.island_ui_back()

        if project:
            if self.island_management_enter():
                future_finish.extend(self.island_project_run(names=names))
                self.island_ui_back()
            else:
                logger.warning('Island management locked, please reach island level 18 '
                                'and unlock island management to use this task.')
                self.config.Scheduler_Enable = False
                return False

        # 任务延时，根据未来完成时间设置下次运行
        if len(future_finish):
            self.config.task_delay(target=future_finish)
        else:
            logger.info('No island routine running')
            self.config.task_delay(success=False)

    def run(self):
        if server.server in ['cn', 'en']:
            transport = False
            project_config = [self.config.__getattribute__(f'Island{i}_Receive')
                              for i in range(1, len(name_to_slot) + 1)]
            project = any(project_config)
            names = self.island_config_to_names(project_config)
            if transport or project:
                self.ui_ensure(page_island_phone)
                self.island_run(transport=transport, project=project, names=names)
                self.ui_goto(page_main, get_ship=False)
            else:
                logger.info('Nothing to receive, skip island running')
                self.config.task_delay(server_update=True)
        else:
            logger.info(f'Island task not presently supported for {server.server} server.')
            logger.info('If want to address, review necessary assets, replace, update above condition, and test')
            self.config.task_delay(server_update=True)

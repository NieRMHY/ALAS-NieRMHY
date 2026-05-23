import os

from module.config.config import TaskEnd
from module.event.base import EventBase
from module.exception import RequestHumanTakeover
from module.logger import logger


class CampaignSP(EventBase):
    def run(self, *args, **kwargs):
        if not os.path.exists(f'./campaign/{self.config.Campaign_Event}/sp.py'):
            logger.info(f'./campaign/{self.config.Campaign_Event}/sp.py not exists')
            logger.info(f'This event do not have SP, skip')
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        try:
            super().run(name=self.config.Campaign_Name, folder=self.config.Campaign_Event, total=1)
        except TaskEnd:
            # Catch task switch
            pass
        except RequestHumanTakeover:
            # Daily SP already completed, delay to next day
            logger.info('Daily SP already completed or unable to enter')
            logger.info('Delaying task to next day')
            self.config.task_delay(server_update=True)
            return
        
        # Check if SP was successfully executed
        if self.run_count > 0:
            # SP completed successfully, delay to next day
            logger.info(f'SP completed successfully, run_count={self.run_count}')
            self.config.task_delay(server_update=True)
        else:
            # SP failed to execute (possibly already completed today)
            # Delay task to next day instead of stopping
            logger.info('SP failed to execute, possibly already completed today')
            logger.info('Delaying task to next day')
            self.config.task_delay(server_update=True)

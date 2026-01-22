
from module.config.utils import get_nearest_weekday_date
from module.logger import logger
from module.os.map import OSMap
from module.shop.shop_voucher import VoucherShop


class OpsiArchive(OSMap):
    def os_archive(self):
        """
        Complete active archive zone in daily mission
        Purchase next available logger archive then repeat
        until exhausted

        Run on weekly basis, AL devs seemingly add new logger
        archives after random scheduled maintenances
        """
        if self.is_in_opsi_explore():
            logger.info('OpsiExplore is under scheduling, stop OpsiArchive')
            self.config.task_delay(server_update=True)
            self.config.task_stop()

        shop = VoucherShop(self.config, self.device)
        while True:
            # In case logger bought manually,
            # finish pre-existing archive zone
            self.os_finish_daily_mission(
                skip_siren_mission=self.config.cross_get('OpsiDaily.OpsiDaily.SkipSirenResearchMission'),
                question=False, rescan=False)

            logger.hr('OS voucher', level=1)
            self._os_voucher_enter()
            bought = shop.run_once()
            self._os_voucher_exit()
            if not bought:
                break

        # Reset to nearest 'Wednesday' date
        next_reset = get_nearest_weekday_date(target=2)
        logger.info('All archive zones finished, delay to next reset')
        logger.attr('OpsiNextReset', next_reset)
        self.config.task_delay(target=next_reset)

from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.handler.assets import MAINTENANCE_ANNOUNCE, USE_DATA_KEY_NOTIFIED
from module.island.assets import *
from module.logger import logger
from module.ui.assets import DORMMENU_GOTO_ISLAND, SHOP_BACK_ARROW
from module.ui.page import page_dormmenu, page_island, page_island_phone
from module.ui.navbar import Navbar
from module.ui.ui import UI


class IslandUI(UI):
    def island_in_management(self, interval=0):
        """
        Args:
            interval (int):

        Returns:
            bool: if in page ISLAND_MANAGEMENT_CHECK
        """
        return self.appear(ISLAND_MANAGEMENT_CHECK, offset=(20, 20), interval=interval)

    def island_in_transport(self, interval=0):
        """
        Args:
            interval (int):

        Returns:
            bool: if in page ISLAND_TRANSPORT_CHECK
        """
        return self.match_template_color(ISLAND_TRANSPORT_CHECK, offset=(20, 20), interval=interval)

    def island_management_enter(self):
        """
        Enter island management page.

        Returns:
            bool: if success

        Pages:
            in: page_island_phone
            out: ISLAND_MANAGEMENT_CHECK
        """
        logger.info('Island management enter')
        self.interval_clear(ISLAND_MANAGEMENT_CHECK)
        if self.appear(ISLAND_MANAGEMENT_LOCKED, offset=(20, 20)):
            return False
        self.ui_click(
            click_button=ISLAND_MANAGEMENT,
            check_button=self.island_in_management,
            offset=(20, 20),
            retry_wait=2,
            skip_first_screenshot=True
        )
        return True

    def island_transport_enter(self):
        """
        Enter island management page.

        Returns:
            bool: if success

        Pages:
            in: page_island_phone
            out: ISLAND_MANAGEMENT_CHECK
        """
        logger.info('Island transport enter')
        self.ui_click(
            click_button=ISLAND_TRANSPORT,
            check_button=self.island_in_transport,
            offset=(20, 20),
            retry_wait=2,
            skip_first_screenshot=True
        )
        return True

    def island_ui_back(self):
        """
        Pages:
            in: any page with SHOP_BACK_ARROW
            out: page_island_phone
        """
        logger.info('Island UI back')
        self.ui_click(
            click_button=SHOP_BACK_ARROW,
            check_button=page_island_phone.check_button,
            offset=(20, 20),
            retry_wait=2,
            skip_first_screenshot=True
        )

    def ui_ensure_management_page(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_island_phone or product page
            out: ISLAND_MANAGEMENT_CHECK
        """
        logger.info('UI ensure management page')
        self.interval_clear(ISLAND_MANAGEMENT_CHECK)
        confirm_timer = Timer(1, count=2).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.island_in_management():
                if confirm_timer.reached():
                    break
                continue
            else:
                confirm_timer.reset()

            if self.appear_then_click(SHOP_BACK_ARROW, offset=(20, 20), interval=2):
                continue

            if self.appear_then_click(ISLAND_MANAGEMENT, offset=(20, 20), interval=2):
                continue

    def handle_get_items(self):
        if self.appear_then_click(GET_ITEMS_ISLAND, offset=(20, 20), interval=2):
            return True
        return False

    def handle_island_ui_additional(self, skip_first_screenshot=True):
        if not self.appear(MAINTENANCE_ANNOUNCE, offset=(100, 50)):
            return False

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            enabled = self.image_color_count(
                USE_DATA_KEY_NOTIFIED, color=(140, 207, 66), threshold=180, count=10)
            if enabled:
                break

            if self.appear(MAINTENANCE_ANNOUNCE, offset=(100, 50), interval=5):
                self.device.click(USE_DATA_KEY_NOTIFIED)
                continue

        self.interval_clear(MAINTENANCE_ANNOUNCE)
        self.appear_then_click(MAINTENANCE_ANNOUNCE, offset=(100, 50), interval=2)
        return True

    def ui_goto_island(self):
        if self.ui_get_current_page() in [page_island, page_island_phone]:
            logger.info(f'Already at {self.ui_current}')
            return True

        self.ui_ensure(page_dormmenu)
        self.ui_click(click_button=DORMMENU_GOTO_ISLAND,
                      check_button=page_island.check_button,
                      additional=self.handle_island_ui_additional,
                      offset=(30, 30),
                      retry_wait=2,
                      skip_first_screenshot=True)

    @cached_property
    def _island_technology_side_navbar(self):
        island_technology_side_navbar = ButtonGrid(
            origin=(13, 107), delta=(0, 196/3),
            button_shape=(128, 43), grid_shape=(1, 5)
        )
        return Navbar(grids=island_technology_side_navbar,
                      active_color=(30, 143, 255),
                      inactive_color=(50, 52, 55),
                      active_count=500,
                      inactive_count=500)

    def _island_technology_side_navbar_get_active(self):
        active, _, _ = self._island_technology_side_navbar.get_info(main=self)
        if active is None:
            return 1
        return active + 2

    def island_technology_side_navbar_ensure(self, tab=1, skip_first_screenshot=True):
        """
        Tab 2, 3, 4, 5, 6 corresponds to _island_technology_side_navbar 1, 2, 3, 4, 5
        Tab 1 is a special situation where the botton icon is chosen,
        and all the navbar icons are inactive.
        """
        for _ in self.loop(skip_first=skip_first_screenshot):
            active = self._island_technology_side_navbar_get_active()
            if active == tab:
                return True
            if tab == 1:
                self.device.click(ISLAND_TECHNOLOGY_TAB1)
                continue
            else:
                if active == 1:
                    self.device.click(self._island_technology_side_navbar.grids.buttons[tab-2])
                    continue
                else:
                    self._island_technology_side_navbar.set(self, upper=tab-1)
                    return True
        return False

"""
后宅（宿舍）任务模块。

自动执行后宅的日常维护操作，包括：
- 收取宿舍中的爱心和金币
- 使用食物喂食舰船（支持长按喂食和多次点击）
- 购买食物并管理食物库存
- 计算下次任务延迟时间

食物喂食支持多种控制后端：minitouch、MaaTouch、uiautomator2、nemu_ipc。
通过 OCR 识别食物数量和饱食度，通过模板匹配识别爱心和金币。
"""
import time
import typing as t
from datetime import timezone

from module.base.button import ButtonGrid
from module.base.decorator import Config, cached_property
from module.base.filter import Filter
from module.base.mask import Mask
from module.base.timer import Timer
from module.base.utils import *
from module.config.time_source import now as current_time
from module.config.utils import server_timezone
from module.dorm.assets import *
from module.dorm.buy_furniture import BuyFurniture
from module.exception import GameStuckError
from module.handler.assets import POPUP_CONFIRM
from module.logger import logger
from module.ocr.ocr import Digit, DigitCounter, Ocr
from module.template.assets import TEMPLATE_DORM_COIN, TEMPLATE_DORM_LOVE
from module.ui.assets import DORM_CHECK
from module.ui.page import page_dorm, page_dormmenu
from module.ui.ui import UI

MASK_DORM = Mask(file='./assets/mask/MASK_DORM.png')
DORM_CAMERA_SWIPE = (300, 250)
DORM_CAMERA_RANDOM = (-20, -20, 20, 20)
OCR_SLOT = DigitCounter(OCR_DORM_SLOT, letter=(107, 89, 82), threshold=128, name='OCR_DORM_SLOT')
OCR_BUY_FOOD_AMOUNT = Digit(OCR_DORM_BUY_FOOD_AMOUNT, letter=(96, 96, 100), threshold=128, name='OCR_DORM_BUY_FOOD_AMOUNT')
OCR_BUY_OIL_COST = Digit(OCR_FUEL_COST, letter=(107, 89, 82), threshold=128, name='OCR_DORM_BUY_OIL_COST')
TEMPLATE_DORM_OIL_COST = DORM_BUY_FOOD_CHECK.crop((0, 0, 28, 32), name='TEMPLATE_DORM_OIL_COST')


class OcrDormFood(DigitCounter):
    """宿舍食物 OCR，识别食物数量格式如 `12084/50000`。"""

    # The OCR area includes the icon left of the number, OCR may read it as an extra
    # '7' in front of the number. The image is cut at the leftmost orange pixel, so
    # the icon is not OCRed. Orange scores about 250 in the color similarity map,
    # the icon, the gray total (40000) and the background score below 130.
    ORANGE_THRESHOLD = 150
    ORANGE_MARGIN = 5
    VALID_TOTALS = range(40000, 102001, 2000)

    def pre_process(self, image):
        orange = color_similarity_2d(image, color=(239, 158, 49))
        gray = color_similarity_2d(image, color=(99, 97, 99))
        # image = cv2.subtract(255, cv2.max(orange, gray))
        # image = cv2.multiply(image, 2)
        cv2.max(orange, gray, dst=gray)
        cv2.bitwise_not(gray, dst=gray)
        cv2.convertScaleAbs(gray, alpha=2, dst=gray)

        # Keep the orange number and ORANGE_MARGIN pixels on its left, cut the rest.
        columns = np.where(orange.max(axis=0) > self.ORANGE_THRESHOLD)[0]
        if len(columns):
            gray = gray[:, max(int(columns[0]) - self.ORANGE_MARGIN, 0):]

        return gray

    def after_process(self, result):
        result = super().after_process(result)

        if '/' not in result:
            for exp in self.VALID_TOTALS:
                res = re.match(rf'^(\d+){exp}$', result)
                if res and int(res.group(1)) <= exp:
                    # 100040000 -> 1000/40000
                    new = f'{res.group(1)}/{exp}'
                    logger.info(f'[宿舍-OCR] 食物OCR结果 {result} 修正为 {new}')
                    result = new
                    break

        return result

    def ocr(self, image, direct_ocr=False):
        result_list = Ocr.ocr(self, image, direct_ocr=direct_ocr)
        result = result_list[0] if isinstance(result_list, list) else result_list

        match = re.search(r'(\d+)/(\d+)', result)
        if match:
            current, total = int(match.group(1)), int(match.group(2))
            if current <= total and total in self.VALID_TOTALS:
                return current, total - current, total

        logger.warning(f'[OCR] 意外的OCR结果: {result_list}')
        return 0, 0, 0


OCR_FILL = OcrDormFood(OCR_DORM_FILL, name='OCR_DORM_FILL')


class Food:
    """食物数据类，包含单次喂食量和数量。"""

    def __init__(self, feed, amount):
        self.feed = feed
        self.amount = amount

    def __str__(self):
        return f'Food_{self.feed}'

    def __eq__(self, other):
        return str(self) == str(other)


FOOD_FEED_AMOUNT = [1000, 2000, 3000, 5000, 10000, 20000]
FOOD_FILTER = Filter(regex=re.compile(r'(\d+)'), attr=['feed'])


class RewardDorm(UI):
    """
    后宅奖励处理器，负责宿舍的日常维护操作。

    继承自 UI，提供以下功能：
    - 收取宿舍中的爱心和金币（手动点击或快捷收取）
    - 使用食物喂食舰船（支持多种喂食方式）
    - 购买食物并管理食物库存
    - 获取宿舍舰船数量并计算任务延迟

    Attributes:
        _dorm_food (ButtonGrid): 食物按钮网格，6 种食物从左到右排列。
        _dorm_food_ocr (Digit): 食物数量 OCR，识别每种食物的库存。
    """

    def _dorm_receive_click(self):
        """
        点击宿舍中的爱心和金币进行收取。

        Returns:
            int: 收取数量。

        Pages:
            in: page_dorm
            out: page_dorm, with info_bar
        """
        image = MASK_DORM.apply(self.device.image)
        loves = TEMPLATE_DORM_LOVE.match_multi(image, name='DORM_LOVE')
        coins = TEMPLATE_DORM_COIN.match_multi(image, name='DORM_COIN')
        logger.info(f'[宿舍-收取] 爱心: {len(loves)}, 金币: {len(coins)}')
        # 复杂的宿舍背景可能导致误检
        if len(loves) > 6:
            logger.warning('[宿舍-收取] 爱心数量超过6个，限制为6')
            loves = loves[:6]
        if len(coins) > 6:
            logger.warning('[宿舍-收取] 金币数量超过6个，限制为6')
            coins = coins[:6]

        count = 0
        for button in loves:
            count += 1
            # 禁用点击记录检查，因为可能有太多金币或爱心
            self.device.click(button, control_check=False)
            self.device.sleep((0.5, 0.8))
        for button in coins:
            count += 1
            self.device.click(button, control_check=False)
            self.device.sleep((0.5, 0.8))

        return count

    @Config.when(DEVICE_CONTROL_METHOD='minitouch')
    def _dorm_feed_long_tap(self, button, count):
        """通过 minitouch 长按食物按钮进行喂食。

        Args:
            button (Button): 食物按钮。
            count (int): 喂食消耗量对应计算出的次数。
        """
        # 长按喂食，需要 minitouch 支持。
        timeout = Timer(count // 5 + 5).start()
        x, y = random_rectangle_point(button.button)
        builder = self.device.minitouch_builder
        builder.down(x, y).commit()
        builder.send()

        while 1:
            builder.move(x, y).commit().wait(10)
            builder.send()
            self.device.screenshot()

            if not self._dorm_has_food(button) \
                    or self.handle_info_bar() \
                    or self.appear(POPUP_CONFIRM, offset=self._popup_offset):
                break
            if timeout.reached():
                logger.warning('[宿舍-喂食] 喂食等待超时')
                break

        builder.up().commit()
        builder.send()

    @Config.when(DEVICE_CONTROL_METHOD='MaaTouch')
    def _dorm_feed_long_tap(self, button, count):
        """通过 MaaTouch 长按食物按钮进行喂食。

        Args:
            button (Button): 食物按钮。
            count (int): 喂食消耗量对应计算出的次数。
        """
        timeout = Timer(count // 5 + 5).start()
        x, y = random_rectangle_point(button.button)
        builder = self.device.maatouch_builder
        builder.down(x, y).commit()
        builder.send()

        while 1:
            builder.move(x, y).commit().wait(10)
            builder.send()
            self.device.screenshot()

            if not self._dorm_has_food(button) \
                    or self.handle_info_bar() \
                    or self.appear(POPUP_CONFIRM, offset=self._popup_offset):
                break
            if timeout.reached():
                logger.warning('[宿舍-喂食] 喂食等待超时')
                break

        builder.up().commit()
        builder.send()

    @Config.when(DEVICE_CONTROL_METHOD='uiautomator2')
    def _dorm_feed_long_tap(self, button, count):
        """通过 uiautomator2 长按食物按钮进行喂食。

        Args:
            button (Button): 食物按钮。
            count (int): 喂食消耗量对应计算出的次数。
        """
        timeout = Timer(count // 5 + 5).start()
        x, y = random_rectangle_point(button.button)
        self.device.u2.touch.down(x, y)

        while 1:
            self.device.u2.touch.move(x, y)
            time.sleep(.01)
            self.device.screenshot()

            if not self._dorm_has_food(button) \
                    or self.handle_info_bar() \
                    or self.appear(POPUP_CONFIRM, offset=self._popup_offset):
                break
            if timeout.reached():
                logger.warning('[宿舍-喂食] 喂食等待超时')
                break

        self.device.u2.touch.up(x, y)

    @Config.when(DEVICE_CONTROL_METHOD='nemu_ipc')
    def _dorm_feed_long_tap(self, button, count):
        """通过 nemu_ipc 长按食物按钮进行喂食。

        Args:
            button (Button): 食物按钮。
            count (int): 喂食消耗量对应计算出的次数。
        """
        timeout = Timer(count // 5 + 5).start()
        x, y = random_rectangle_point(button.button)

        while 1:
            self.device.nemu_ipc.down(x, y)
            time.sleep(.01)
            self.device.screenshot()

            if not self._dorm_has_food(button) \
                    or self.handle_info_bar() \
                    or self.appear(POPUP_CONFIRM, offset=self._popup_offset):
                break
            if timeout.reached():
                logger.warning('[宿舍-喂食] 喂食等待超时')
                break

        self.device.nemu_ipc.up()

    @Config.when(DEVICE_CONTROL_METHOD=None)
    def _dorm_feed_long_tap(self, button, count):
        """当控制方式不支持长按抬起时，使用多次点击替代长按。

        Args:
            button (Button): 食物按钮。
            count (int): 喂食消耗量对应计算出的次数。
        """
        logger.warning(f'[宿舍-喂食] 当前控制方式 {self.config.Emulator_ControlMethod} '
                       f'不支持DOWN/UP事件，使用多次点击代替')
        self.device.multi_click(button, count)

    def dorm_view_reset(self):
        """
        通过进入宿舍管理界面再返回来重置宿舍视角。

        Pages:
            in: page_dorm
            out: page_dorm
        """
        logger.info('[宿舍-视角] 重置宿舍视角')
        for _ in self.loop():
            # 结束
            if self.appear(DORM_MANAGE_CHECK, offset=(20, 20)):
                break

            if self.appear_then_click(DORM_MANAGE, offset=(20, 20), interval=3):
                continue
            # 处理所有弹窗
            if self.ui_additional(get_ship=False):
                continue
            if self.appear_then_click(DORM_FURNITURE_CONFIRM, offset=(30, 30), interval=3):
                continue

        for _ in self.loop():
            if self.appear(DORM_MANAGE, offset=(20, 20)):
                break

            if self.appear(DORM_MANAGE_CHECK, offset=(20, 20), interval=3):
                self.device.click(DORM_FURNITURE_SHOP_QUIT)
                continue

    def dorm_collect(self):
        """
        使用一键收取按钮收取宿舍中所有的金币和爱心。

        Pages:
            in: page_dorm
            out: page_dorm
        """
        logger.hr('后宅收取')

        self.ensure_no_info_bar()

        # 设置计时器，防止 Alas 偶尔未能检测到 info_bar
        timeout = Timer(1.5, count=3).start()

        for _ in self.loop():
            # 处理所有弹窗
            if self.ui_additional(get_ship=False):
                continue

            # 通过快捷收取按钮收取金币和爱心
            if self.appear_then_click(DORM_QUICK_COLLECT, offset=(20, 20), interval=1):
                continue

            # 正常结束
            if self.info_bar_count() > 0:
                break

            # 超时结束
            if timeout.reached():
                logger.warning('[宿舍-收取] 收取超时，可能未检测到信息栏')
                break

    @cached_property
    def _dorm_food(self):
        """获取后宅喂食界面的 6 个食物槽位按钮网格。"""
        return ButtonGrid(origin=(395, 410), delta=(129, 0), button_shape=(105, 70), grid_shape=(6, 1), name='FOOD')

    @cached_property
    def _dorm_food_ocr(self):
        """获取后宅 6 个食物槽位的数字库存 OCR 识别对象。"""
        grids = self._dorm_food.crop((54, 41, 101, 66), name='FOOD_AMOUNT')
        return Digit(grids.buttons, letter=(255, 255, 255), threshold=128, name='OCR_DORM_FOOD')

    def _dorm_has_food(self, button):
        """检测指定食物按钮是否有食物（非空槽位）。

        Args:
            button (Button): 食物按钮。

        Returns:
            bool: 槽位有食物返回 True，空槽位返回 False。
        """
        return np.min(rgb2gray(self.image_crop(button, copy=False))) < 127

    def _dorm_feed_click(self, button, count, reserve=None):
        """
        点击食物按钮进行喂食。

        Args:
            button (Button): 食物按钮。
            count (int): 本轮最多使用的食物数量。
            reserve (int | None): 库存不足时需要保留的总数；None 使用原喂食方案。

        Pages:
            in: DORM_FEED_CHECK
        """
        logger.info(f'[宿舍-喂食] 喂食 {button} x {count}')
        if reserve is not None:
            self._dorm_feed_reserved(button, count, reserve=reserve)
            return
        if count <= 3:
            for _ in range(count):
                self.device.click(button)
                self.device.sleep((0.5, 0.8))
            skip_first_screenshot = False
        else:
            self._dorm_feed_long_tap(button, count)
            skip_first_screenshot = True

        self.popup_interval_clear()
        for _ in self.loop(skip_first=skip_first_screenshot):
            # 结束
            if self.appear(DORM_FEED_CHECK, offset=(20, 20)):
                break
            # 点击
            if self.handle_popup_cancel('DORM_FEED'):
                continue

    def _dorm_feed_reserved(self, button, count, reserve):
        """按剩余数量连续喂食，再核对库存并补点未完成的数量。

        Args:
            button (Button): 本轮选择的食物按钮。
            count (int): 本轮最多实际消耗的数量，不代表提交点击的次数。
            reserve (int): 需要保留的总库存，本次单个食物豁免时为零。

        Pages:
            in: DORM_FEED_CHECK，已有可用截图
            out: DORM_FEED_CHECK，库存或饱食度已确认到达本轮终点
        """
        index = self._dorm_food.buttons.index(button)
        target = None
        previous = None
        progress = Timer(15, count=3).start()
        self.popup_interval_clear()
        for _ in self.loop():
            remaining = 0
            handled = self.handle_popup_cancel('DORM_FEED') or self.handle_info_bar()
            if not handled and self.appear(DORM_FEED_CHECK, offset=(20, 20)):
                food, fill = self.dorm_food_get()
                if fill >= 0:
                    amount = food[index].amount
                    total = sum(f.amount for f in food)
                    if target is None:
                        target = max(amount - count, 0)
                    if previous is not None and amount < previous:
                        logger.attr('后宅食物实际消耗', previous - amount)
                        progress.reset()
                        # 只在库存确认减少后清理本按钮记录，吞操作仍保留连击检测。
                        self.device.click_record_remove(button)
                    previous = amount
                    if amount <= target or total <= reserve or fill <= food[index].feed:
                        return
                    remaining = min(amount - target, total - reserve, fill // food[index].feed)

            # 长批次先识别实际进展，避免把连点耗时误判为卡死。
            if progress.reached():
                raise GameStuckError('[宿舍-喂食] 未确认食物库存减少')
            if remaining > 0:
                self.device.multi_click(button, remaining)
                self.device.sleep(1)

    def dorm_food_get(self):
        """
        获取当前食物信息和饱食度。

        Returns:
            list[Food]: 食物列表。
            int: 剩余可喂食量。

        Pages:
            in: DORM_FEED_CHECK
        """
        has_food = [self._dorm_has_food(button) for button in self._dorm_food.buttons]
        amount = self._dorm_food_ocr.ocr(self.device.image)
        amount = [a if hf else 0 for a, hf in zip(amount, has_food)]
        food = [Food(feed=f, amount=a) for f, a in zip(FOOD_FEED_AMOUNT, amount)]
        current, fill, total = OCR_FILL.ocr(self.device.image)
        # 零库存是合法结果，槽位中的深色图案不能作为 OCR 失败的依据。
        if total not in OcrDormFood.VALID_TOTALS or current > total or fill < 0 or current + fill != total:
            fill = -1
        logger.info(f'[宿舍-食物] 食物库存: {[f.amount for f in food]}, 需填充: {fill}')
        return food, fill

    def _dorm_food_reserve(self, total):
        """记录当天首次可喂食检查，返回本次需要保留的食物总数。

        首次启用当天不豁免；之后按服务器日期换日，仅首次检查且总库存
        恰好为一个时豁免。操作前持久化，防止任务重试或重启重复豁免。

        Args:
            total (int): 六种食物的总库存，必须大于零。

        Returns:
            int: 通常保留一个，次日首次单个食物豁免时返回零。
        """
        today = current_time(timezone(server_timezone())).date().isoformat()
        state = self.config.Dorm_FeedReserveState
        previous = state.get('day') if isinstance(state, dict) else None
        if previous != today:
            self.config.Dorm_FeedReserveState = {'day': today}
            if isinstance(previous, str) and previous < today and total == 1:
                logger.info('[宿舍-喂食] 当天首次喂食仅剩一个食物，豁免保留一次')
                return 0
            logger.attr('后宅食物保留日期', today)
        return 1

    def dorm_feed_once(self):
        """
        执行一次喂食操作。

        Returns:
            bool: 是否执行了喂食。

        Pages:
            in: DORM_FEED_CHECK
        """
        timeout = Timer(1.5, count=3).start()
        food: t.List[Food] = []
        fill: int = 0
        for _ in self.loop():
            # 结束
            if timeout.reached():
                logger.warning('[宿舍-食物] 获取食物信息超时，可能食物为空')
                break

            if self.handle_info_bar():
                continue

            # 获取食物信息
            food, fill = self.dorm_food_get()
            if fill == -1:
                continue
            if sum([f.amount for f in food]) > 0:
                break
        if fill < 0:
            fill = 0

        FOOD_FILTER.load(self.config.Dorm_FeedFilter)
        for selected in FOOD_FILTER.apply(food):
            button = self._dorm_food.buttons[food.index(selected)]
            if selected.amount > 0 and fill > selected.feed:
                total = sum(f.amount for f in food)
                reserve = self._dorm_food_reserve(total) if self.config.Dorm_ReserveFood else 0
                count = min(fill // selected.feed, selected.amount)
                # 其他种类仍有库存或本种食物超出饱食度需求时，原方案不会用尽总库存。
                if self.config.Dorm_ReserveFood and count == total:
                    count -= reserve
                    if count <= 0:
                        logger.info('[宿舍-喂食] 保留最后一个食物到第二天使用')
                        return False
                    self._dorm_feed_click(button=button, count=count, reserve=reserve)
                else:
                    self._dorm_feed_click(button=button, count=count)
                return True

        return False

    def dorm_feed(self):
        """
        循环执行喂食直到可用食物用完或饱食度满。

        Returns:
            int: 执行喂食的次数。

        Pages:
            in: DORM_FEED_CHECK
        """
        logger.hr('后宅喂食')

        for n in range(10):
            if not self.dorm_feed_once():
                logger.info('[宿舍-喂食] 喂食完成')
                return n

        logger.warning('[宿舍-喂食] 喂食次数达到上限')
        return 10

    def dorm_feed_enter(self):
        """
        从宿舍主页进入喂食界面。

        处理可能遇到的管理界面、家具商店等中间状态。

        Pages:
            in: DORM_CHECK
            out: DORM_FEED_CHECK
        """
        self.interval_clear(DORM_CHECK)
        for _ in self.loop(skip_first=False):
            # 结束
            if self.appear(DORM_FEED_CHECK, offset=(20, 20)):
                break

            if self.ui_additional(get_ship=False):
                self.interval_clear(DORM_CHECK)
                continue
            if self.appear(DORM_CHECK, offset=(20, 20), interval=5):
                self.device.click(DORM_FEED_ENTER)
                continue
            if self.appear(DORM_MANAGE_CHECK, offset=(20, 20), interval=5):
                self.device.click(DORM_FURNITURE_SHOP_QUIT)
                logger.info(f'[宿舍-视角] {DORM_MANAGE_CHECK} -> {DORM_FURNITURE_SHOP_QUIT}')
                continue
            if self.appear(DORM_FURNITURE_SHOP_FIRST, offset=(20, 20), interval=5):
                self.device.click(DORM_FURNITURE_SHOP_QUIT)
                logger.info(f'[宿舍-视角] {DORM_FURNITURE_SHOP_FIRST} -> {DORM_FURNITURE_SHOP_QUIT}')
                continue
            if self.appear(DORM_FURNITURE_SHOP_FIRST_SELECTED, offset=(20, 20), interval=5):
                self.device.click(DORM_FURNITURE_SHOP_QUIT)
                logger.info(f'[宿舍-视角] {DORM_FURNITURE_SHOP_FIRST_SELECTED} -> {DORM_FURNITURE_SHOP_QUIT}')
                continue

    def dorm_feed_quit(self):
        """
        从喂食界面返回宿舍主页。

        Pages:
            in: DORM_FEED_CHECK
            out: DORM_CHECK
        """
        self.interval_clear(DORM_FEED_CHECK)
        for _ in self.loop():
            # 结束
            if self.appear(DORM_CHECK):
                break

            if self.appear(DORM_FEED_CHECK, offset=(20, 20), interval=5):
                self.device.click(DORM_FEED_ENTER)
                continue
            if self.handle_popup_cancel('DORM_FEED'):
                self.interval_clear(DORM_CHECK)
                continue
            if self.ui_additional(get_ship=False):
                self.interval_clear(DORM_CHECK)
                continue

    def dorm_buy_food_enter(self):
        """
        从喂食界面进入购买食物界面。

        Pages:
            in: DORM_FEED_CHECK
            out: DORM_BUY_FOOD_CHECK
        """
        self.interval_clear(DORM_FEED_CHECK)
        for _ in self.loop():
            # 结束
            if self.appear(DORM_BUY_FOOD_CHECK, offset=(20, 20)):
                break

            if self.match_template_color(DORM_FEED_CHECK, offset=(20, 20), interval=5):
                self.device.click(DORM_BUY_FOOD_ENTER)
                continue

    def dorm_buy_food(self, amount):
        """
        设置购买食物的数量。

        Pages:
            in: DORM_BUY_FOOD_CHECK
            out: DORM_BUY_FOOD_CHECK
        """
        logger.hr('后宅购买食物')
        index_offset = (20, 20)
        # 防止 +/- 按钮位置偏移，使用船坞 OCR 技巧准确解析
        self.appear(FOOD_PLUS, offset=index_offset)
        self.appear(FOOD_MINUS, offset=index_offset)

        self.ui_ensure_index(amount, letter=OCR_BUY_FOOD_AMOUNT, prev_button=FOOD_MINUS, next_button=FOOD_PLUS,
                             skip_first_screenshot=True)
        return True

    def dorm_buy_food_confirm(self):
        """
        确认购买食物并返回喂食界面。

        Pages:
            in: DORM_BUY_FOOD_CHECK
            out: DORM_FEED_CHECK
        """
        self.interval_clear(DORM_BUY_FOOD_CONFIRM)
        purchase = self.dorm_oil_price()
        sent = False
        for _ in self.loop():
            # 结束
            if self.match_template_color(DORM_FEED_CHECK, offset=(20, 20)):
                if sent and purchase:
                    from module.statistics.resource_flow import record
                    record(self.config, {'Oil': -purchase[1], 'Food': purchase[0]}, '后宅购粮')
                break

            if self.appear_then_click(DORM_BUY_FOOD_CONFIRM, offset=(20, 20), interval=5):
                sent = True
                continue

    def dorm_food_run(self, amount):
        """
        执行购买食物的完整流程。

        Args:
            amount (int): 购买食物的数量。

        Pages:
            in: 任意页面
            out: page_dorm
        """
        if amount <= 0:
            return

        self.ui_ensure(page_dormmenu)
        self.handle_info_bar()
        self.ui_goto(page_dorm, skip_first_screenshot=True)
        logger.hr('后宅购买食物', level=1)
        self.dorm_feed_enter()
        self.dorm_buy_food_enter()
        self.dorm_buy_food(amount=amount)
        self.dorm_buy_food_confirm()
        self.dorm_feed_quit()

    def dorm_oil_price(self):
        """购买弹窗同时确认石油图标、数量和总价，拒绝钻石计价。"""
        if not self.appear(TEMPLATE_DORM_OIL_COST, offset=(20, 20)):
            return None
        amount = OCR_BUY_FOOD_AMOUNT.ocr(self.device.image)
        cost = OCR_BUY_OIL_COST.ocr(self.device.image)
        if (not OCR_BUY_FOOD_AMOUNT.last_valid or not OCR_BUY_OIL_COST.last_valid
                or amount <= 0 or cost <= 0 or cost % amount):
            return None
        return amount, cost

    def dorm_oil_quantity(self, amount, unit_cost):
        """有界调整数量；界面限制数量时使用已确认的较小数量。"""
        self.appear(FOOD_PLUS, offset=(20, 20))
        self.appear(FOOD_MINUS, offset=(20, 20))
        previous = None
        observation = None
        for _ in self.loop(skip_first=False, timeout=30):
            row = self.dorm_oil_price()
            if row is None:
                observation = None
                continue
            if row != observation:
                observation = row
                continue
            current, cost = row
            if cost != current * unit_cost:
                return None
            if current == amount or (current == previous and current < amount):
                return current, cost
            previous = current
            observation = None
            self.device.multi_click(FOOD_PLUS if current < amount else FOOD_MINUS,
                                    n=min(abs(amount - current), 50), interval=(0.1, 0.15))
        logger.warning('[宿舍-购粮] 数量调整超时，取消购买')
        return None

    def dorm_buy_oil_food(self, oil, target):
        """为原调度清油购买以石油计价的食物，不修改日常后宅设置。

        Args:
            oil (int): 购买前可靠观察的石油。
            target (int): 需要降到其以下的石油控制线。

        Returns:
            bool: 购买已确认并返回喂食页；实际消耗由调度器重新观察。

        Pages:
            in: 任意页面
            out: page_dorm
        """
        from module.scheduler.resources import stable_read
        self._oil_food_purchase = None
        if oil < target or oil <= 500:
            return False
        self.ui_ensure(page_dormmenu)
        self.handle_info_bar()
        self.ui_goto(page_dorm, skip_first_screenshot=True)
        self.dorm_feed_enter()
        entered = False
        for _ in self.loop(skip_first=False, timeout=10):
            if self.appear(TEMPLATE_DORM_OIL_COST, offset=(20, 20)):
                entered = True
                break
            if self.match_template_color(DORM_FEED_CHECK, offset=(20, 20), interval=3):
                self.device.click(DORM_BUY_FOOD_ENTER)
                continue
            if self.handle_info_bar():
                continue
        if not entered:
            logger.warning('[宿舍-购粮] 无法进入石油购粮弹窗')
            self.dorm_feed_quit()
            return False
        row = stable_read(self, lambda: self.appear(TEMPLATE_DORM_OIL_COST, offset=(20, 20)), self.dorm_oil_price)
        if row is None:
            logger.warning('[宿舍-购粮] 无法可靠确认石油价格')
            self.dorm_feed_quit()
            return False
        unit_cost = row[1] // row[0]
        # 最小数量使余油严格低于目标，且不突破已有的 500 石油安全网。
        amount = min((oil - target) // unit_cost + 1, (oil - 500) // unit_cost)
        row = self.dorm_oil_quantity(amount, unit_cost) if amount > 0 else None
        if row is None or row[1] > oil - 500:
            self.dorm_feed_quit()
            return False
        logger.attr('石油控制-购粮数量', row[0])
        logger.attr('石油控制-购粮花费', row[1])
        confirmed = False
        sent = False
        for _ in self.loop(skip_first=False, timeout=10):
            if self.match_template_color(DORM_FEED_CHECK, offset=(20, 20)):
                confirmed = sent
                break
            stop = getattr(getattr(self, 'config', None), 'stop_event', None)
            if stop and stop.is_set():
                break
            if self.appear(TEMPLATE_DORM_OIL_COST, offset=(20, 20)):
                if self.appear_then_click(DORM_BUY_FOOD_CONFIRM, offset=(20, 20), interval=3):
                    sent = True
                    continue
            if self.handle_info_bar():
                continue
        self.dorm_feed_quit()
        if confirmed:
            self._oil_food_purchase = row
        return confirmed

    def dorm_run(self, feed=True, collect=True, buy_furniture=False):
        """
        执行宿舍操作：喂食、收取、购买家具。

        操作顺序：先喂食（处理 DORM_INFO 弹窗避免遮挡），再收取金币和爱心，
        最后购买家具。

        Args:
            feed (bool): 是否执行喂食。
            collect (bool): 是否收取金币和爱心。
            buy_furniture (bool): 是否购买家具。

        Pages:
            in: 任意页面
            out: page_dorm
        """
        if not feed and not collect and not buy_furniture:
            return

        self.ui_ensure(page_dormmenu)
        self.handle_info_bar()
        # 2025.10.17 移除 DORM_RED_DOT 检查，因为宿舍卡片有缓慢的出现动画
        # if not self.appear(DORM_RED_DOT, offset=(30, 30)):
        #     logger.info('Nothing to collect. Dorm collecting skipped.')
        #     collect = False
        #     if not feed and not buy_furniture:
        #         return
        self.ui_goto(page_dorm, skip_first_screenshot=True)

        # 先喂食以处理 DORM_INFO
        # DORM_INFO 可能会遮挡宿舍金币和爱心
        if feed:
            logger.hr('后宅喂食', level=1)
            self.dorm_feed_enter()
            self.dorm_feed()
            self.dorm_feed_quit()

        if collect:
            logger.hr('后宅收取', level=1)
            self.dorm_collect()

        if buy_furniture:
            logger.hr('后宅购买家具', level=1)
            BuyFurniture(self.config, self.device).run()

    def get_dorm_ship_amount(self):
        """
        获取宿舍中的舰船数量。

        Returns:
            int: 宿舍中的舰船数量。

        Pages:
            in: page_dorm
        """
        timeout = Timer(2, count=4).start()
        current = 0
        for _ in self.loop():
            # 处理弹窗
            if self.appear_then_click(DORM_FURNITURE_CONFIRM, offset=(30, 30), interval=3):
                timeout.reset()
                continue
            if self.ui_additional(get_ship=False):
                timeout.reset()
                continue

            current, _, total = OCR_SLOT.ocr(self.device.image)

            if timeout.reached():
                logger.warning('[宿舍-栏位] 获取宿舍栏位超时')
                break
            if total == 0:
                continue
            elif current not in [0, 1, 2, 3, 4, 5, 6]:
                logger.warning(f'[宿舍-栏位] 无效的宿舍栏位数量: {current}')
                continue
            else:
                break

        return current

    def cal_dorm_delay(self, ships):
        """
        计算宿舍任务的延迟时间（分钟）。

        计算公式：(任务延迟) = 20000 / (每 15 秒食物消耗) * 15 / 60

        | 宿舍舰船数 | 每 15 秒食物消耗 | 任务延迟（分钟） |
        | ----------- | ---------------- | ---------------- |
        | 0           | 0                | 278              |
        | 1           | 5                | 1000             |
        | 2           | 9                | 556              |
        | 3           | 12               | 417              |
        | 4           | 14               | 358              |
        | 5           | 16               | 313              |
        | 6           | 18               | 278              |

        Args:
            ships (int): 宿舍中的舰船数量。

        Returns:
            int: 延迟分钟数。

        Pages:
            in: page_dorm
        """
        dict_delay = {
            0: self.config.Scheduler_SuccessInterval,
            1: 1000,
            2: 556,
            3: 417,
            4: 358,
            5: 313,
            6: 278,
        }
        delay = dict_delay.get(ships, self.config.Scheduler_SuccessInterval)
        return delay

    def run(self):
        """
        执行宿舍任务的主入口。

        Pages:
            in: 任意页面
            out: page_dorm
        """
        if not self.config.Dorm_Feed and not self.config.Dorm_Collect \
                and not self.config.BuyFurniture_Enable:
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        self.dorm_run(feed=self.config.Dorm_Feed,
                      collect=self.config.Dorm_Collect,
                      buy_furniture=self.config.BuyFurniture_Enable)

        # Scheduler
        ships = self.get_dorm_ship_amount()
        delay = self.cal_dorm_delay(ships)
        logger.info(f'[宿舍-调度] 宿舍舰船数: {ships}, 任务延迟: {delay}')
        self.config.task_delay(minute=delay)

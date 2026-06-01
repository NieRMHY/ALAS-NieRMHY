from module.combat.assets import GET_ITEMS_1
from module.logger import logger
from module.meowfficer.assets import *
from module.meowfficer.base import MeowfficerBase
from module.ocr.ocr import Digit, DigitCounter
from module.ui.assets import MEOWFFICER_GOTO_DORMMENU

BUY_MAX = 15
BUY_PRIZE = 1500
MEOWFFICER = DigitCounter(OCR_MEOWFFICER, letter=(140, 113, 99), threshold=64)
MEOWFFICER_CHOOSE = Digit(OCR_MEOWFFICER_CHOOSE, letter=(140, 113, 99), threshold=64)
MEOWFFICER_COINS = Digit(OCR_MEOWFFICER_COINS, letter=(99, 69, 41), threshold=64)


class MeowfficerBuy(MeowfficerBase):
    def meow_get_buy_count(self) -> int:
        """
        OCR 识别剩余购买次数和金币数量，结合用户配置决定本次购买多少个指挥喵箱。

        基础购买：每天最多购买 Meowfficer_BuyAmount 个。
        溢出购买：当 Meowfficer_OverflowCoins 不为 -1 且当前金币超过阈值时，
        持续购买额外箱子，直到金币降至阈值以下或今日配额用完。每天第 1 个箱子免费。

        Pages:
            in: page_meowfficer

        Returns:
            int: 0 到 BUY_MAX，本次购买的箱子数量。
        """
        self.device.screenshot()
        remain, bought, total = MEOWFFICER.ocr(self.device.image)
        coins = MEOWFFICER_COINS.ocr(self.device.image)
        logger.attr('Meowfficer_remain', remain)
        logger.attr('Meowfficer_coins', coins)

        if total != BUY_MAX:
            logger.warning(f'Invalid meowfficer buy limit: {total}, revise to {BUY_MAX}')
            total = BUY_MAX
            bought = total - remain

        today_left = max(0, total - bought)
        if today_left <= 0:
            logger.info(f'Already bought {bought}/{total} today, stopped')
            return 0

        # 基础购买
        baseline = min(max(0, self.config.Meowfficer_BuyAmount - bought), today_left)

        # 溢出购买
        overflow_th = self.config.Meowfficer_OverflowCoins
        extra = 0
        if overflow_th != -1 and coins > overflow_th:
            extra = -(-(coins - overflow_th) // BUY_PRIZE)
            extra = min(extra, today_left - baseline)
            extra = max(0, extra)

        count = baseline + extra

        # 根据可负担的金币数量限制购买数量，每天第 1 个箱子免费
        free = 1 if bought == 0 else 0
        affordable = coins // BUY_PRIZE + free
        if count > affordable:
            logger.info(f'Current coins only afford to buy {affordable}')
            count = affordable

        logger.info(
            f'Meowfficer buy plan: count={count}, baseline={baseline}, '
            f'overflow={extra}, bought={bought}/{total}, coins={coins}'
        )
        return count

    def meow_choose(self, count) -> None:
        """
        导航到购买界面并设置购买数量为 `count`。

        Pages:
            in: page_meowfficer
            out: MEOWFFICER_BUY

        Args:
            count (int): 1 到 BUY_MAX。
        """
        self.meow_enter(MEOWFFICER_BUY_ENTER, check_button=MEOWFFICER_BUY)
        self.ui_ensure_index(count, letter=MEOWFFICER_CHOOSE, prev_button=MEOWFFICER_BUY_PREV,
                             next_button=MEOWFFICER_BUY_NEXT, skip_first_screenshot=True)

    def meow_confirm(self, skip_first_screenshot=True) -> None:
        """
        确认购买并处理购买后的各种弹窗。

        Pages:
            in: MEOWFFICER_BUY
            out: page_meowfficer
        """
        # 使用简单点击，避免多次点击 MEOWFFICER_BUY
        logger.hr('Meow confirm')
        executed = False
        with self.stat.new(
                genre="meowfficer_buy",
                method=self.config.DropRecord_MeowfficerBuy,
        ) as drop:
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                if self.appear(MEOWFFICER_BUY, offset=(20, 20), interval=3):
                    if executed:
                        self.device.click(MEOWFFICER_GOTO_DORMMENU)
                    else:
                        self.device.click(MEOWFFICER_BUY)
                    continue
                if self.handle_meow_popup_confirm():
                    executed = True
                    continue
                if self.appear_then_click(MEOWFFICER_BUY_SKIP, interval=3):
                    executed = True
                    continue
                if self.appear(GET_ITEMS_1, offset=5, interval=3):
                    if drop.save is True:
                        drop.handle_add(self, before=2)
                    self.device.click(MEOWFFICER_BUY_SKIP)
                    self.interval_clear(MEOWFFICER_BUY)
                    executed = True
                    continue
                # 少见情况：MEOWFFICER_INFO 在此处弹出
                if self.meow_additional():
                    continue

                # 结束
                if self.match_template_color(MEOWFFICER_BUY_ENTER, offset=(20, 20)):
                    break

    def meow_buy(self) -> None:
        """
        根据基础购买和可选的溢出购买计划购买指挥喵箱。

        Pages:
            in: page_meowfficer
            out: page_meowfficer
        """
        logger.hr('Meowfficer buy', level=1)
        count = self.meow_get_buy_count()
        if count <= 0:
            return
        self.meow_choose(count)
        self.meow_confirm()

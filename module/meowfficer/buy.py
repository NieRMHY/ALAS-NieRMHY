"""指挥喵购买模块。

处理指挥喵猫箱的购买操作，包括：
- 普通购买：根据配置的购买数量和金币余额购买猫箱
- 溢出购买：当金币超过阈值时自动购买猫箱以避免资源浪费

购买机制说明：
- 每日购买上限：15 个猫箱
- 每个猫箱价格：1500 金币
- 首次购买免费（每日第一个猫箱不消耗金币）
- 购买数量支持 OCR 识别剩余次数和金币余额

配置项前缀：`Meowfficer_BuyAmount`、`Meowfficer_OverflowBuyThreshold`
"""

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
    """指挥喵购买处理器。

    负责指挥喵猫箱的购买操作，支持普通购买和金币溢出购买两种模式。

    Attributes:
        config.Meowfficer_BuyAmount (int): 每日计划购买的猫箱数量。
        config.Meowfficer_OverflowBuyThreshold (int): 金币溢出购买阈值，
            金币超过此值时自动购买猫箱。
    """
    def meow_choose(self, count) -> bool:
        """选择计划购买的指挥喵猫箱数量。

        识别当前已购买数量与金币余额，校验是否可购买，并设置购买数字。

        Args:
            count (int): 目标购买数量（0 到 15）。

        Returns:
            bool: 成功设置购买数量并进入购买弹窗返回 True；无需购买或金币不足返回 False。

        Pages:
            in: page_meowfficer
            out: MEOWFFICER_BUY
        """
        remain, bought, total = MEOWFFICER.ocr(self.device.image)
        logger.attr('指挥喵剩余次数', remain)

        # 检查购买状态
        if total != BUY_MAX:
            logger.warning(f'[指挥喵-购买] 无效的购买上限: {total}，修正为 {BUY_MAX}')
            total = BUY_MAX
            bought = total - remain
        if bought > 0:
            if bought >= count:
                logger.info(f'[指挥喵-购买] 今天已购买 {bought} 个，停止')
                return False
            else:
                count -= bought
                logger.info(f'[指挥喵-购买] 今天已购买 {bought} 个，还需要购买 {count} 个')

        # 检查金币
        coins = MEOWFFICER_COINS.ocr(self.device.image)
        if (coins < BUY_PRIZE) and (remain < total):
            logger.info('[指挥喵-购买] 金币不足以购买一个，停止')
            return False
        elif (count - int(remain == total)) * BUY_PRIZE > coins:
            count = coins // BUY_PRIZE + int(remain == total)
            logger.info(f'[指挥喵-购买] 当前金币只够购买 {count} 个')

        self.meow_enter(MEOWFFICER_BUY_ENTER, check_button=MEOWFFICER_BUY)
        self.ui_ensure_index(count, letter=MEOWFFICER_CHOOSE, prev_button=MEOWFFICER_BUY_PREV,
                             next_button=MEOWFFICER_BUY_NEXT, skip_first_screenshot=True)
        return True

    def meow_confirm(self, skip_first_screenshot=True) -> None:
        """确认购买指挥喵猫箱并处理掉落与返回。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

        Pages:
            in: MEOWFFICER_BUY
            out: page_meowfficer
        """
        # 此处使用单次点击，避免重复点击 MEOWFFICER_BUY；重试逻辑在 meow_buy() 中处理
        logger.hr('确认购买')
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
                # 罕见情况：此处可能弹出 MEOWFFICER_INFO
                if self.meow_additional():
                    continue

                # 判定结束
                if self.match_template_color(MEOWFFICER_BUY_ENTER, offset=(20, 20)):
                    break

    def meow_buy(self) -> bool:
        """执行日常指挥喵猫箱购买任务。

        根据配置中的计划购买数量重试并完成购买。

        Returns:
            bool: 购买成功或无需购买返回 True，超出重试次数返回 False。

        Pages:
            in: page_meowfficer
            out: page_meowfficer
        """
        logger.hr('指挥喵购买', level=1)

        for _ in range(3):
            if self.meow_choose(count=self.config.Meowfficer_BuyAmount):
                self.meow_confirm()
            else:
                return True

        logger.warning('[指挥喵-购买] 尝试次数过多，停止')
        return False

    def meow_overflow_buy(self, overflow_coins):
        """金币溢出时购买猫箱，直到金币降至阈值以下。

        根据当前金币与溢出阈值的差值计算需要购买的猫箱数量，
        考虑每日15个购买限制和首抽免费机制。
        不依赖金币OCR判断是否触发购买（由调用方判断），
        仅负责在指挥喵界面执行购买操作。

        Args:
            overflow_coins (int): 金币溢出阈值，金币超过此值时购买猫箱

        Pages:
            in: page_meowfficer
            out: page_meowfficer
        """
        logger.hr('指挥喵溢出购买', level=1)

        # OCR识别剩余购买次数
        remain, bought, total = MEOWFFICER.ocr(self.device.image)
        logger.attr('指挥喵剩余次数', remain)
        logger.attr('指挥喵已购买次数', bought)

        # 每日限制检查
        if total != BUY_MAX:
            logger.warning(f'[指挥喵-溢出] 无效的购买上限: {total}，修正为 {BUY_MAX}')
            total = BUY_MAX
            bought = total - remain

        if bought >= BUY_MAX:
            logger.info(f'[指挥喵-溢出] 今天已购买 {bought} 个，达到每日上限，跳过')
            return

        # OCR识别金币
        coins = MEOWFFICER_COINS.ocr(self.device.image)
        logger.attr('指挥喵金币', coins)

        if coins <= overflow_coins:
            logger.info(f'[指挥喵-溢出] 金币 {coins} <= 阈值 {overflow_coins}，跳过')
            return

        # 计算溢出购买数量
        today_left = total - bought
        # 向上取整：需要购买多少个猫箱才能将金币降到阈值以下
        overflow_count = -(-(coins - overflow_coins) // BUY_PRIZE)
        # 限制在今日剩余数量内
        count = min(overflow_count, today_left)

        # 考虑首抽免费：如果剩余=总数（一个都没买），第一个免费
        free = 1 if remain == total else 0
        # 检查金币是否足够
        affordable = coins // BUY_PRIZE + free
        if count > affordable:
            count = affordable
            logger.info(f'[指挥喵-溢出] 金币只够购买 {count} 个指挥喵')

        if count <= 0:
            logger.info('[指挥喵-溢出] 没有指挥喵可购买，跳过')
            return

        logger.info(f'[指挥喵-溢出] 溢出购买数量: {count} (溢出计算={overflow_count}, 今日剩余={today_left})')

        # 执行购买
        # 传入总共需要达到的数量（已买 + 还需买），meow_choose 会自动计算差额
        if self.meow_choose(count=count + bought):
            self.meow_confirm()
        else:
            logger.info('[指挥喵-溢出] 溢出购买被 meow_choose 跳过')

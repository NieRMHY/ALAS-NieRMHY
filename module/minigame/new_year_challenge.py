"""新年挑战小游戏自动化模块。
通过颜色识别按钮状态和 OCR 读取得分与消耗，
自动完成小游戏的循环战斗操作。"""

from module.base.timer import Timer
from module.logger import logger
from module.minigame.assets import *
from module.minigame.minigame import MINIGAME_SCROLL, MinigameRun
from module.ocr.ocr import Digit
from module.ui.page import page_game_room

OCR_GAME_NEW_YEAR_COIN_COST = Digit(NEW_YEAR_CHALLENGE_COIN_COST_HOLDER,
                                    name='OCR_GAME_NEW_YEAR_COIN_COST',
                                    letter=(33, 28, 49),
                                    threshold=128)
OCR_NEW_YEAR_BATTLE_SCORE = Digit(NEW_YEAR_CHALLENGE_SCORE_HOLDER,
                                  name='OCR_NEW_YEAR_BATTLE_SCORE',
                                  letter=(231, 215, 82),
                                  threshold=128)


class NewYearChallenge(MinigameRun):
    NEW_YEAR_BATTLE_RED = (255, 150, 123)
    NEW_YEAR_BATTLE_YELLOW = (247, 223, 115)
    NEW_YEAR_BATTLE_BLUE = (82, 134, 239)
    NEW_YEAR_BATTLE_TMP_BUTTON = [NEW_YEAR_CHALLENGE_TMP_1,
                                  NEW_YEAR_CHALLENGE_TMP_2,
                                  NEW_YEAR_CHALLENGE_TMP_3,
                                  NEW_YEAR_CHALLENGE_TMP_4,
                                  NEW_YEAR_CHALLENGE_TMP_5]
    NEW_YEAR_BATTLE_COLOR_BUTTON_DICT = {NEW_YEAR_BATTLE_RED: NEW_YEAR_CHALLENGE_RED_BUTTON,
                                         NEW_YEAR_BATTLE_YELLOW: NEW_YEAR_CHALLENGE_YELLOW_BUTTON,
                                         NEW_YEAR_BATTLE_BLUE: NEW_YEAR_CHALLENGE_BLUE_BUTTON}

    def deal_specific_popup(self):
        """处理新年挑战特有的弹窗（首次进入提示等）。

        Returns:
            bool: 成功处理弹窗返回 True，否则返回 False。
        """
        # 首次进入新年挑战时的提示
        if self.appear(NEW_YEAR_CHALLENGE_FIRST_TIME, offset=(5, 5), interval=3):
            self.device.click(NEW_YEAR_CHALLENGE_SAFE_AREA)
            return True
        return False

    def choose_game(self, skip_first_screenshot=True):
        """从游戏列表中滚动并选择新年挑战小游戏。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: page_game_room 选游戏界面
            out: page_game_room 新年挑战准备界面
        """
        self.interval_clear(page_game_room.check_button)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.deal_popup():
                continue
            # 入口
            if self.appear(NEW_YEAR_CHALLENGE_START, offset=(5, 5)):
                break
            # GOTO_CHOOSE_GAME -> 选游戏界面
            if self.appear_then_click(GOTO_CHOOSE_GAME, offset=(5, 5), interval=3):
                continue
            # 选择游戏
            if self.appear(NEW_YEAR_CHALLENGE_ENTRANCE, offset=(5, 500), interval=3):
                self.device.click(NEW_YEAR_CHALLENGE_ENTRANCE)
                self.interval_reset(page_game_room.check_button, interval=3)
                continue
            # 向下滚动查找
            if self.ui_page_appear(page_game_room, interval=3) and MINIGAME_SCROLL.appear(main=self) \
                    and not MINIGAME_SCROLL.set(main=self, position=0.25, distance_check=False):
                MINIGAME_SCROLL.set_bottom(main=self)
                continue

    def use_coin(self, skip_first_screenshot=True):
        """投入代币（默认投入 5 枚）。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 成功投币返回 True，否则返回 False。
        """
        return self.use_coin_new_year_challenge(count=5)

    def play_game(self, skip_first_screenshot=True):
        """执行新年挑战小游戏的单局游玩逻辑。

        识别颜色提示序列并快速响应点击，当得分达到阈值（>1000）后停止游玩等待结算。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: page_game_room 新年挑战准备界面
            out: page_game_room 新年挑战结算界面
        """
        score_ocr_interval = Timer(0.6, count=5).start()
        started = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.deal_popup():
                continue
            # 单回合判断
            if self.appear(NEW_YEAR_CHALLENGE_CHOOSING, offset=(5, 5), interval=3):
                self.new_year_challenge_turn(skip_first_screenshot=False)
                self.device.click_record_clear()
                continue
            # 等待选择或提前结束
            if score_ocr_interval.reached() and self.appear(NEW_YEAR_CHALLENGE_STOP_PLAY, offset=(5, 5)):
                # 分数足够时提前结束游玩
                score = OCR_NEW_YEAR_BATTLE_SCORE.ocr(self.device.image)
                score_ocr_interval.reset()
                if score > 1000 and self.appear_then_click(NEW_YEAR_CHALLENGE_STOP_PLAY, offset=(5, 5), interval=3):
                    continue
            # 游戏结束
            if self.appear(NEW_YEAR_CHALLENGE_END, offset=(5, 5), interval=3):
                break
            # 游戏规则介绍或开始按钮
            if self.appear(NEW_YEAR_CHALLENGE_START, offset=(5, 5), interval=3):
                if started:
                    self.interval_clear(NEW_YEAR_CHALLENGE_START)
                    break
                else:
                    started = True
                    self.device.click(NEW_YEAR_CHALLENGE_START)
                    continue

    def exit_game(self, skip_first_screenshot=True):
        """退出新年挑战返回至游戏室界面。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: page_game_room 结算界面
            out: page_game_room 选游戏界面
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.deal_popup():
                continue
            if self.appear(BACK, offset=(5, 5)):
                if self.appear(GOTO_CHOOSE_GAME, offset=(5, 5)):
                    break
                else:
                    self.appear_then_click(BACK, offset=(5, 5), interval=3)
                    continue
            if self.appear_then_click(NEW_YEAR_CHALLENGE_END, offset=(5, 5), interval=3):
                continue
            if self.appear_then_click(NEW_YEAR_CHALLENGE_EXIT, offset=(5, 5), interval=3):
                continue

    def use_coin_new_year_challenge(self, skip_first_screenshot=True, count=1):
        """调整新年挑战小游戏的代币消耗量。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。
            count (int): 目标投入代币数量，默认为 1。

        Returns:
            bool: 成功投入代币返回 True，无法投入或已达每月上限返回 False。
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.deal_popup():
                continue
            if self.appear(NEW_YEAR_CHALLENGE_ADD_COIN, offset=(5, 5)):
                # 增加代币投入量
                if count > 1:
                    for i in range(count - 1):
                        self.device.click(NEW_YEAR_CHALLENGE_ADD_COIN)
                    self.device.screenshot()
                # 测试时不消耗代币
                if count < 1:
                    self.appear_then_click(NEW_YEAR_CHALLENGE_DEC_COIN, offset=(5, 5), interval=3)
                    self.device.screenshot()
                coin_cost_after_add = OCR_GAME_NEW_YEAR_COIN_COST.ocr(self.device.image)
                logger.info(f"[小游戏] 投入代币后消耗数量: {coin_cost_after_add}")
                if count >= 1 and coin_cost_after_add <= 0:
                    # 无法增加代币：代币为 0 或已领完全月奖励
                    return False
                return True

    def new_year_challenge_turn(self, skip_first_screenshot=True):
        """执行单回合的颜色按键序列识别与点击。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。
        """
        if not skip_first_screenshot:
            self.device.screenshot()
        to_clicks = []
        # 判断待点击的颜色按钮
        for to_judge in self.NEW_YEAR_BATTLE_TMP_BUTTON:
            for color, button in self.NEW_YEAR_BATTLE_COLOR_BUTTON_DICT.items():
                if self.image_color_count(to_judge, color, threshold=30, count=10):
                    to_clicks.append(button)
                    break
        logger.info(f"[小游戏] 待点击按钮: {to_clicks}")
        to_clicks.reverse()
        # 点击序列
        click_interval = Timer(0.2, count=5).start()
        while 1:
            if to_clicks and click_interval.reached():
                self.device.click(to_clicks.pop())
                click_interval.reset()
            if not to_clicks:
                break

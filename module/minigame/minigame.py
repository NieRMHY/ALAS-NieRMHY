"""
小游戏自动化模块。

管理学院游戏室（Game Room）中的小游戏自动化流程。
负责游戏券/代币的收集、小游戏选择、游玩和退出。

主要功能：
    - OCR 识别当前代币数量
    - 自动收集游戏代币
    - 导航至游戏室主页
    - 选择并游玩特定小游戏（如新年挑战）
    - 处理弹窗（代币已满、游戏券不足等）

代币机制：
    - 最大代币上限为 40，OCR 超过 40 时截断
    - 代币数量 <= 30 时尝试自动收集
    - 代币为 0 时结束游玩循环
    - 每局游玩后根据配置决定下次游玩时间

依赖关系：
    - MinigameRun: 小游戏运行基类，定义选择/游玩/退出模板方法
    - Minigame: 主任务类，组合代币管理、游戏室导航和游玩循环

Pages:
    游戏室页面：page_game_room
    学院页面：page_academy
"""

import module.config.server as server
from module.combat.assets import GET_ITEMS_1
from module.logger import logger
from module.minigame.assets import *
from module.ocr.ocr import Digit
from module.ui.assets import ACADEMY_GOTO_GAME_ROOM, GAME_ROOM_CHECK
from module.ui.page import page_academy, page_game_room
from module.ui.scroll import Scroll
from module.ui.ui import UI

if server.server != 'jp':
    OCR_COIN = Digit(COIN_HOLDER,
                    name='OCR_COIN',
                    letter=(255, 235, 115),
                    threshold=128)
else:
    OCR_COIN = Digit(COIN_HOLDER,
                    name='OCR_COIN',
                    letter=(211, 196, 95),
                    threshold=128)
MINIGAME_SCROLL = Scroll(MINIGAME_SCROLL_AREA, color=(247, 247, 247), name='MINIGAME_SCROLL')

class MinigameRun(UI):
    """
    小游戏运行基类。

    定义小游戏的通用运行流程模板：导航至游戏列表、选择游戏、
    投入代币、游玩、退出。具体游戏逻辑由子类实现。

    子类需要重写以下方法：
        - choose_game(): 从游戏列表中选择目标游戏
        - use_coin(): 投入代币并准备游玩
        - play_game(): 执行游戏的具体操作
        - exit_game(): 退出当前游戏
        - deal_specific_popup(): 处理特定游戏的弹窗

    属性:
        无额外属性，所有状态通过方法参数传递
    """

    def minigame_run(self, skip_first_screenshot=True):
        """执行单次小游戏的进入、选择、投币、游玩与退出流程。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 成功投币并完成游玩返回 True，无法投币或跳过游玩返回 False。

        Pages:
            in: page_game_room 主页
            out: page_game_room 主页
        """
        logger.hr('[小游戏] 运行', level=1)

        # page_game_room main_page -> MINIGAME_SCROLL
        logger.info("[小游戏] 进入小游戏")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            # 结束判断：列表界面出现
            if self.appear(GAME_ROOM_CHECK, offset=(5, 5)) and not self.appear(GOTO_CHOOSE_GAME, offset=(20, 20)):
                if MINIGAME_SCROLL.appear(main=self):
                    break
            # 处理无法获取更多游戏券等弹窗
            if self.deal_popup():
                continue
            if self.appear_then_click(GOTO_CHOOSE_GAME, offset=(5, 5), interval=3):
                continue

        logger.info("[小游戏] 选择小游戏")
        self.choose_game()
        # 尝试投币，失败则跳过游玩
        add_coin_result = self.use_coin()
        if add_coin_result:
            logger.hr("[小游戏] 游玩", level=2)
            self.play_game()
        logger.info("[小游戏] 退出小游戏")
        self.exit_game()
        return add_coin_result

    def deal_popup(self):
        """处理可能出现的弹窗（代币已满、获得物品等）。

        Returns:
            bool: 成功处理了弹窗返回 True，需要重新截图。
        """
        if self.deal_specific_popup():
            return True
        if self.handle_popup_confirm('TICKETS_FULL'):
            self.interval_reset(COIN_POPUP, interval=3)
            return True
        # 代币超过 31 枚时处理弹窗
        if self.appear_then_click(COIN_POPUP, offset=(5, 5), interval=3):
            return True
        # 收到代币或游戏券
        if self.appear_then_click(GET_ITEMS_1, offset=(5, 5), interval=3):
            return True
        return False

    def deal_specific_popup(self):
        """处理特定小游戏专有的弹窗，由子类重写。

        Returns:
            bool: 是否处理了弹窗。
        """
        return False

    def choose_game(self, skip_first_screenshot=True):
        """在游戏列表中选择目标小游戏，由子类实现。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: page_game_room 选游戏界面
            out: page_game_room 游戏入口界面
        """
        pass

    def use_coin(self, skip_first_screenshot=True):
        """投入代币准备游玩，由子类实现。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 成功投币返回 True，否则返回 False。
        """
        return False

    def play_game(self, skip_first_screenshot=True):
        """执行小游戏的具体游玩操作，由子类实现。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。
        """
        pass

    def exit_game(self, skip_first_screenshot=True):
        """退出当前小游戏返回至游戏室界面，由子类实现。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: page_game_room 游戏结束界面
            out: page_game_room 选游戏界面
        """
        pass


class Minigame(UI):
    """
    小游戏主任务类。

    管理小游戏任务的完整生命周期：从学院页面导航到游戏室，
    收集代币，选择并游玩小游戏，直到代币耗尽或达到游玩上限。

    流程概要：
        1. 从任意页面导航至学院 -> 游戏室主页
        2. OCR 读取代币数量
        3. 代币 <= 30 时尝试自动收集
        4. 代币 > 0 时选择小游戏并游玩（最多 10 次）
        5. 代币耗尽后调度下次运行

    配置项:
        通过 self.config.task_delay(server_update=True) 调度下次运行

    Pages:
        任务入口页面：任意页面
        任务结束页面：page_game_room
    """

    def get_coin_amount(self, skip_first_screenshot=True):
        """识别当前拥有的游戏代币数量。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            int: 代币数量（上限截断至 40）。

        Pages:
            in: page_game_room 主页
            out: page_game_room 主页
        """
        if not skip_first_screenshot:
            self.device.screenshot()
        amount = OCR_COIN.ocr(self.device.image)
        if amount >= 40:
            amount = 40
        return amount

    def go_to_main_page(self, skip_first_screenshot=True):
        """返回游戏室主界面。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: page_game_room 主页或选游戏界面
            out: page_game_room 主页
        """
        logger.info('[小游戏] 前往主页')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.ui_additional():
                continue
            if self.appear_then_click(COIN_POPUP, offset=(5, 5), interval=2):
                continue
            if self.appear(GAME_ROOM_CHECK, offset=(5, 5)) \
                    and not self.appear(GOTO_CHOOSE_GAME, offset=(5, 5)):
                self.appear_then_click(BACK, offset=(5, 5), interval=2)
                continue
            if self.appear(GOTO_CHOOSE_GAME, offset=(5, 5)):
                break

    def collect_coin(self, skip_first_screenshot=True):
        """自动收集游戏室中生成的代币。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 是否成功收集了代币。

        Pages:
            in: page_game_room 主页或选游戏界面
            out: page_game_room 主页
        """
        coin_collected = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.ui_additional():
                continue
            if self.appear_then_click(COIN_POPUP, offset=(5, 5), interval=3):
                continue
            # 游戏室与选游戏界面顶部相同，优先返回游戏室
            if self.appear(GAME_ROOM_CHECK, offset=(5, 5)) \
                    and not self.appear(GOTO_CHOOSE_GAME, offset=(5, 5)):
                self.appear_then_click(BACK, offset=(5, 5), interval=3)
                continue
            # 收集代币
            if not coin_collected and self.appear(COIN, offset=(5, 5)):
                self.appear_then_click(COIN, offset=(5, 5), interval=3)
                coin_collected = True
                continue
            if self.appear(GOTO_CHOOSE_GAME, offset=(5, 5)):
                break
        return coin_collected

    def run(self):
        """运行小游戏日常自动化任务。

        导航至学院游戏室，识别并收集代币，循环运行配置的小游戏直至代币耗尽。

        Pages:
            in: 任意页面
            out: page_game_room
        """
        self.ui_ensure(page_academy)
        # page_academy -> page_game_room
        for _ in self.loop():
            if self.ui_page_appear(page_game_room):
                break
            if self.ui_page_appear(page_academy, interval=5):
                self.device.click(ACADEMY_GOTO_GAME_ROOM)
                continue
            # 每月游戏券达到上限时弹窗处理
            if self.handle_popup_confirm('MINIGAME_ENTER'):
                continue

        # 确保回到游戏室主界面
        self.go_to_main_page()
        coin_collected = False
        play_count = 0

        # 选择具体小游戏
        specific_game_name = "new_year_challenge"
        minigame_instance = None
        if specific_game_name == "new_year_challenge":
            from module.minigame.new_year_challenge import NewYearChallenge
            minigame_instance = NewYearChallenge(config=self.config, device=self.device)

        while 1:
            # 游玩次数上限控制
            if play_count >= 10:
                break
            # OCR 获取代币数量
            coin_count = self.get_coin_amount()
            logger.info(f"[小游戏] 硬币数量: {coin_count}")
            # 收集代币
            if coin_count <= 30 and not coin_collected:
                coin_collected = True
                if self.collect_coin():
                    continue
            # 无代币剩余
            if coin_count == 0:
                logger.info(f"[小游戏] 硬币数量: {coin_count}, 游玩结束")
                break
            logger.info("[小游戏] 硬币数量 > 0，消费")
            # 具体小游戏逻辑
            if minigame_instance is not None and minigame_instance.minigame_run():
                play_count += 1
                continue
            elif minigame_instance is None:
                logger.error(f"[小游戏] 未知的游戏名称 {specific_game_name}")
                break
            else:
                break

        self.config.task_delay(server_update=True)

"""舰队准备界面管理模块。

管理战役关卡进入前的舰队准备界面操作，包括：
- 舰队选择和切换（通过下拉菜单）
- 舰队推荐按钮
- 困难图整体推荐配队（Campaign.UseRecommendFleet）
- 舰队清空操作
- 困难模式限制条件检测
- 自动搜索设置（舰队角色分配）

FleetOperator 类封装了单个舰队槽位的操作逻辑，
支持舰队的激活、停用和状态检测。
下拉菜单的选项位置不写死，由 FleetBarDetector 在每轮截图上动态检测。

继承自 InfoHandler，可处理准备界面中的弹窗。
"""

import numpy as np
from scipy import signal

from module.base.timer import Timer
from module.base.utils import *
from module.exception import HardNotSatisfied
from module.handler.assets import AUTO_SEARCH_SET_MOB, AUTO_SEARCH_SET_BOSS, \
    AUTO_SEARCH_SET_ALL, AUTO_SEARCH_SET_STANDBY, \
    AUTO_SEARCH_SET_SUB_AUTO, AUTO_SEARCH_SET_SUB_STANDBY, \
    POPUP_CONFIRM
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.map.assets import *
from module.map.fleet_bar import FleetBarDetector
from module.ui_white.assets import POPUP_CONFIRM_WHITE


class FleetOperator:
    """单个舰队槽位的操作器。

    管理舰队准备界面中单个舰队槽位的选择、推荐和状态检测。
    下拉菜单的选项不依赖固定坐标，由 FleetBarDetector 逐轮从截图检测。

    Attributes:
        FLEET_IN_USE_STD (int): 使用中状态的标准差阈值（使用中: 52, 未使用: 3-6）。
        OFFSET (tuple[int, int, int, int]): 检测舰队相关按钮时相对清空按钮的偏移搜索范围。
        options (dict): 当前检测到的下拉菜单选项，键为舰队编号，值为 FleetOption。
    """
    FLEET_IN_USE_STD = 27  # In use 52, not in use (3, 6).

    OFFSET = (-20, -80, 20, 5)

    def __init__(self, choose, advice, bar, clear, in_use, hard_satisfied, main):
        """初始化舰队槽位操作器。

        Args:
            choose (Button): 激活或折叠下拉选择菜单的按钮。
            advice (Button): 推荐配队按钮。
            bar (Button): 舰队下拉选择菜单区域。
            clear (Button): 清空当前舰队的按钮。
            in_use (Button): 检测当前舰队是否在使用的区域按钮。
            hard_satisfied (Button): 检测当前舰队是否满足困难属性限制的区域按钮。
            main (InfoHandler): 所属的 Alas 模块实例。
        """
        self._choose = choose
        self._advice = advice
        self._bar = bar
        self._clear = clear
        self._in_use = in_use
        self._hard_satisfied = hard_satisfied
        self.main = main
        self.options = {}

        if main.appear(clear, offset=FleetOperator.OFFSET):
            choose.load_offset(clear)
            bar.load_offset(clear)
            in_use.load_offset(clear)
            hard_satisfied.load_offset(clear)

    def __str__(self):
        return str(self._choose)[:-7]

    def allow(self):
        """判断当前舰队槽位是否允许选择与编辑。

        Returns:
            bool: 是否允许选择当前舰队。
        """
        return self.main.appear(self._clear, offset=FleetOperator.OFFSET)

    def is_hard(self):
        """判断当前关卡是否为困难模式（是否存在推荐按钮）。

        Returns:
            bool: 是否为困难模式关卡。
        """
        return self.main.appear(self._advice, offset=FleetOperator.OFFSET)

    def is_hard_satisfied(self):
        """检测当前舰队是否满足困难模式的属性限制条件。

        通过检测黄色高亮线判断。若有高亮线说明存在限制且已满足。

        Returns:
            bool | None: 若满足限制返回 True，不满足返回 False；若非困难关卡返回 None。
        """
        if not self.is_hard():
            return None

        area = self._hard_satisfied.button
        image = color_similarity_2d(self.main.image_crop(area, copy=False), color=(249, 199, 0))
        height = cv2.reduce(image, 1, cv2.REDUCE_AVG).flatten()
        parameters = {'height': 180, 'distance': 5}
        peaks, _ = signal.find_peaks(height, **parameters)
        lines = len(peaks)
        # logger.attr('Light_orange_line', lines)
        return lines > 0

    def raise_hard_not_satisfied(self):
        """若不满足困难限制条件，抛出 HardNotSatisfied 异常。

        Raises:
            HardNotSatisfied: 当前舰队未满足困难关卡属性限制时抛出。
        """
        if self.is_hard_satisfied() is False:
            stage = self.main.config.Campaign_Name
            logger.critical(f'[Map] 关卡 "{stage}" 是困难模式，'
                            f'请在运行 AzurPilot 之前在游戏中准备好您的舰队 "{str(self)}"，'
                            f'或在战斗设置中开启「自动配队」')
            raise HardNotSatisfied

    def clear(self, skip_first_screenshot=True):
        """清空当前槽位选中的舰队。

        Args:
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。
        """
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            # 清除困难舰队时的弹窗
            if self.main.handle_popup_confirm(str(self._clear)):
                continue

            # 检查清空按钮以避免在弹窗显示动画时过早停止
            if self.allow():
                # 结束判定
                if not self.in_use():
                    break

                # 点击清空
                if click_timer.reached():
                    main.device.click(self._clear)
                    click_timer.reset()

    def recommend(self, skip_first_screenshot=True):
        """点击推荐配队按钮。

        Args:
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。
        """
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            # 结束判定
            if self.in_use():
                break

            # 点击选择
            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def update_options(self):
        """重新检测下拉菜单的舰队选项。

        每次都用当前截图新建检测器，确保选项不是上一次检测的缓存。
        """
        det = FleetBarDetector(self.main, bar=self._bar, choose=self._choose)
        self.options = det.options

    def open(self, skip_first_screenshot=True):
        """展开舰队选择下拉菜单。

        Args:
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。
        """
        main = self.main
        click_timer = Timer(3, count=6)
        # TODO: 为 FleetBarDetector 补充测试
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()
                self.update_options()

            # 结束判定
            if self.options:
                break

            # 点击展开
            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def close(self, skip_first_screenshot=True):
        """收起舰队选择下拉菜单。

        Args:
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。
        """
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()
                self.update_options()

            # 结束判定
            if not self.options:
                break

            # 点击折叠
            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def click(self, index, skip_first_screenshot=True):
        """在下拉菜单中点击选择指定舰队，并等待菜单收起。

        Args:
            index (int): 目标舰队编号，范围 1 到 6。
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。
        """
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()
                self.update_options()

            if not self.options:
                # 结束判定
                if self.in_use():
                    break
                else:
                    self.open()

            button = self.options.get(index)
            if button is None:
                if click_timer.reached():
                    logger.error(f'[地图-编队] 找不到舰队选项 {index}，无法切换')
                    self.close()
                    break
                else:
                    # 刚刚点过：点击动画可能盖住选项，菜单还没那么快收起
                    continue
            if button.selected:
                logger.info(f'[地图-编队] 舰队选项 {index} 已被选中')
                self.close()
                break

            # 点击对应项
            if click_timer.reached():
                main.device.click(button)
                click_timer.reset()

    def in_use(self):
        """检测当前槽位是否已配置并使用了舰队。

        Returns:
            bool: 是否已选择任意舰队。
        """
        # 处理自动搜索信息栏
        # 裁剪 FLEET_*_IN_USE 区域避免检测到信息栏，同时节省处理信息栏的时间
        image = self.main.image_crop(self._in_use.button, copy=False)

        # 针对英仙座皮肤纯色背景的特殊修正
        color = cv2.mean(image)[:3]
        # 英仙座皮肤
        if color_similar(color, (224, 154, 114), threshold=30):
            return True

        # 新条茜皮肤（秘密客室）：舰队卡片底部带有蓝色背景的特殊修正
        if color_similar(color, (124, 141, 171), threshold=30):
            return True

        gray = rgb2gray(image)
        return np.std(gray.flatten(), ddof=1) > self.FLEET_IN_USE_STD

    def ensure_to_be(self, index):
        """确保当前槽位切换为指定的舰队。

        Args:
            index (int): 目标舰队编号，范围 1 到 6。
        """
        logger.info(f'[地图-编队] {self} 设置为 {index}')
        self.open()
        self.click(index)


class FleetPreparation(InfoHandler):
    map_fleet_checked = False
    map_is_hard_mode = False

    def _handle_recommend_confirm(self, name=''):
        """确认推荐配队后的补齐弹窗。

        舰队槽位已有舰船时，点击推荐会弹出「是否采用推荐配置补齐空余位置」，
        确定后才会填充剩余位置；舰队为空时点击推荐直接生效，没有弹窗。

        Args:
            name (str, optional): 弹窗标记，用于区分点击记录中的确认按钮。默认为 ''。

        Returns:
            bool: 是否确认了弹窗。
        """
        timeout = Timer(1, count=3).start()
        while 1:
            self.device.screenshot()
            # interval=0：两支舰队的补齐弹窗间隔可能小于默认 2s 的点击间隔限制，
            # 共用同一个按钮名的计时器会吞掉后续弹窗
            if self.handle_popup_confirm(name, interval=0):
                # 等待弹窗消失，填充动画期间弹窗仍在前台，会遮挡下一个推荐按钮
                disappear = Timer(2, count=6).start()
                while 1:
                    self.device.screenshot()
                    if not self.appear(POPUP_CONFIRM, offset=self._popup_offset) \
                            and not self.appear(POPUP_CONFIRM_WHITE, offset=self._popup_offset):
                        break
                    if disappear.reached():
                        break
                return True
            if timeout.reached():
                return False

    def fleet_preparation(self, skip_first_screenshot=True):
        """更换与确认出击舰队。

        包含普通与困难模式的配队检查、推荐配队、困难限制检测与潜艇设置。

        Args:
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。

        Returns:
            bool: 是否进行了舰队设置或更换。
        """
        logger.info(f'[地图-编队] 使用舰队: {[self.config.Fleet_Fleet1, self.config.Fleet_Fleet2, self.config.Submarine_Fleet]}')
        if self.map_fleet_checked:
            return False

        # 校准自动搜索设置按钮（AUTO_SEARCH_SET_*）的坐标：以清空按钮为锚点。
        # enter_map() 在 fleet_preparation() 之后紧接着就会调用 handle_auto_search_setting()，
        # 这里只做识别与内存偏移、不点击界面，因此跳过编队检测时也必须执行，
        # 否则 W15/16 章等新布局下会扫不到高亮项（误报「未找到活跃的自动搜索设置」）
        if self.appear(FLEET_1_CLEAR, offset=FleetOperator.OFFSET):
            AUTO_SEARCH_SET_MOB.load_offset(FLEET_1_CLEAR)
            AUTO_SEARCH_SET_BOSS.load_offset(FLEET_1_CLEAR)
            AUTO_SEARCH_SET_ALL.load_offset(FLEET_1_CLEAR)
            AUTO_SEARCH_SET_STANDBY.load_offset(FLEET_1_CLEAR)
        if self.appear(SUBMARINE_CLEAR, offset=FleetOperator.OFFSET):
            AUTO_SEARCH_SET_SUB_AUTO.load_offset(SUBMARINE_CLEAR)
            AUTO_SEARCH_SET_SUB_STANDBY.load_offset(SUBMARINE_CLEAR)

        # 跳过编队检测：信任游戏内当前预选的舰队，不操作下拉菜单
        # 适用于舰队槽位未完全解锁的账号，避免下拉菜单检测卡死
        if self.config.Fleet_SkipPreparation:
            logger.info('[地图-编队] 跳过舰队准备 (Fleet_SkipPreparation=True), '
                        '使用游戏中当前预选的舰队')
            return True

        fleet_1 = FleetOperator(
            choose=FLEET_1_CHOOSE, advice=FLEET_1_ADVICE, bar=FLEET_1_BAR, clear=FLEET_1_CLEAR,
            in_use=FLEET_1_IN_USE, hard_satisfied=FLEET_1_HARD_SATIESFIED, main=self)
        y = FLEET_1_CLEAR.button[1] - FLEET_1_CLEAR.area[1]
        if y < -10:
            logger.info('[地图-编队] FLEET_1_CLEAR上移，加载W15资源')
            in_use = FLEET_2_IN_USE_W15
        else:
            in_use = FLEET_2_IN_USE
        fleet_2 = FleetOperator(
            choose=FLEET_2_CHOOSE, advice=FLEET_2_ADVICE, bar=FLEET_2_BAR, clear=FLEET_2_CLEAR,
            in_use=in_use, hard_satisfied=FLEET_2_HARD_SATIESFIED, main=self)
        submarine = FleetOperator(
            choose=SUBMARINE_CHOOSE, advice=SUBMARINE_ADVICE, bar=SUBMARINE_BAR, clear=SUBMARINE_CLEAR,
            in_use=SUBMARINE_IN_USE, hard_satisfied=SUBMARINE_HARD_SATIESFIED, main=self)

        # 检查是否为困难模式
        h1, h2, h3 = fleet_1.is_hard_satisfied(), fleet_2.is_hard_satisfied(), submarine.is_hard_satisfied()
        self.map_is_hard_mode = h1 is not None or h2 is not None or h3 is not None

        # 潜艇槽位可用性检测
        # 缓存 submarine.allow() 以免展开 fleet_2 遮挡潜艇按钮后检测不一致
        map_allow_submarine = submarine.allow()
        logger.attr('允许潜艇', map_allow_submarine)

        # 困难图自动配队：直接采用游戏内置的推荐阵容，用户不必事先在游戏里配好舰队
        if self.map_is_hard_mode and self.config.Campaign_UseRecommendFleet:
            logger.info('[地图-编队] 困难图使用推荐配队')
            self.device.screenshot()

            if fleet_1.allow():
                logger.info('[地图-编队] 舰队1使用推荐配队')
                if self.appear_then_click(RECOMMEND_A, interval=2):
                    self._handle_recommend_confirm('RecommendFleet1')
            if fleet_2.allow():
                logger.info('[地图-编队] 舰队2使用推荐配队')
                if self.appear_then_click(RECOMMEND_B, interval=2):
                    self._handle_recommend_confirm('RecommendFleet2')
            if map_allow_submarine:
                if self.config.Submarine_Fleet:
                    logger.info('[地图-编队] 潜艇使用推荐配队')
                    if self.appear_then_click(RECOMMEND_C, interval=2):
                        self._handle_recommend_confirm('RecommendSubmarine')
                else:
                    submarine.clear()
            else:
                self.config.SUBMARINE = 0

            # 复查困难满足状态，等待填充动画结束：连续两次读数一致即认为完成
            check_timer = Timer(2, count=6).start()
            prev = None
            while 1:
                self.device.screenshot()
                curr = (
                    fleet_1.is_hard_satisfied(),
                    fleet_2.is_hard_satisfied(),
                    submarine.is_hard_satisfied(),
                )
                if curr == prev:
                    break
                prev = curr
                if check_timer.reached():
                    break
            h1, h2, h3 = prev

        logger.info(f'[地图-编队] 困难满足: 舰队1: {h1}, 舰队2: {h2}, 潜艇: {h3}')
        if self.config.SERVER in ['cn', 'en', 'jp']:
            # 困难关卡一次只有一支舰队实际出击，另一支在基地待命、不参与战斗，
            # 所以待命舰队不应被强制要求满足困难限制（否则会误报"必须准备两只舰队"）。
            # 出击舰队由 Fleet_FleetOrder 决定，与 Hard.HardFleet 一一对应：
            #   fleet1_all_fleet2_standby -> 舰队1出击、舰队2待命
            #   fleet1_standby_fleet2_all -> 舰队2出击、舰队1待命
            #   其余取值（mob/boss 分工）两队都出击，两队都需要满足限制
            sortie_fleet = 0  # 0: 两队均出击，1: 仅舰队1出击，2: 仅舰队2出击
            if self.map_is_hard_mode:
                if self.config.Fleet_FleetOrder == 'fleet1_all_fleet2_standby':
                    sortie_fleet = 1
                elif self.config.Fleet_FleetOrder == 'fleet1_standby_fleet2_all':
                    sortie_fleet = 2
                if sortie_fleet:
                    logger.info(f'[地图-编队] 困难模式仅舰队{sortie_fleet}出击，'
                                f'待命舰队不做困难限制校验')
            if self.config.Fleet_Fleet1 and sortie_fleet in (0, 1):
                fleet_1.raise_hard_not_satisfied()
            if self.config.Fleet_Fleet2 and sortie_fleet in (0, 2):
                fleet_2.raise_hard_not_satisfied()
            if self.config.Submarine_Fleet:
                submarine.raise_hard_not_satisfied()

        # 困难模式跳过普通编队设置
        if self.map_is_hard_mode:
            logger.info('[地图-编队] 困难战役，无需舰队准备')
            # 若用户未配置潜艇舰队则清空潜艇槽位
            if submarine.allow():
                if self.config.Submarine_Fleet:
                    pass
                else:
                    submarine.clear()
            else:
                self.config.SUBMARINE = 0
            return False

        if map_allow_submarine:
            if self.config.Submarine_Fleet:
                if fleet_2.allow():
                    self.device.click(fleet_2._clear)
                    # 无需重新截图，潜艇检测不需要舰队2部分
                submarine.ensure_to_be(self.config.Submarine_Fleet)
            else:
                # 简单点击同时清空潜艇与舰队2以加快速度
                op = False
                if fleet_2.allow():
                    self.device.click(fleet_2._clear)
                    op = True
                if submarine.allow():
                    self.device.click(submarine._clear)
                    op = True
                if op:
                    self.device.screenshot()

        if self.config.Fleet_Fleet2:
            # 同时使用两支舰队，强制重新设置
            fleet_2.clear()
            fleet_1.ensure_to_be(self.config.Fleet_Fleet1)
            fleet_2.ensure_to_be(self.config.Fleet_Fleet2)
        else:
            # 不使用第二舰队
            if fleet_2.allow():
                fleet_2.clear()
            fleet_1.ensure_to_be(self.config.Fleet_Fleet1)

        # 再次检查潜艇槽位是否为空
        if map_allow_submarine:
            if self.config.Submarine_Fleet:
                pass
            else:
                submarine.clear()
        else:
            self.config.SUBMARINE = 0

        return True

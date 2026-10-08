"""科研掉落解析。

从科研领奖时落盘的掉落记录中解析出「哪个科研项目产出了什么」，是科研统计的
数据入口，也是 WebUI 科研统计页的数据来源。

记录结构：一条掉落记录是一张 PNG，内含多帧（由 AzurStats.pack 垂直拼接）：
    - 第 0 帧：科研队列页，卡片上印着项目代号（如 D-737-MI）与系列角标（罗马数字）；
    - 第 1..n 帧：「获得道具」弹窗，是这次实际到手的东西。

**期数只看卡片上的罗马数字角标，不看项目代号**：同一个代号（G-531-MI、Q-051-MI…）
在每一期都存在，代号里没有期数信息。而掉落物也不能反推期数——只有彩装备与舰船图纸
是绑定期数的，金装备各期混着出（队列里还常常混着别期的「定向研发」项目）。
角标用 module/research/series.py 既有的 match_series 读，实测 896 张全对。

入口：
    record_research_drop() 由 AzurStats.commit() 在领奖时调用。
    模板库里缺某件物品时该物品会被跳过而不是记成乱码，
    补模板见 alas-research-stats 技能文档。
"""

import re
import typing as t
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from module.base.utils import extract_white_letters
from module.logger import logger
from module.statistics.item import AmountOcr, remove_small_fragments, resolve_amount_max

# 队列页卡片上的项目代号区域（1280x720 实测坐标）。
# 卡 3~5 因处于「等待进行」状态被半透明遮罩压暗而读不出来，但不影响结论：
# ALAS 是在点开第一个已完成项目领奖之前截的图，队列 FIFO，第 1 张卡即是刚完成的项目。
QUEUE_CARD_AREAS = (
    (55, 296, 232, 338),
    (288, 296, 468, 338),
    (545, 296, 715, 338),
    (782, 296, 955, 338),
    (1025, 296, 1190, 338),
)
# 卡 1 左上角的系列角标（罗马数字）区域。队列页的卡片是平的，没有透视缩放，
# 所以 scaling 固定 1.0（科研主页那 5 张卡是弧形排列，那套要按位置补缩放）。
# 区域比角标本身（35x26）留出余量：太贴边模板匹配会失败（实测裁到 40x36 就全读不出）。
SERIES_BADGE_AREA = (55, 118, 105, 160)
# 项目代号字表，与 module/research/project.py 的 OCR_RESEARCH 保持一致
RESEARCH_ALPHABET = '0123456789BCDEGHQTMIULRF-'
# 合法代号形如 D-737-MI
CODE_PATTERN = re.compile(r'^[A-Z0-9]-[0-9]{3}-[A-Z]{2}$')

ITEM_TEMPLATE_FOLDER = './assets/stats/research_items'

# 科研掉落的数量上限，只用于触发重识别（超限即认为读错）。
# 心智单元能到 100+，不能沿用大世界那边的 50 上限。
RESEARCH_AMOUNT_MAX = {'CognitiveChips': 300}
# 科研掉落的图纸（舰船图纸与全部装备图纸）一次都不超过 10 张。
# 超限触发重新识别；仍无法确认时跳过本格，不靠丢掉首位或末位猜数量。
RESEARCH_SURE_MAX = 10
RESEARCH_SURE_PREFIXES = ('Blueprint',)
# 装备图纸的模板名以 _T<数字> 结尾，可能还带 _2/_3 变体后缀
RESEARCH_SURE_PATTERN = re.compile(r'_T\d+(_\d+)?$')


def research_amount_default_max(item_name: str) -> int:
    """科研掉落的默认数量上限。

    科研掉落的图纸只有舰船图纸（Blueprint*）与装备图纸（*_T<数字>）两类，
    一次都不超过 10 张；其余物品（心智单元、物资等）没有这个规律。

    Args:
        item_name (str): 物品模板名。

    Returns:
        int: 该物品的数量上限。
    """
    from module.statistics.item import DEFAULT_AMOUNT_MAX

    if item_name.startswith(RESEARCH_SURE_PREFIXES) or RESEARCH_SURE_PATTERN.search(item_name):
        return RESEARCH_SURE_MAX
    return DEFAULT_AMOUNT_MAX


def right_digit_column_left(image, min_height=8, max_valley=2, dark=120):
    """按「每列墨迹高度」从右往左定位最右侧的数字簇，返回其左边界列号。

    科研的数量框紧挨物品图标，图标底部的白色纹理（纸角、斜边、横条）会被
    ``extract_white_letters`` 提取成笔画，拼进数字里：实测「图纸 1 张」被读成 71
    （超过上限后又被截断末位兜底成 7，六倍误差）、「装备设计图 1 张」被读成 9。

    数量数字是右对齐的，残影总在数字左侧；数字笔画的列高 12~17px，残影的列高
    通常不超过 6px，即便残影较高（如斜角）也会与数字之间隔着一道矮列组成的
    「谷」。因此从最右侧的笔画列往左扫，遇到超过 ``max_valley`` 个连续矮列即停。

    比按连通域形状筛选更稳：图标残影与数字粘连时连通域会合并变宽，按形状筛选
    会把整段（含真数字）丢掉；列剖面只看高度，真数字不会被误伤——实测物资的
    「72」在连通域法下被拆坏读成 1，列剖面读数不变。

    Args:
        image (np.ndarray): ``extract_white_letters`` 的输出（深色字 + 白底）。
        min_height (int): 视为「笔画列」的最小墨迹高度（px）。
        max_valley (int): 数字之间允许的连续矮列数。
        dark (int): 判定为字的灰度上限。

    Returns:
        int: 数字簇的左边界列号（含）；找不到笔画列时返回 None。
    """
    heights = (image < dark).sum(axis=0)
    index = len(heights) - 1
    while index >= 0 and heights[index] < min_height:
        index -= 1
    if index < 0:
        return None

    left = index
    valley = 0
    for column in range(index - 1, -1, -1):
        if heights[column] >= min_height:
            left = column
            valley = 0
        else:
            valley += 1
            if valley > max_valley:
                break
    return left


class ResearchAmountOcr(AmountOcr):
    """科研掉落的数量读数器。

    优先匹配原始小字的逐位模板；不确定时使用配置中的 OCR 后端。
    OCR 兜底只对图纸启用列剖面，读空时提高阈值重读；仍超限则跳过本格。
    科研网格专用，不改变全局 AMOUNT_OCR 的行为。

    Attributes:
        digit_min_height (int): 数字笔画的最小列高。
        digit_max_valley (int): 数字之间允许的连续矮列数（谷宽）。
        retry_threshold (int): 首轮读数为 0 时的重读阈值。
    """

    threshold = 96
    use_digit_templates = True
    strict_amount_max = True
    digit_min_height = 8
    digit_max_valley = 2
    # 首轮读数为 0 时的兜底阈值：数字被灰色残影加粗成「I」时，中等阈值下
    # 整块都被当成字，只有近白像素能还原出「1」（实测 9 格 96 读空、180 全读出 1）。
    retry_threshold = 180
    # 本次识别是否启用列剖面，由 ocr_with_validation 按数量上限设置
    apply_column = False

    def ocr_with_validation(self, image, item_name=None, direct_ocr=False, trim=True,
                            amount_max=None, amount_default_max=None):
        """逐位字形匹配之后，按图纸上限选择 OCR 兜底预处理。

        一、只有「图纸」这类**个位数掉落**（数量上限 ≤10）才启用列剖面：
        它们的真值最多两位数，读数里的多位数必然含残影；物资、心智单元能有
        三位数，切列会误伤真数字——实测物资 97 被切成 7、心智 44 被切成 4。
        二、首轮读数为 0 时提高阈值重读一次。

        Args:
            image: 单张图像或图像列表。
            item_name: 物品名称，用于查找最大值。
            direct_ocr: 为 True 时跳过裁剪。
            trim: 是否调用 crop_to_text 裁剪空白边框。
            amount_max (dict): 按场景覆盖的数量上限表。
            amount_default_max (int): 未命中时的默认上限。

        Returns:
            int: 验证后的数量。
        """
        max_val = resolve_amount_max(item_name, amount_max, amount_default_max)
        self.apply_column = max_val <= RESEARCH_SURE_MAX
        amount = super().ocr_with_validation(
            image, item_name=item_name, direct_ocr=direct_ocr, trim=trim,
            amount_max=amount_max, amount_default_max=amount_default_max)
        if amount == 0:
            threshold, self.threshold = self.threshold, self.retry_threshold
            try:
                amount = super().ocr_with_validation(
                    image, item_name=item_name, direct_ocr=direct_ocr, trim=trim,
                    amount_max=amount_max, amount_default_max=amount_default_max)
            finally:
                self.threshold = threshold
        return amount

    def pre_process(self, image):
        """预处理科研数量图像，提取白字、滤除碎片噪点并定位数字列。

        Args:
            image (np.ndarray): 原始输入切片图像。

        Returns:
            np.ndarray: 处理后的二值化图像。
        """
        image = extract_white_letters(image, threshold=self.threshold)
        image = remove_small_fragments(
            image,
            min_height=self.fragment_min_height,
            min_area=self.fragment_min_area,
            max_digit_gap=self.fragment_max_digit_gap,
        )
        if not self.apply_column:
            return image.astype(np.uint8)
        left = right_digit_column_left(image, self.digit_min_height, self.digit_max_valley)
        if left is None or left == 0:
            return image.astype(np.uint8)
        image = image.copy()
        image[:, :left] = 255
        return image.astype(np.uint8)


def levenshtein(a: str, b: str, limit: int = 3) -> int:
    """计算两串的编辑距离，超过 limit 时提前返回。

    Args:
        a (str): 字符串一。
        b (str): 字符串二。
        limit (int): 距离上限，超过即不再精确计算。

    Returns:
        int: 编辑距离；大于 limit 时返回 limit 以上的任意值。
    """
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (char_a != char_b),
            ))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


@dataclass
class ResearchDrop:
    """一次科研领奖的解析结果。

    Attributes:
        project (str): 项目代号，如 'D-737-MI'；未能识别时为空串。
        series (int): 科研期数，1~9；未能识别时为 0。
        items (dict): {物品模板名: 数量}，如 {'BlueprintValparaiso': 1}。
    """

    project: str = ''
    series: int = 0
    items: t.Dict[str, int] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        """检查科研掉落解析结果是否有效（至少包含一个有效物品）。"""
        return bool(self.items)


class ResearchDropParser:
    """科研掉落记录解析器。

    加载一次模板库后复用，避免每次领奖都重新读 300 多个模板文件。

    Attributes:
        stats (GetItemsStatistics): 物品识别器，绑定到科研自己的物品网格。
        ocr (Ocr): 队列页项目代号识别器。
        lookup (dict): 项目代号 -> LIST_RESEARCH_PROJECT 条目。
    """

    def __init__(self):
        from module.base.button import Button
        from module.ocr.ocr import Ocr
        from module.research.project_data import LIST_RESEARCH_PROJECT
        from module.statistics.get_items import GetItemsStatistics
        from module.statistics.item import ItemGrid

        Ocr.SHOW_LOG = False
        # 独立网格：科研有一套自己的物品模板，不能和战斗掉落共用全局网格，
        # 否则两边加载的模板会混在一起，且数量上限也按各自场景算。
        grid = ItemGrid(None, {}, template_area=(40, 21, 89, 70), amount_area=(60, 71, 91, 92))
        grid.load_template_folder(ITEM_TEMPLATE_FOLDER)
        grid.amount_max = dict(RESEARCH_AMOUNT_MAX)
        grid.amount_default_max = research_amount_default_max
        # 独立读数器优先匹配数量字形，OCR 兜底过滤纸角；超限不截断猜数。
        grid.amount_ocr = ResearchAmountOcr([], threshold=96, name='RESEARCH_AMOUNT_OCR')

        self.stats = GetItemsStatistics()
        self.stats.grid = grid
        # 向右留出字形边缘，向左容纳完整心智/物资数；图标残影由逐位匹配排除。
        self.stats.amount_area = (50, 72, 94, 94)
        self.ocr = Ocr(
            [Button(area=area, color=(255, 255, 255), button=area) for area in QUEUE_CARD_AREAS],
            threshold=64, alphabet=RESEARCH_ALPHABET, name='RESEARCH_QUEUE',
        )
        self.lookup = {project['name']: project for project in LIST_RESEARCH_PROJECT}

    def _correct_code(self, code: str) -> str:
        """把 OCR 出的项目代号纠正到合法代号。

        实测常见的单字母误读：I 被读成 T 或 L、D 被读成 O 或 1。
        只在编辑距离 1 以内接受纠正，避免把噪声串凑成某个项目。

        Args:
            code (str): OCR 原始结果。

        Returns:
            str: 纠正后的合法代号；无法确定时为空串。
        """
        if not CODE_PATTERN.match(code):
            return ''
        for name in self.lookup:
            if levenshtein(code, name, limit=1) <= 1:
                return name
        return ''

    def _read_project(self, image: np.ndarray) -> str:
        """从队列页读取本组掉落对应的科研项目代号。

        代号只用来记录「哪一次项目」，**不带期数信息**（同一个代号每期都有），
        期数一律走 `_read_series()`。

        Args:
            image (np.ndarray): 队列页截图。

        Returns:
            str: 项目代号；识别失败返回空串。
        """
        names = self.ocr.ocr(image)
        if not isinstance(names, list):
            names = [names]
        for raw in names:
            code = (raw or '').strip().upper()
            if not code:
                continue
            if code in self.lookup:
                return code
            fixed = self._correct_code(code)
            if fixed:
                logger.info(f'[科研统计] 项目代号 {code} 纠正为 {fixed}')
                return fixed
        logger.warning(f'[科研统计] 未能识别项目代号: {names}')
        return ''

    def _read_series(self, image: np.ndarray) -> int:
        """从队列页卡片 1 的角标读取科研期数。

        复用 module/research/series.py 的模板匹配（那里已经有 I~IX 的模板，
        本来是为科研主页的项目卡片写的）。

        Args:
            image (np.ndarray): 队列页截图。

        Returns:
            int: 期数 1~9；读不出来返回 0。
        """
        from module.base.utils import crop
        from module.research.series import match_series

        series = match_series(crop(image, SERIES_BADGE_AREA), scaling=1.0)
        if not series:
            logger.warning('[科研统计] 未能读出卡片角标的期数，本次记录不计入任何一期')
        return series

    def parse(self, images: t.Sequence[np.ndarray]) -> ResearchDrop:
        """解析一组科研掉落截图。

        Args:
            images (list): 掉落记录的各帧截图。

        Returns:
            ResearchDrop: 解析结果；完全无法识别时 items 为空。
        """
        from module.research.assets import QUEUE_CHECK
        from module.base.utils import load_image  # noqa: F401  保持与调用方一致的读图路径
        from module.statistics.utils import unpack

        drop = ResearchDrop()
        frames: t.List[np.ndarray] = []
        for image in images:
            try:
                frames.extend(unpack(image))
            except Exception as e:
                logger.warning(f'[科研统计] 跳过无法拆帧的截图: {e}')

        if not frames:
            return drop

        queue_page = None
        for frame in frames:
            if QUEUE_CHECK.match(frame, offset=(10, 10)):
                queue_page = frame
                break
        if queue_page is not None:
            drop.project = self._read_project(queue_page)
            drop.series = self._read_series(queue_page)
        else:
            logger.info('[科研统计] 本组截图没有队列页，只统计掉落物')

        seen = set()
        for frame in frames:
            if frame is queue_page:
                continue
            key = id(frame)
            if key in seen:
                continue
            seen.add(key)
            try:
                items = self.stats.stats_get_items(frame)
            except Exception:
                # 不是「获得道具」界面
                continue
            for item in items:
                if not item.is_known_item():
                    continue
                if item.amount <= 0:
                    logger.warning(f'[科研统计] {item.name} 数量无法确认，跳过本格')
                    continue
                drop.items[item.name] = drop.items.get(item.name, 0) + item.amount

        return drop


_parser: t.Optional[ResearchDropParser] = None


def get_parser() -> ResearchDropParser:
    """取全局解析器实例（模板只加载一次）。

    Returns:
        ResearchDropParser: 解析器单例。
    """
    global _parser
    if _parser is None:
        _parser = ResearchDropParser()
    return _parser


def record_research_drop(images: t.Sequence[np.ndarray], instance: str, imgid: str = '') -> t.Optional[dict]:
    """解析一组科研掉落截图并写入本地库。

    Args:
        images (list): 掉落记录的各帧截图。
        instance (str): ALAS 实例名，统计按实例隔离。
        imgid (str): 掉落记录的文件名（时间戳），用于防止同一条记录重复入库。

    Returns:
        dict: 写入的条目；无有效掉落或重复时返回 None。
    """
    try:
        drop = get_parser().parse(images)
    except Exception as e:
        logger.warning(f'[科研统计] 解析失败，跳过本次记录: {e}')
        return None

    if not drop.valid:
        logger.info('[科研统计] 本次没有识别到已知物品，未入库')
        return None

    from module.statistics.cl1_database import db as cl1_db
    entry = cl1_db.add_research_drop(
        instance, drop.project, drop.series, drop.items, imgid=imgid)
    if entry is not None:
        detail = ', '.join(f'{name}x{amount}' for name, amount in drop.items.items())
        logger.info(f'[科研统计] {drop.project or "未知项目"} 记录入库: {detail}')
    return entry

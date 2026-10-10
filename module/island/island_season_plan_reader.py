"""赛季「开发计划」页面读取（Add by MHY）。

ALAS 原本只有「每日计划/每周计划」两个页签的互动逻辑，赛季任务（提交小麦/
牧草/餐品等）完全没有读取能力。仓库判定只能靠「库存掉幅」反推是否已提交，
容易出现误判；直接读页面才是真相来源。

页面结构（真机实测，1280x720）：
    岛屿主页 → 右上角「开发季」图标 (954, 42) → 底部第 3 页签「开发计划」(533, 694)
    任务卡片 3 列 x 2 行/屏，可滚动：
        列 x 范围: 43-418 / 437-812 / 831-1205
        行 y 范围: 177-388 / 406-602
    每张卡片：任务名 / 描述 / 「提交X*N」/ 进度（右对齐，如 70/100）/ 3 个奖励图标

OCR 选型（离线实测）：
    任务名  ppocr_v6 —— 全部 6 张卡片识别正确
            cnocr    —— 会多带尾字（烤肉能量家、营养组合一）
    进度    azur_lane（游戏数字字体）识别 70/100、0/100、5/100 稳定
"""
import difflib

from module.island.island_season_plan_data import plan_tasks

# 卡片列 x 范围（3 列）
CARD_COLUMNS = ((43, 418), (437, 812), (831, 1205))
# 一屏可见的行 y 范围（2 行）
CARD_ROWS = ((177, 388), (406, 602))

# 卡片内文字区（相对卡片左上角 / 右上角）
NAME_BOX = (30, 18, 220, 50)
# 右边界原来取 -20，最后一位数字会被切掉（真机读到 500/50、250/25），放宽到 -8
PROGRESS_BOX = (-135, 18, -8, 46)
# 「已领取」徽章区（相对卡片右下角）：提交过的任务会沉到列表末尾并标记
CLAIM_BOX = (-150, 150, -5, 210)
# 兜底区域：徽章位置会随卡片状态（可提交 / 已领取）变化。真机上只认窄框时，
# 16 项里只认出 1 项已领取，而用户看到的那些其实都已经提交过了。
CLAIM_BOX_WIDE = (-210, 118, -5, 215)
# 提交过的卡片可能显示不同文案，命中任一即算已领取；
# 注意不能用「提交」单独匹配——可提交的卡片也有「提交 玉米*500」字样
CLAIM_TEXTS = ('已领取', '已提交')
# 徽章竖向兜底搜索：单步 / 最大范围（Add by MHY）
# 真机实测同一页各屏的行偏移会跳到 0/40/80/-20/-30，而徽章框只能容忍 ±25~44px，
# 于是名字和进度都读对了、徽章却整体错开。落空时按下面参数上下再找一遍。
CLAIM_SEARCH_STEP = 10
CLAIM_SEARCH_SPAN = 60
# 任务列表可视区下沿（1280x720 真机实测约 618，再往下被底部页签盖住并淡出）。
# Add by MHY：卡片滚到这里时奖励区连同「已领取」徽章一起被裁掉，读不到徽章
# 并不代表未领取——这种情况判成 None（未知），交给后面滚到完整位置的那一屏补。
LIST_BOTTOM = 615

NAME_LANG = 'ppocr_v6'
PROGRESS_LANG = 'azur_lane'
MATCH_RATIO = 0.5  # 任务名模糊匹配阈值


def parse_progress(text):
    """
    解析进度文本。

    Args:
        text: OCR 文本，如 '70/100'、'6 / 250'、'70|100'

    Returns:
        tuple: (当前数量, 需要数量)；无法解析返回 None
    """
    if not text:
        return None
    cleaned = str(text).replace('|', '/').replace(' ', '').replace('．', '.')
    if '/' not in cleaned:
        return None
    left, _, right = cleaned.partition('/')
    left = ''.join(ch for ch in left if ch.isdigit())
    right = ''.join(ch for ch in right if ch.isdigit())
    if not left or not right:
        return None
    return int(left), int(right)


def normalize_name(text):
    """去掉 OCR 常见噪声（空白、标点、零宽字符）。"""
    if not text:
        return ''
    drop = ' \t\u3000·.-—－:：,，。'
    return ''.join(ch for ch in str(text) if ch not in drop)


def match_task(name, season):
    """
    把 OCR 出的任务名映射回赛季任务。

    Args:
        name: OCR 文本
        season: 赛季

    Returns:
        tuple: (任务名, 物品英文名, 需要数量)；匹配不到返回 (None, None, 0)
    """
    target = normalize_name(name)
    if not target:
        return None, None, 0
    tasks = plan_tasks(season)
    for task, item, need in tasks:
        if normalize_name(task) == target:
            return task, item, need
    for task, item, need in tasks:
        task_norm = normalize_name(task)
        if task_norm and (task_norm in target or target in task_norm):
            return task, item, need
    names = [normalize_name(task) for task, _, _ in tasks]
    best = difflib.get_close_matches(target, names, n=1, cutoff=MATCH_RATIO)
    if best:
        for task, item, need in tasks:
            if normalize_name(task) == best[0]:
                return task, item, need
    return None, None, 0


def card_top(row):
    """
    卡片的上边缘 y 坐标（CARD_ROWS 是 (上边缘, 下边缘) 二元组）。

    这里曾经写成 CARD_ROWS[row][1]（下边缘），所有基于它的区域整体下移了
    一个卡片高度：徽章区域偏了 361px，「已领取」永远读不到；名字区也只在
    进度锚点恰好补偿回来时才对。统一走这个函数，别再直接索引。
    """
    return CARD_ROWS[row][0]


def claim_box(row, col):
    """卡片右下角的「提交/已领取」按钮区。"""
    x1, x2 = CARD_COLUMNS[col]
    y1, _ = CARD_ROWS[row]
    return (x2 + CLAIM_BOX[0], y1 + CLAIM_BOX[1], x2 + CLAIM_BOX[2], y1 + CLAIM_BOX[3])


def claim_boxes(row, col):
    """
    徽章的候选区域（先窄后宽）。

    Args:
        row: 行号 0-1
        col: 列号 0-2

    Returns:
        list[tuple]: 依次尝试的区域
    """
    x2 = CARD_COLUMNS[col][1]
    y1 = card_top(row)
    return [
        (x2 + CLAIM_BOX[0], y1 + CLAIM_BOX[1], x2 + CLAIM_BOX[2], y1 + CLAIM_BOX[3]),
        (x2 + CLAIM_BOX_WIDE[0], y1 + CLAIM_BOX_WIDE[1],
         x2 + CLAIM_BOX_WIDE[2], y1 + CLAIM_BOX_WIDE[3]),
    ]


def claim_visible(row, col, offset=0):
    """
    徽章区是否完整落在可视列表内。

    卡片被滚到屏幕下沿时奖励区会被底部页签裁掉，徽章跟着消失。
    """
    return claim_boxes(row, col)[0][3] + offset <= LIST_BOTTOM


def read_claim(ocr, image, row, col, offset=0):
    """
    读卡片是否已领取：任一候选区域命中任意已知文案即算已领取。

    Args:
        ocr: ocr(image, area, lang) -> str
        image: 截图
        row: 行号
        col: 列号
        offset: 本次读屏的行偏移

    Returns:
        bool: 是否已领取
        None: 徽章区被屏幕下沿裁掉，读不到不能当成「未领取」
    """
    if not claim_visible(row, col, offset):
        return None
    for box in claim_boxes(row, col):
        text = str(ocr(image, (box[0], box[1] + offset, box[2], box[3] + offset), NAME_LANG))
        if any(claim in text for claim in CLAIM_TEXTS):
            return True
    # Add by MHY, 竖向兜底：行偏移有残差时徽章会整体错开，上面的固定框就落空。
    # 只在上面全落空时才搜，代价只落在真正漏读的那几张卡上。
    wide = claim_boxes(row, col)[-1]
    for delta in range(CLAIM_SEARCH_STEP, CLAIM_SEARCH_SPAN + 1, CLAIM_SEARCH_STEP):
        for shift in (-delta, delta):
            y = offset + shift
            text = str(ocr(image, (wide[0], wide[1] + y, wide[2], wide[3] + y), NAME_LANG))
            if any(claim in text for claim in CLAIM_TEXTS):
                return True
    return False


# 两行卡片的行距（真机实测 229px）
ROW_SPAN = CARD_ROWS[1][0] - CARD_ROWS[0][0]


def detect_row_offsets(image, ocr, season=None, coarse=20):
    """
    用进度数字 N/M 做锚点，粗定位每一行卡片的垂直偏移。

    列表滚动后卡片不再对齐固定坐标（真机实测：滚动一格后固定坐标读到空白），
    所以要先定位行位置。锚点选进度数字而不是任务名：名字区附近有描述文字，
    模糊匹配会把「…的苹果汁能显著提升岛…」当成任务名（真机踩过）。

    这里只做粗定位（步长 20），精确到像素由 find_row_offset 按任务名补。

    Args:
        image: 截图
        ocr: ocr(image, area, lang) -> str
        season: 赛季
        coarse: 搜索步长

    Returns:
        dict: {行号: 偏移}，没找到的行不出现
    """
    _, x2 = CARD_COLUMNS[0]
    anchors = {row: card_top(row) + PROGRESS_BOX[1] for row in range(len(CARD_ROWS))}
    base = anchors[0]
    lo, hi = -260, 300

    def hit(offset):
        box = (x2 + PROGRESS_BOX[0], base + offset,
               x2 + PROGRESS_BOX[2], base + PROGRESS_BOX[3] - PROGRESS_BOX[1] + offset)
        return parse_progress(ocr(image, box, PROGRESS_LANG)) is not None

    hits = [o for o in range(lo, hi + 1, coarse) if hit(o)]
    if not hits:
        return {}
    clusters = [[hits[0]]]
    for offset in hits[1:]:
        if offset - clusters[-1][-1] <= coarse:
            clusters[-1].append(offset)
        else:
            clusters.append([offset])
    result = {}
    for cluster in clusters:
        center = int(sum(cluster) / len(cluster))
        absolute = base + center
        row = min(anchors, key=lambda r: abs(anchors[r] - absolute))
        offset = absolute - anchors[row]
        # 同一行命中多次时取离标准位置最近的那个
        if row not in result or abs(offset) < abs(result[row]):
            result[row] = offset
    return result


def card_boxes(row, col):
    """
    卡片内「任务名」「进度」两块文字的坐标。

    Args:
        row: 行号（0 起）
        col: 列号（0 起）

    Returns:
        tuple: ((名字 x1,y1,x2,y2), (进度 x1,y1,x2,y2))
    """
    x1, x2 = CARD_COLUMNS[col]
    y1, _ = CARD_ROWS[row]
    name = (x1 + NAME_BOX[0], y1 + NAME_BOX[1], x1 + NAME_BOX[2], y1 + NAME_BOX[3])
    progress = (x2 + PROGRESS_BOX[0], y1 + PROGRESS_BOX[1],
                x2 + PROGRESS_BOX[2], y1 + PROGRESS_BOX[3])
    return name, progress


def find_row_offset(image, ocr, season, row, base=0, span=50, step=10):
    """
    在 base 附近按「任务名精确匹配」定位某一行的垂直偏移。

    为什么必须按行独立定位：进度数字的位置和名字区并不一致（真机实测同一屏
    进度锚点给出 +30，而名字区需要 0），用全局偏移会让某一行整体错位——错位后
    名字读到的是卡片里的描述文字，徽章区域也一起偏掉，于是「已领取」永远读不到。
    列与列之间水平位置是固定的，所以只搜第一列即可。

    Args:
        image: 截图
        ocr: ocr(image, area, lang) -> str
        season: 赛季
        row: 行号 0-1
        base: 起始偏移（一般来自进度锚点）
        span: 上下搜索范围
        step: 搜索步长

    Returns:
        int: 该行的偏移（找不到时返回 base）
    """
    names = {normalize_name(name) for name, _, _ in plan_tasks(season)}
    x1, _ = CARD_COLUMNS[0]
    y1 = card_top(row)
    for delta in (0, -step, step, -2 * step, 2 * step, -3 * step, 3 * step,
                  -4 * step, 4 * step, -5 * step, 5 * step):
        if abs(delta) > span:
            continue
        offset = base + delta
        box = (x1 + NAME_BOX[0], y1 + NAME_BOX[1] + offset,
               x1 + NAME_BOX[2], y1 + NAME_BOX[3] + offset)
        if normalize_name(ocr(image, box, NAME_LANG)) in names:
            return offset
    return base


def merge_claimed(old, new):
    """
    合并同一张卡在多屏上的领取状态。

    优先级 True > False > None：读到过徽章就是已领取；只有完整可见却没读到才算
    未领取；两屏都被裁掉则仍是未知。

    Args:
        old: 已有的 claimed
        new: 本次读到的 claimed

    Returns:
        bool|None: 合并结果
    """
    if old is True or new is True:
        return True
    if old is False or new is False:
        return False
    return None


def read_cards(image, ocr, season=None, offsets=None):
    """
    读取一屏任务卡片。

    Args:
        image: 1280x720 截图（numpy 数组）
        ocr: 可调用对象 ocr(image, area, lang) -> str（便于离线测试注入假实现）
        season: 赛季；传入时把卡片映射到赛季任务

    Returns:
        list[dict]: [{'row', 'col', 'name', 'have', 'need', 'task', 'item'}, ...]
            识别不到任务名的卡片会被跳过
    """
    cards = []
    offsets = offsets or {}
    for row in range(len(CARD_ROWS)):
        offset = offsets.get(row, 0)
        for col in range(len(CARD_COLUMNS)):
            name_box, progress_box = card_boxes(row, col)
            name_box = (name_box[0], name_box[1] + offset, name_box[2], name_box[3] + offset)
            progress_box = (progress_box[0], progress_box[1] + offset,
                            progress_box[2], progress_box[3] + offset)
            name = normalize_name(ocr(image, name_box, NAME_LANG))
            if not name:
                continue
            have, need = parse_progress(ocr(image, progress_box, PROGRESS_LANG)) or (0, 0)
            card = {'row': row, 'col': col, 'name': name, 'have': have, 'need': need,
                    'claimed': read_claim(ocr, image, row, col, offset),  # 可能为 None：徽章被裁掉
                    'task': None, 'item': None,
                    # 带上本次读屏用的行偏移：外面要按偏移点「提交」按钮，
                    # 之前在这里漏传过一次，导致 NameError（真机每轮崩一次）
                    'offset': offset}
            if season:
                task, item, need_cfg = match_task(name, season)
                card.update({'task': task, 'item': item})
                if need_cfg and not need:
                    card['need'] = need_cfg
            cards.append(card)
    return cards

def _default_ocr(image, area, lang):
    """真机 OCR：按坐标裁剪识别。"""
    from module.ocr.ocr import Ocr
    return Ocr(area, lang=lang).ocr(image)


# 赛季页底部页签：1=活动总览 2=累积PT 3=开发计划 4=开发商店 5=开发排行榜 6=开发回顾
TAB_CENTERS = (107, 320, 533, 746, 959, 1172)
TAB_Y = 694
PLAN_TAB_INDEX = 3

SCROLL_SETTLE = 1.0               # 拖动后等惯性停下
MAX_SCROLLS = 12                  # 任务总数十几项，多翻几屏
EMPTY_LIMIT = 3                   # 连续几屏无新任务才判定到底



def tab_brightness(image):
    """取 6 个底部页签的亮度（选中的白色胶囊明显更亮）。"""
    return [float(image[TAB_Y - 12:TAB_Y + 12, cx - 60:cx + 60].mean())
            for cx in TAB_CENTERS]




def scroll_to_top(island, attempts=3):
    """
    把任务列表拉回顶部（一次大距离上滑，不够再补）。

    列表滚动位置会保留到下一次进入页面（真机实测：上一轮停在底部时，下一轮
    直接从底部开始读，只读到零星几项）。

    Args:
        island: 岛屿任务实例
        attempts: 最多滑几次
    """
    for _ in range(attempts):
        island.device.stuck_record_clear()
        scroll_list(island, down=False)
    island.device.sleep(1.0)
    island.device.stuck_record_clear()


# 该页面不吃 swipe/swipe_vector（试过多种 box 与时长，列表纹丝不动），
# 但「按住 - 慢拖 - 松手」的 drag 能滚动（真机实测：drag 之后的截图里
# 出现了原本在屏幕外的「便携快餐 / 麦田守望」）。
DRAG_X = 640
DRAG_Y = {True: (520, 180), False: (180, 520)}
DRAG_NAME = 'SEASON_PLAN_DRAG'


def scroll_list(island, down=True):
    """
    拖动任务列表一屏。

    Args:
        island: 岛屿任务实例
        down: True 向下翻（看后面的任务），False 回到顶部
    """
    start, end = DRAG_Y[down]
    island.device.drag((DRAG_X, start), (DRAG_X, end), segments=4, shake=(0, 8),
                       hold_duration=0.5, swipe_duration=1.5, name=DRAG_NAME)
    # Add by MHY, 立刻清掉本次拖拽记录：一轮要拖十几次（回顶 3 次 + 读屏最多 12 次），
    # 累计超过单操作 12 次阈值会抛 GameTooManyClickError 并把游戏重启
    # （真机 21:23、21:25 各一次，读到第 9 屏时触发）。drag 不是点击，
    # 本来就不该计入点击保护；清记录不会掩盖真正的连点问题（那些走的是 click）。
    island.device.click_record_remove(DRAG_NAME)
    island.device.sleep(SCROLL_SETTLE)


def _read_screen(island, ocr, season):
    from module.logger import logger

    """
    读一屏卡片：先定位行偏移（滚动后固定坐标会失效），再按该偏移读。

    读空时等一会儿重试一次（页面可能还在绘制或惯性未停）。
    """
    for attempt in range(2):
        island.device.stuck_record_clear()
        island.device.screenshot()
        image = island.device.image
        # 进度锚点先粗定各行位置（能覆盖滚动后的任意偏移），再按行用任务名精定位
        anchors = detect_row_offsets(image, ocr, season)
        offsets = {row: find_row_offset(image, ocr, season, row,
                                        base=anchors.get(row, 0))
                   for row in range(len(CARD_ROWS))}
        island.device.stuck_record_clear()
        cards = read_cards(image, ocr, season=season, offsets=offsets)
        # 必须至少有一张卡片匹配上任务名：偏移不对时读到的是描述文字，
        # 那种「读到了内容」不能算成功（真机踩过）
        if any(card['task'] for card in cards):
            logger.info(f"[岛屿-赛季计划] 行偏移 {offsets}，读到 {len(cards)} 张")
            return cards
        if attempt == 0:
            island.device.sleep(1.5)
    return []


def _save_debug_image(island, index):
    """读不到卡片时存一张现场图，便于排查（正常情况不落盘，避免占用磁盘）。"""
    import os
    try:
        from PIL import Image
        directory = 'log'
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        Image.fromarray(island.device.image).save(
            os.path.join(directory, f'island_season_plan_p{index + 1}.png'))
    except Exception:
        pass


def ensure_bottom_tab(island, index=PLAN_TAB_INDEX):
    """
    切换到赛季页底部第 index 个页签。

    不走 IslandUI.island_season_bottom_navbar_ensure：那个方法在 IslandUI 上，
    而店铺/农场类只继承 Island，真机会 AttributeError。这里自包含实现，
    用「选中页签是白色胶囊、亮度最高」判断是否已切换成功。

    Args:
        island: 岛屿任务实例
        index: 1-6，3 为「开发计划」

    Returns:
        bool: 是否已切到目标页签
    """
    from module.logger import logger

    target = TAB_CENTERS[index - 1]
    for _ in island.loop(timeout=12):
        island.device.screenshot()
        values = tab_brightness(island.device.image)
        if values[index - 1] >= max(values) - 5:
            logger.info(f"[岛屿-赛季计划] 已切到第 {index} 个页签（亮度 "
                        f"{values[index - 1]:.0f}，其它 {max(v for i, v in enumerate(values) if i != index - 1):.0f}）")
            return True
        island.device.click_minitouch(target, TAB_Y)
    return False


def enter_season_page(island):
    """
    从岛屿主页进入赛季「开发计划」页。

    导航复用 ALAS 既有设施：岛屿主页 → 右上角「开发季」→ 底部第 3 页签
    「开发计划」。

    Args:
        island: 带 UI 能力的岛屿任务实例（Island 子类）

    Returns:
        bool: 是否已停在「开发计划」页；失败时已退回岛屿页
    """
    from module.island_season_plan.assets import ISLAND_SEASON_ENTRY
    from module.logger import logger
    from module.ui.assets import ISLAND_SEASON_GOTO_ISLAND
    from module.ui.page import page_island

    # 页面标记用「返回岛屿」白色按钮，而不是 ISLAND_SEASON_CHECK：
    # 后者注册色是蓝调 (99,106,117)，秋季主题是橙褐调 (99,84,76)，差值 42
    # 超出容差，真机上永远匹配不上（页面开了也识别不到）。
    island.ui_goto(page_island, get_ship=False)
    for _ in island.loop(timeout=20):
        if island.appear(ISLAND_SEASON_GOTO_ISLAND):
            break
        # 不加 offset：按钮区域加宽后点击会落到图标外的空白处（真机踩过）
        if island.appear_then_click(ISLAND_SEASON_ENTRY, interval=2):
            continue
    island.device.stuck_record_clear()
    if not island.appear(ISLAND_SEASON_GOTO_ISLAND):
        # Add by MHY, 入口区域被生成器覆盖成左上角 (0,0,56,54) 时这里只留一行告警，
        # 十天都没人发现；带上匹配区域与实测均色，下次一眼能看出是识别还是导航的问题
        entry_seen = island.appear(ISLAND_SEASON_ENTRY)
        logger.warning(f'[岛屿-赛季计划] 进入开发季页面失败，退回岛屿页'
                       f'（入口区域 {ISLAND_SEASON_ENTRY.area}，入口识别 {entry_seen}）')
        leave_season_page(island, timeout=6)
        return False

    if not ensure_bottom_tab(island, index=PLAN_TAB_INDEX):
        logger.warning('[岛屿-赛季计划] 切换到「开发计划」页签失败')
        leave_season_page(island, timeout=6)
        return False
    return True


def read_season_plan_page(island, season, max_scrolls=MAX_SCROLLS, ocr=_default_ocr,
                         on_cards=None):
    """
    进入赛季「开发计划」页面并读取全部任务卡片。

    Args:
        island: 带 UI 能力的岛屿任务实例（Island 子类）
        season: 赛季
        max_scrolls: 最多向下翻几屏
        ocr: 可调用对象 ocr(image, area, lang) -> str，便于离线测试注入
        on_cards: 每读完一屏调用一次 on_cards(cards)。提交要靠它就地完成：
            卡片此刻就在这一屏、坐标是现场读到的；等整页读完再回头找，列表已经
            滚走，两次扫描撞上的屏还不一样（真机踩过，10-01 的 111 次点击全落空）

    Returns:
        dict: {任务名: {'item', 'have', 'need'}}；读取失败返回 {}
    """
    from module.logger import logger

    result = {}
    if not enter_season_page(island):
        return {}

    # 页面滚动位置会保留：先反复下滑回到顶部。之前只滑 3-4 次不够，
    # 上一轮停在底部时新的一轮会从底部开始读，只读到零星几项。
    scroll_to_top(island)

    seen = set()
    empty_screens = 0
    for index in range(max_scrolls):
        cards = _read_screen(island, ocr, season)
        if not cards:
            _save_debug_image(island, index)
        new = 0
        for card in cards:
            task = card['task']
            if not task:
                continue
            prev = result.get(task)
            if prev is None:
                result[task] = {'item': card['item'], 'have': card['have'],
                                'need': card['need'], 'claimed': card['claimed'],
                                'row': card['row'], 'col': card['col'],
                                'offset': card['offset']}
                seen.add(task)
                new += 1
                continue
            # Add by MHY, 同一张卡会被相邻两屏重复读到：滚动步长 340px 与卡片行距
            # 229px 不整除，卡片必然重现在下一屏。原先「首次读到即定稿」，第一次
            # 漏读徽章就永远算未领取——真机实测 32 次读里 28 次漏读；滚到屏幕下沿
            # 时徽章更是直接被裁掉。合并规则见 merge_claimed。
            merged = merge_claimed(prev['claimed'], card['claimed'])
            if merged != prev['claimed']:
                flag = '已领取' if merged is True else ('未领取' if merged is False else '未知')
                logger.info(f"[岛屿-赛季计划] {task} 修正为「{flag}」（第 {index + 1} 屏）")
                prev['claimed'] = merged
        logger.info(f"[岛屿-赛季计划] 第 {index + 1} 屏读到 {new} 个新任务，"
                    f"累计 {len(result)} 个")
        if on_cards is not None:
            on_cards(cards)
        if new:
            empty_screens = 0
        else:
            empty_screens += 1
            if empty_screens >= EMPTY_LIMIT:
                logger.info(f'[岛屿-赛季计划] 连续 {EMPTY_LIMIT} 屏无新任务，判定到底')
                break
        scroll_list(island)

    # 读完必须退回岛屿页：ALAS 的任务从岛屿页继续，留在赛季页会让上层
    # 识别失败（真机表现为 [UI] 未知UI页面 → 重启游戏）
    leave_season_page(island)
    return result


def leave_season_page(island, timeout=8):
    """
    从赛季页退回岛屿页，避免把上层任务留在无法识别的页面。

    Args:
        island: 岛屿任务实例
        timeout: 超时时间（秒）

    Returns:
        bool: 是否已回到岛屿页
    """
    from module.island.assets import ISLAND_BACK
    from module.logger import logger
    from module.ui.assets import ISLAND_SEASON_GOTO_ISLAND

    # 不用 ui_get_current_page：它会遍历所有页面模板，单次就要好几秒，
    # 循环里根本来不及点击（真机踩过）。改用「赛季页返回按钮是否还在」判断。
    for _ in island.loop(timeout=timeout):
        if not island.appear(ISLAND_SEASON_GOTO_ISLAND):
            logger.info('[岛屿-赛季计划] 已退出赛季页')
            return True
        if island.appear_then_click(ISLAND_SEASON_GOTO_ISLAND, interval=1):
            continue
        if island.appear_then_click(ISLAND_BACK, interval=1):
            continue

    # 兜底：再补点两次返回，宁可多退一层也不要留在赛季页
    for _ in range(2):
        island.appear_then_click(ISLAND_SEASON_GOTO_ISLAND, interval=1)
        island.appear_then_click(ISLAND_BACK, interval=1)
    logger.warning('[岛屿-赛季计划] 未能确认退回岛屿页，已补点返回')
    return False


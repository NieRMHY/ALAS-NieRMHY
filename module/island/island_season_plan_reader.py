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
PROGRESS_BOX = (-110, 18, -20, 46)

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


def read_cards(image, ocr, season=None):
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
    for row in range(len(CARD_ROWS)):
        for col in range(len(CARD_COLUMNS)):
            name_box, progress_box = card_boxes(row, col)
            name = normalize_name(ocr(image, name_box, NAME_LANG))
            if not name:
                continue
            have, need = parse_progress(ocr(image, progress_box, PROGRESS_LANG)) or (0, 0)
            card = {'row': row, 'col': col, 'name': name, 'have': have, 'need': need,
                    'task': None, 'item': None}
            if season:
                task, item, need_cfg = match_task(name, season)
                card.update({'task': task, 'item': item})
                if need_cfg and not need:
                    card['need'] = need_cfg
            cards.append(card)
    return cards

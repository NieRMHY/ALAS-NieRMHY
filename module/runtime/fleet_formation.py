"""编队的固定舰位、卡面定位及Lua姓名与心情确认。"""

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import re

import cv2
import numpy as np
from PIL import Image

from module.base.utils import crop, image_color_count
from module.ocr.ocr import Ocr
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.retire.dock import CARD_GRIDS
from module.retire.assets import DOCK_SELECTED
from module.retire.scanner import FleetEmotionScanner, FleetNameScanner, FleetScanner, LevelScanner
from module.runtime.mind_level import dock_level_reader
from module.runtime.mind_recognition import Card, ScanMerger, fleet_status, grid_rows


SLOT_CENTERS = {1: (589, 249), 2: (800, 211), 3: (367, 286),
                4: (510, 438), 5: (757, 389), 6: (974, 343)}
SUBMARINE_SLOT_CENTERS = {1: (625, 281), 2: (843, 248), 3: (401, 329)}
DETAIL_LEFTS = (60, 246, 433, 686, 873, 1059)
CATEGORY_SLOTS = {'main': (1, 2, 3), 'vanguard': (4, 5, 6), 'submarine': (1, 2, 3)}
TYPE_BUTTON_AREAS = {'surface': (22, 650, 122, 702), 'submarine': (387, 650, 490, 702)}
OCR_FAILURES = (ValueError, RuntimeError, TypeError, OSError, MemoryError, RequestHumanTakeover)


def validate_position(fleet, slot, fleet_type='surface'):
    if fleet_type not in ('surface', 'submarine'):
        raise ValueError('舰队类型必须为 surface 或 submarine')
    count, slots = (6, SLOT_CENTERS) if fleet_type == 'surface' else (2, SUBMARINE_SLOT_CENTERS)
    if type(fleet) is not int or not 1 <= fleet <= count:
        raise ValueError(f'{fleet_type} 舰队号必须为 1–{count} 的整数')
    if type(slot) is not int or slot not in slots:
        raise ValueError(f'{fleet_type} 的舰位号无效：{slot}')


def validate_swap(source_fleet, source_slot, fleet, slot, fleet_type='surface'):
    validate_position(source_fleet, source_slot, fleet_type)
    validate_position(fleet, slot, fleet_type)
    if fleet_type == 'surface' and (source_slot <= 3) != (slot <= 3):
        raise ValueError('主力舰位与先锋舰位不能互换')


def slot_swap_plan(occupied, source_fleet, source_slot, fleet, slot, fleet_type='surface'):
    """按位置生成交换预期，标记代表原舰位卡面，不代表OCR身份。"""
    validate_swap(source_fleet, source_slot, fleet, slot, fleet_type)
    result = {number: {position: f'{number}:{position}' if present else None
                       for position, present in positions.items()} for number, positions in occupied.items()}
    source = result[source_fleet][source_slot]
    previous = result[fleet][slot]
    if source is None:
        raise ValueError('源舰位没有舰船，不能执行互换')
    if previous is None:
        group = (1, 2, 3) if fleet_type == 'submarine' or slot <= 3 else (4, 5, 6)
        next_slot = next((position for position in group if result[fleet][position] is None), None)
        if slot != next_slot or source_fleet == fleet:
            raise ValueError('空舰位需按组内顺序添加；同队空位移动会压缩舰位')
        remaining = [result[source_fleet][position] for position in group if position != source_slot
                     and result[source_fleet][position] is not None]
        for position, value in zip(group, remaining + [None] * (3 - len(remaining))):
            result[source_fleet][position] = value
    else:
        result[source_fleet][source_slot] = previous
    result[fleet][slot] = source
    return result


def detail_portraits(image, fleet_type='surface'):
    """详情左到右为水面1–6、潜艇1–3；只截卡面，不截舰名、等级和心情。"""
    count = 6 if fleet_type == 'surface' else 3
    return {slot: np.asarray(image)[181:441, left + 4:left + 153].copy()
            for slot, left in enumerate(DETAIL_LEFTS[:count], 1)}


def detail_occupied(image, slot):
    """以详情卡片的原生等级字形区域确认有船，和文字识别结果无关。"""
    left = DETAIL_LEFTS[slot - 1]
    header = np.asarray(image)[155:180, left + 82:left + 153]
    return int(np.sum(header.min(axis=2) > 210)) >= 12


@lru_cache(maxsize=1)
def selector_arrow():
    return np.array(Image.open(Path(__file__).parents[2] / 'assets/ship/formation_selector_arrow.png').convert('L'))


def selector_closed(image, fleet_type='surface'):
    left = 202 if fleet_type == 'surface' else 568
    region = np.asarray(image)[599:644, left:left + 39]
    binary = (region.min(axis=2) > 205).astype(np.uint8) * 255
    score = cv2.minMaxLoc(cv2.matchTemplate(binary, selector_arrow(), cv2.TM_CCOEFF_NORMED))[1]
    return score >= .75


def menu_area(fleet, fleet_type='surface'):
    validate_position(fleet, 1, fleet_type)
    left = 152 if fleet_type == 'surface' else 516
    top = 586 - (fleet - 1) * 54
    return left, top, left + 201, top + 42


def selected_menu_fleet(image, fleet_type='surface'):
    """读取下拉列表的高亮行；不用舰队编号 OCR 判断当前队。"""
    count = 6 if fleet_type == 'surface' else 2
    gold, gray = [], []
    for fleet in range(1, count + 1):
        x1, y1, x2, y2 = menu_area(fleet, fleet_type)
        region = np.asarray(image)[y1 + 3:y2 - 3, x1 + 3:x2 - 3]
        if image_color_count(region, (255, 194, 73), threshold=55, count=500):
            gold.append(fleet)
        elif image_color_count(region, (180, 185, 202), threshold=40, count=500):
            gray.append(fleet)
    return gold[0] if len(gold) == 1 and len(gray) == count - 1 else None


def fleet_type_selected(image, fleet_type='surface'):
    """底部类型按钮使用棕金色渐变，和展开菜单的亮金色高亮不同。"""
    region = crop(np.asarray(image), TYPE_BUTTON_AREAS[fleet_type])
    return image_color_count(region, (160, 120, 70), threshold=45, count=350)


@lru_cache(maxsize=1)
def fleet_index_templates():
    root = Path(__file__).parents[2] / 'assets/ship'
    return tuple(np.array(Image.open(root / f'formation_index_{fleet}.png').convert('L'))
                 for fleet in range(1, 7))


def bottom_fleet_index(image, fleet_type='surface'):
    """按底部大号数字的原生字形核对队号，不展开列表或读取文字OCR。"""
    left = 298 if fleet_type == 'surface' else 664
    region = cv2.cvtColor(np.asarray(image)[647:707, left:left + 50], cv2.COLOR_RGB2GRAY)
    count = 6 if fleet_type == 'surface' else 2
    scores = [cv2.minMaxLoc(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED))[1]
              for template in fleet_index_templates()[:count]]
    ordered = sorted(range(count), key=scores.__getitem__, reverse=True)
    best, second = ordered[:2]
    return best + 1 if scores[best] >= .85 and scores[best] - scores[second] >= .1 else None


def selected_count_changed(before, after):
    """新打开的单选页从0选到1：比对计数图像变化，不调用数字 OCR。"""
    x1, y1, x2, y2 = DOCK_SELECTED.area
    old = np.asarray(before)[y1:y2, x1:x2].astype(np.int16)
    new = np.asarray(after)[y1:y2, x1:x2].astype(np.int16)
    # 只允许计数左侧改变，右侧 /1 保持原样，避免把弹窗遮罩当作选中。
    split = round((x2 - x1) / 2)
    return (float(np.mean(np.abs(old[:, :split] - new[:, :split]))) > 2
            and float(np.mean(np.abs(old[:, split:] - new[:, split:]))) < 1.5)


class PortraitMatcher:
    """用源舰位卡面的 SIFT 特征定位船坞卡片，不读取名字、等级或心情。"""

    def __init__(self, portrait):
        self.sift = cv2.SIFT_create(nfeatures=1200, contrastThreshold=.015)
        self.points, self.descriptors = self.features(portrait)

    def features(self, image):
        gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
        return self.sift.detectAndCompute(gray, None)

    def score(self, portrait):
        points, descriptors = self.features(portrait)
        if self.descriptors is None or descriptors is None or len(descriptors) < 2:
            return 0
        pairs = cv2.BFMatcher().knnMatch(self.descriptors, descriptors, k=2)
        good = [first for pair in pairs if len(pair) == 2
                for first, second in [pair] if first.distance < .72 * second.distance]
        if len(good) < 6:
            return 0
        source = np.float32([self.points[match.queryIdx].pt for match in good])
        target = np.float32([points[match.trainIdx].pt for match in good])
        matrix, mask = cv2.estimateAffine2D(source, target, ransacReprojThreshold=2.5,
                                           maxIters=3000, confidence=.99)
        if matrix is None or mask is None or np.linalg.det(matrix[:, :2]) <= 0:
            return 0
        inliers = int(mask.sum())
        return inliers if inliers >= 8 and inliers >= len(good) * .65 else 0


def choose_portrait(candidates, source_fleet):
    """优先唯一卡面匹配；同立绘实体可参考舰队徽标模板消歧，不读取文字。"""
    candidates = sorted(candidates, key=lambda item: item[2], reverse=True)
    if not candidates or candidates[0][2] < 12:
        raise ValueError('未在当前前后排的已编队候选范围找到源舰位卡面')
    strongest = [item for item in candidates if item[2] >= max(12, candidates[0][2] * .75)]
    if len(strongest) == 1:
        return strongest[0][:2]
    located = [item for item in strongest if item[0].fleet == source_fleet]
    if len(located) == 1:
        return located[0][:2]
    raise ValueError('多个候选卡面相同，图像无法区分来源实体；尚未执行交换')


def reference_read(reader, image, count, label):
    """识别只服务参考记录；失败保留未知并写日志，不作为换船条件。"""
    try:
        values = reader.scan(image, output=False) if hasattr(reader, 'scan') else reader.ocr(image)
        values = values if isinstance(values, list) else [values]
        return (values + [None] * count)[:count]
    except OCR_FAILURES as exc:
        logger.warning(f'舰队{label}参考信息未读到，保留未知：{exc}')
        return [None] * count


class DetailLevelOcr(Ocr):
    """保留Lv前缀读取详情等级，避免旧裁剪规则吞掉百位或十位。"""

    def after_process(self, result):
        match = re.fullmatch(r'LV[.\s]*([0-9U]{1,3})', str(result).strip().upper())
        if not match:
            return 0
        # 此字体的0底边在缩小时类似U；仅在完整Lv数字串中归一化。
        value = int(match.group(1).replace('U', '0'))
        return value if 1 <= value <= 125 else 0


class FormationDetailScanner:
    def __init__(self):
        self.names = FleetNameScanner(grid_shape=(6, 1))
        self.names.ocr_model.buttons = [(left - 4, 460, left + 157, 491) for left in DETAIL_LEFTS]
        self.levels = DetailLevelOcr([(left + 80, 152, left + 157, 181) for left in DETAIL_LEFTS],
                                     lang='ppocr_v6', name='编队详情等级参考')

    @property
    def matcher(self):
        return self.names.name_matcher

    def scan(self, image, fleet_type='surface'):
        names = reference_read(self.names, image, 6, '舰名')
        levels = reference_read(self.levels, image, 6, '等级')
        count = 6 if fleet_type == 'surface' else 3
        ships = {}
        for slot in range(1, count + 1):
            occupied = detail_occupied(image, slot)
            raw = names[slot - 1] or ''
            name, status = self.matcher.approximate(raw)
            level = levels[slot - 1]
            confirmed = status in ('exact', 'prefix', 'similar')
            ships[slot] = dict(name=name if occupied and confirmed else '', level=level if occupied and
                               type(level) is int and 1 <= level <= 125 else 0, emotion=None,
                               slot=slot, occupied=occupied, review=occupied and not confirmed,
                               raw_name=raw if occupied and (not confirmed or raw != name) else '')
        return ships


class VisualDockScanner:
    """只定位几何卡位和卡面；操作路径不会创建或调用 OCR 识别器。"""

    def __init__(self):
        self.fleets = FleetScanner()

    def scan(self, image, bottom=627, has_remove=True):
        pixels = np.asarray(image)
        rows = [y for y in grid_rows(pixels) if y >= 55 and y + 190 <= bottom]
        if not rows:
            raise ValueError('未能定位选船页的完整卡片行')
        cards = []
        for y in rows:
            for col in range(7):
                x = round(float(CARD_GRIDS.origin[0] + col * CARD_GRIDS.delta[0]))
                badge = crop(pixels, (x, y + 117, x + 35, y + 162))
                fleet = fleet_status(badge, self.fleets)
                # 物理位置作合并键，下面的占位文字不代表舰船身份。
                ship = dict(name=f'卡位{col}', level=0, emotion=None, review=False, source='几何卡位')
                cards.append(Card(x, y, col, ship, 0, False, fleet))
        return cards

    @staticmethod
    def portrait(image, card):
        return np.asarray(image)[card.y + 28:card.y + 162, card.x:card.x + 138]


class MoraleDockScanner(VisualDockScanner):
    """只增加心情参考，不加载舰名或等级OCR。"""

    def __init__(self):
        super().__init__()
        self.emotions = FleetEmotionScanner(grid_shape=(7, 1))
        self.row_offset = 0

    def scan(self, image, bottom=627, has_remove=True):
        cards = super().scan(image, bottom, has_remove)
        for y in sorted({card.y for card in cards}):
            offset = y - int(CARD_GRIDS.origin[1])
            self.emotions.move((0, offset - self.row_offset))
            self.row_offset = offset
            values = reference_read(self.emotions, image, 7, '心情')
            for card in cards:
                if card.y == y:
                    card.ship['emotion'] = values[card.col]
        return cards


class FormationDockScanner:
    """动态定位完整卡片行，舰名、等级、心情与徽标均作为参考信息。"""

    def __init__(self, update_emotion=True, *, fleets=None):
        self.names = FleetNameScanner(grid_shape=(7, 1))
        self.levels = LevelScanner(grid_shape=(7, 1))
        self.emotions = FleetEmotionScanner(grid_shape=(7, 1))
        self.fleets = FleetScanner()
        self.update_emotion = update_emotion
        self.target_fleets = None if fleets is None else set(fleets)
        self.row_offset = 0

    @property
    def matcher(self):
        return self.names.name_matcher

    @staticmethod
    def _read_columns(reader, image, columns, label):
        """保留物理卡位，只向识别器提交目标舰队所在的列。"""
        result = [None] * 7
        if columns:
            buttons = reader.ocr_model.buttons
            try:
                reader.ocr_model.buttons = [buttons[col] for col in columns]
                values = reference_read(reader, image, len(columns), label)
            finally:
                reader.ocr_model.buttons = buttons
            for col, value in zip(columns, values):
                result[col] = value
        return result

    def scan(self, image, bottom=627, has_remove=True):
        pixels = np.asarray(image)
        rows = [y for y in grid_rows(pixels) if y >= 55 and y + 190 <= bottom]
        if pixels.shape != (720, 1280, 3) or not rows:
            raise ValueError('需要1280×720截图和可定位的完整卡片行')
        cards = []
        level_reader = dock_level_reader()
        for y in rows:
            offset = y - int(CARD_GRIDS.origin[1])
            for reader in (self.names, self.levels, self.emotions):
                reader.move((0, offset - self.row_offset))
            self.row_offset = offset
            fleets = [fleet_status(crop(pixels, (x, y + 117, x + 35, y + 162)), self.fleets)
                      for col in range(7)
                      for x in [round(float(CARD_GRIDS.origin[0] + col * CARD_GRIDS.delta[0]))]]
            if self.target_fleets is None:
                names = reference_read(self.names, pixels, 7, '舰名')
                levels = reference_read(self.levels, pixels, 7, '等级')
                emotions = reference_read(self.emotions, pixels, 7, '心情') if self.update_emotion else [None] * 7
            else:
                columns = [col for col, fleet in enumerate(fleets) if fleet in self.target_fleets]
                names = self._read_columns(self.names, pixels, columns, '舰名')
                levels = self._read_columns(self.levels, pixels, columns, '等级')
                emotions = (self._read_columns(self.emotions, pixels, columns, '心情')
                            if self.update_emotion else [None] * 7)
            for col in range(7):
                x = round(float(CARD_GRIDS.origin[0] + col * CARD_GRIDS.delta[0]))
                glyphs, _, _ = level_reader.prepare(pixels[y:y + 32, x + 74:x + 138])
                fleet = fleets[col]
                targeted = self.target_fleets is None or fleet in self.target_fleets
                level = level_reader.read(glyphs) if targeted else 0
                if not level and glyphs and type(levels[col]) is int and 1 <= levels[col] <= 125:
                    level = levels[col]
                if not glyphs and has_remove and col == 0 and y == rows[0]:
                    continue
                if not glyphs and float(pixels[y + 35:y + 150, x:x + 138].std()) < 20:
                    continue
                raw = names[col] or ''
                name, status = self.matcher.approximate(raw)
                confirmed = status in ('exact', 'prefix', 'similar')
                ship = dict(name=name if confirmed else '', level=level, emotion=emotions[col],
                            review=not confirmed or not level, raw_name=raw if not confirmed or raw != name else '',
                            source='编队选船参考')
                cards.append(Card(x, y, col, ship, int(confirmed) + int(bool(level)),
                                  bool(level), fleet))
        return cards


class FormationCardMerger(ScanMerger):
    """复用已由图像定位的物理卡位；文字不一致标记参考疑问，不阻断操作。"""

    def add(self, image, cards):
        image = Image.fromarray(image) if isinstance(image, np.ndarray) else image
        self.advance(image)
        for card in cards:
            previous = next((old for old, y in self.slots if old.col == card.col and
                             abs(y - card.y - self.offset) <= 12), None)
            if previous is None:
                continue
            if card.ship['review'] and not previous.ship['review'] and card.fleet == previous.fleet:
                if card.ship['level'] == previous.ship['level']:
                    card.ship = dict(card.ship, name=previous.ship['name'], review=False)
            elif previous.ship['review'] and not card.ship['review']:
                previous.ship = dict(previous.ship, name=card.ship['name'], level=card.ship['level'], review=False)
            if previous.fleet >= 0 and card.fleet >= 0 and previous.fleet != card.fleet:
                card.ship['review'] = True
                card.ship['source'] += '；舰队徽标读数冲突'
        self.previous = None
        return super().add(image, cards)


def combine_references(dock, formations, dock_portraits=None, detail_images=None):
    """固定详情列确定舰位，以同队同排卡面把第一轮名称、等级和心情放回对应舰位。"""
    result = {'main': {}, 'vanguard': {}, 'submarine': {}}
    for fleet_type, teams in formations.items():
        categories = ('main', 'vanguard') if fleet_type == 'surface' else ('submarine',)
        for fleet, positions in teams.items():
            for category in categories:
                ships = []
                pool = dock.get(category, {}).get(str(fleet), [])
                portraits = (dock_portraits or {}).get(category, {}).get(str(fleet), [])
                image = (detail_images or {}).get(fleet_type, {}).get(fleet)
                used = set()
                for slot in CATEGORY_SLOTS[category]:
                    ship = deepcopy(positions[slot])
                    if not ship['occupied']:
                        continue
                    matches = [item for item in pool
                               if item.get('name') == ship['name'] and ship['name']]
                    if image is not None and len(portraits) == len(pool) and portraits:
                        # 有卡面时不能再用误读的同名文本分配心情，歧义必须保留未知。
                        matches = []
                        matcher = PortraitMatcher(detail_portraits(image, fleet_type)[slot])
                        ranked = sorted(((matcher.score(portrait), index) for index, portrait in enumerate(portraits)
                                         if index not in used), reverse=True)
                        if (ranked and ranked[0][0] >= 12 and
                                (len(ranked) == 1 or ranked[1][0] < ranked[0][0] * .75)):
                            index = ranked[0][1]
                            used.add(index)
                            matches = [pool[index]]
                    if len(matches) == 1:
                        reference = matches[0]
                        ship['emotion'] = reference.get('emotion')
                        if reference.get('name'):
                            ship['name'] = reference['name']
                            ship['review'] = reference.get('review', False)
                        if reference.get('level'):
                            ship['level'] = reference['level']
                    ships.append(ship)
                if ships:
                    result[category][str(fleet)] = ships
    return result


def preserve_emotions(result, previous):
    """未选择更新时，按既有舰位保留心情参考；不推断没有舰位的历史记录。"""
    if not isinstance(previous, dict):
        return result
    for category, fleets in result.items():
        for fleet, ships in fleets.items():
            old = {item['slot']: item for item in previous.get(category, {}).get(fleet, [])
                   if isinstance(item, dict) and type(item.get('slot')) is int}
            for ship in ships:
                if ship['slot'] in old:
                    ship['emotion'] = old[ship['slot']].get('emotion')
    return result

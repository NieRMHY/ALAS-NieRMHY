"""智能换船的舰种装备码及国服详情舰种模板，不操作设备。"""

import json
from functools import lru_cache

import cv2
import numpy as np


EQUIPMENT_PATH = 'FleetInfo.FleetEquipment'
SHIP_TYPES = {'DD': '驱逐', 'CL': '轻巡', 'CA': '重巡', 'CB': '超巡', 'BC': '战巡', 'BB': '战列',
              'CVL': '轻航', 'CV': '航母', 'BBV': '航战', 'SS': '潜艇', 'SSV': '潜母',
              'AR': '维修', 'BM': '重炮', 'AE': '运输', 'IX': '风帆'}
TYPE_AREA = (155, 90, 210, 121)


def parse_codes(value):
    """空装备码表示跳过该舰种；在任何卸装前校验已填写的所有方案。"""
    from module.equipment.equipment_code import EquipmentCodeHandler

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError) as exc:
            raise ValueError('舰种装备码必须为JSON对象') from exc
    if not isinstance(value, dict) or value.keys() - SHIP_TYPES.keys():
        raise ValueError('装备码包含未知舰种或不是舰种映射')
    codes = {}
    for kind, entries in value.items():
        # 旧单码只占第一格，不能复制到三格而继续抢同一套装备。
        entries = [entries] if isinstance(entries, str) else entries
        if not isinstance(entries, list) or len(entries) > 3 or any(not isinstance(code, str) for code in entries):
            raise ValueError(f'{SHIP_TYPES[kind]}必须填写最多三个字符串装备码')
        entries = [code.strip().strip('\'"') for code in entries]
        for index, code in enumerate(entries, 1):
            if code and not EquipmentCodeHandler._is_equipment_code(code):
                raise ValueError(f'{SHIP_TYPES[kind]}第{index}个装备码格式无效')
        if any(entries):
            codes[kind] = entries + [''] * (3 - len(entries))
    return codes


def type_mask(image):
    """提取原生720p徽标中的金色文字，排除稀有度底色与银色外框。"""
    left, top, right, bottom = TYPE_AREA
    hsv = cv2.cvtColor(np.asarray(image)[top:bottom, left:right], cv2.COLOR_RGB2HSV)
    return cv2.inRange(hsv, (12, 110, 150), (40, 255, 255)) > 0


@lru_cache(maxsize=1)
def type_templates():
    from module.equipment import assets

    return {kind: getattr(assets, f'TEMPLATE_FLEET_TYPE_{kind}').image[:, :, 0] > 0 for kind in SHIP_TYPES}


def recognize_ship_type(image):
    """只接受高分且唯一的舰种，不能把未知舰种默认当作驱逐。"""
    if np.asarray(image).shape != (720, 1280, 3):
        return None
    mask = type_mask(image)
    count = np.count_nonzero(mask)
    if count < 50:
        return None
    padded = np.pad(mask, 2)
    height, width = mask.shape
    scores = []
    for kind, template in type_templates().items():
        total = count + np.count_nonzero(template)
        score = max(2 * np.count_nonzero(template & padded[y:y + height, x:x + width]) / total
                    for y in range(5) for x in range(5))
        scores.append((score, kind))
    scores.sort(reverse=True)
    if scores[0][0] >= .9 and scores[0][0] - scores[1][0] >= .12:
        return scores[0][1]
    return None

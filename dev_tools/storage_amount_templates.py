"""从人工核对的原生仓库数量生成固定字高的灰度采样相位模板。"""

import json
from pathlib import Path

import cv2
import numpy as np

from module.base.utils import extract_white_letters, load_image
from module.storage.amount_glyphs import GLYPH_HEIGHT, GLYPH_WIDTH, native_glyph
from module.storage.statistics_recognition import ROOT, StorageCatalog, StorageRecognitionError, detect_rows


def native_samples(source):
    """合并滚动数量切片与原始目录截图，覆盖不同材料的原生采样形态。"""
    samples = load_image(str(source / 'live_digits.png'))
    for case in json.loads((source / 'live_digits.json').read_text(encoding='utf-8')):
        start = case['row'] * 27
        yield samples[start:start + 27], str(case['amount'])
    pages = {}
    for case in json.loads((source / 'expected.json').read_text(encoding='utf-8')):
        if case['page'] not in pages:
            pages[case['page']] = detect_rows(load_image(str(source / f"page_{case['page']}.png")))
        card = pages[case['page']][case['row']][case['column']]
        yield card.image[99:126, 25:127], str(case['amount'])


def generate(source=ROOT / 'tests/fixtures/storage_statistics',
             destination=ROOT / 'assets/stats/storage_items/amount_glyphs.png'):
    """保留原生灰度，仅合成有限采样相位；不从 OCR 输出生成标签。"""
    source = Path(source)
    glyphs = [dict() for _ in range(10)]
    for crop, text in native_samples(source):
        for dx in (0., .25, .5, .75):
            for dy in (0., .25, .5, .75):
                shifted = cv2.warpAffine(crop, np.array([[1, 0, dx], [0, 1, dy]], dtype=np.float32),
                                         (102, 27), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                image = extract_white_letters(shifted, threshold=96)
                try:
                    _, parts, baseline = StorageCatalog._amount_parts(image < 100)
                except StorageRecognitionError:
                    continue
                # 相位导致粘连或截断时不能强制给组件贴数字标签。
                if len(parts) != len(text) or any(width > height * .85 for _, _, _, width, height in parts):
                    continue
                for digit, (_, x, _, width, _) in zip(text, parts):
                    glyph = native_glyph(image, x, width, baseline)
                    glyphs[int(digit)][glyph.tobytes()] = glyph
    if any(not group for group in glyphs):
        raise ValueError('原生样本未覆盖所有数字')
    atlas = np.full((max(map(len, glyphs)) * GLYPH_HEIGHT, 10 * GLYPH_WIDTH), 255, dtype=np.uint8)
    for digit, group in enumerate(glyphs):
        for row, glyph in enumerate(group.values()):
            atlas[row * GLYPH_HEIGHT:(row + 1) * GLYPH_HEIGHT,
                  digit * GLYPH_WIDTH:(digit + 1) * GLYPH_WIDTH] = glyph
    if not cv2.imwrite(str(destination), atlas):
        raise OSError('无法保存仓库灰度数量模板')
    print('仓库灰度数量模板：', list(map(len, glyphs)))


if __name__ == '__main__':
    generate()

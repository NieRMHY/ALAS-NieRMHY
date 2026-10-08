"""掉落数量的逐位字形匹配，适配 96px 弹窗与 64px 奖励格。

小数字不适合只依赖整行 OCR：重复的 7 会丢位，图标纸角又会被拼成首位。
这里按数量字体的高度、基线和间距分出数字，再用本地字形模板交叉匹配。
低相似度或候选接近时返回 None，让调用方继续使用配置中的 OCR 后端。
"""

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from module.base.utils import extract_white_letters

GLYPH_SIZE = 24
MAX_ERROR = 0.025
MIN_MARGIN = 0.025
TEMPLATE_FOLDER = Path(__file__).resolve().parents[2] / 'assets/stats/amount_digits'


def normalize_glyph(mask):
    """保留字形宽高比并居中，避免把窄体 1 拉伸成其他数字。"""
    width = min(GLYPH_SIZE, max(1, round(mask.shape[1] * GLYPH_SIZE / mask.shape[0])))
    scaled = cv2.resize(mask.astype(np.float32), (width, GLYPH_SIZE), interpolation=cv2.INTER_AREA)
    result = np.zeros((GLYPH_SIZE, GLYPH_SIZE), np.float32)
    left = (GLYPH_SIZE - width) // 2
    result[:, left:left + width] = scaled
    return result


class DigitTemplates:
    """数字模板及粘连字形的有界拆分。"""

    def __init__(self, atlas):
        masks = []
        labels = []
        for digit in range(10):
            for y in range(0, atlas.shape[0], GLYPH_SIZE):
                glyph = atlas[y:y + GLYPH_SIZE, digit * GLYPH_SIZE:(digit + 1) * GLYPH_SIZE]
                if np.any(glyph < 250):
                    masks.append((255 - glyph.astype(np.float32)) / 255)
                    labels.append(digit)
        self.masks = np.array(masks, dtype=np.float32)
        self.labels = np.array(labels)

    def classify(self, mask):
        errors = np.mean((self.masks - normalize_glyph(mask)) ** 2, axis=(1, 2))
        ranks = sorted((float(errors[self.labels == digit].min()), digit) for digit in range(10))
        return ranks[0][1], ranks[0][0], ranks[1][0] - ranks[0][0]

    def split(self, mask):
        """从右向左尝试有限字宽，保留粘连的 71、77 等完整数量。"""
        @lru_cache(None)
        def solve(end):
            if end <= 0:
                return 0., '', []
            if not mask[:, end - 1].any():
                return solve(end - 1)
            best = (float('inf'), '', [])
            for width in range(2, min(end, round(mask.shape[0] * .85)) + 1):
                begin = end - width
                part = mask[:, begin:end]
                if not part[:, 0].any() or not part[:, -1].any():
                    continue
                rows = np.where(part)[0]
                if rows.size == 0 or rows.max() - rows.min() + 1 < mask.shape[0] - 2:
                    continue
                digit, error, margin = self.classify(part[rows.min():rows.max() + 1])
                previous, text, scores = solve(begin)
                # 拆分惩罚防止将单个 8 等数字凑成若干个窄笔画。
                cost = previous + error + .018
                if cost < best[0]:
                    best = cost, text + str(digit), scores + [(error, margin)]
            return best

        _, text, scores = solve(mask.shape[1])
        return text, scores

    @staticmethod
    def confident(scores):
        """近乎逐像素一致的字形也需与次优候选有明确差距。"""
        return bool(scores) and all(
            error < MAX_ERROR and (margin > MIN_MARGIN or (error < .001 and margin > .008))
            for error, margin in scores
        )

    def split_icon_suffix(self, mask):
        """分离连着纸角的数字尾部，只忽略无法组成数字的宽图标前缀。"""
        best = ('', [])
        best_error = float('inf')
        # 前缀至少一个字高，避免把不确定的单个首位数字当作图标删除。
        for begin in range(mask.shape[0], mask.shape[1] - 1):
            text, scores = self.split(mask[:, begin:])
            if not text or not self.confident(scores):
                continue
            prefix, prefix_scores = self.split(mask[:, :begin])
            if prefix and all(error <= .1 for error, _ in prefix_scores):
                continue
            error = sum(score for score, _ in scores) / len(scores)
            if len(text) > len(best[0]) or (len(text) == len(best[0]) and error < best_error):
                best, best_error = (text, scores), error
        return best

    def read(self, image):
        binary = (extract_white_letters(image, threshold=96) < 100).astype(np.uint8)
        _, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        min_height = 8 if image.shape[0] <= 14 else 10
        parts = []
        for label, (x, y, width, height, area) in enumerate(stats[1:], 1):
            if height >= min_height and width <= 42 and area >= 8:
                # 包围盒里可能还有不相连的纸角，必须只取当前组件的像素。
                mask = (labels[y:y + height, x:x + width] == label).astype(np.uint8)
                parts.append((int(x), int(y), int(width), int(height), mask))
        parts.sort(key=lambda part: part[0])
        if not parts:
            return None
        baseline = parts[-1][1] + parts[-1][3]
        parts = [part for part in parts if abs(part[1] + part[3] - baseline) <= 2]
        selected = [parts[-1]]
        for part in reversed(parts[:-1]):
            if selected[-1][0] - part[0] - part[2] > 4:
                break
            selected.append(part)

        result = ''
        for part in reversed(selected):
            text, scores = self.split(part[4])
            # 数量左侧有时紧贴大片纸角/齿轮。它们虽然字高相近，但横向跨度
            # 大、拆分后也明显不像数字；排除这种图标组件，不丢弃相似的未知字形。
            if part is not selected[0] and part[2] >= part[3] and (
                not text or any(error > .1 for error, _ in scores)
            ):
                text, scores = self.split_icon_suffix(part[4])
                if not text:
                    continue
            if not text or not self.confident(scores):
                return None
            result += text
        if not result or result.startswith('0'):
            return None
        return int(result)


@lru_cache(maxsize=2)
def load_digit_templates(layout):
    atlas = cv2.imread(str(TEMPLATE_FOLDER / f'{layout}.png'), cv2.IMREAD_GRAYSCALE)
    if atlas is None or atlas.shape[1] != GLYPH_SIZE * 10 or atlas.shape[0] % GLYPH_SIZE:
        return None
    templates = DigitTemplates(atlas)
    if set(templates.labels) != set(range(10)):
        return None
    return templates


def read_amount_digits(image):
    """读取原始数量切片；模板缺失或字形不确定时返回 None。"""
    if image.ndim != 3 or min(image.shape[:2]) < 2:
        return None
    layout = 'reward' if image.shape[0] <= 14 else 'popup'
    templates = load_digit_templates(layout)
    return templates.read(image) if templates is not None else None

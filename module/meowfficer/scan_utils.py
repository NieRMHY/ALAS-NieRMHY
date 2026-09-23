from module.base.button import Button, ButtonGrid
"""指挥喵扫描用到的纯图像/文本工具函数。

从 :mod:`module.meowfficer.scan` 拆出来，一是让扫描主流程保持在 500 行以内
（仓库约定），二是这些函数不依赖设备，可以单独测试。
"""

import re

import numpy as np

# 相关能测到的最大位移（超过面板高度就没有重叠可对了）
MAX_SCROLL_SHIFT = 300
# 猫名 OCR 结果里需要排除的界面词
NAME_NOISE = ('空闲中', '后勤', '指挥', '战术', '加成', '一览', '技能', '天赋',
              '陪玩', '锁定', '使用', '成长', '确认', '消耗', '容量', '猫窝',
              '订购', '训练', '排行', '等级')


def _crop(image: np.ndarray, area: tuple) -> np.ndarray:
    """按 ``(x0, y0, x1, y1)`` 裁剪图像。"""
    x0, y0, x1, y1 = area
    return image[y0:y1, x0:x1]


def _mean_diff(a: np.ndarray, b: np.ndarray) -> float:
    """两张同尺寸图像的平均像素差，用于判断画面是否还在变化。"""
    if a is None or b is None or a.shape != b.shape:
        return 255.0
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def scroll_offset(before: np.ndarray, after: np.ndarray, max_shift: int = MAX_SCROLL_SHIFT) -> int:
    """估算 ``after`` 相对 ``before`` 内容向上滚动了多少像素。

    内容向上滚（看到更后面的猫）时，``before`` 里 y 处的图像会出现在 ``after`` 的 y-dy 处，
    所以拿 ``before[dy:]`` 和 ``after[:h-dy]`` 逐 dy 比较，取平均差最小的那个 dy。

    Args:
        before: 滚动前裁剪的面板图像。
        after: 滚动后同区域的面板图像。
        max_shift: 最大可测位移（超出面板高度就没有重叠可对了）。

    Returns:
        int: 向上滚动的像素数；画面基本没动时返回 0。
    """
    if before is None or after is None or before.shape != after.shape or before.size == 0:
        return 0
    height = before.shape[0]
    best_dy, best_diff = 0, None
    for dy in range(0, min(max_shift, height - 1) + 1):
        a = before[dy:]
        b = after[:len(a)]
        if a.size == 0:
            break
        diff = float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())
        if best_diff is None or diff < best_diff:
            best_dy, best_diff = dy, diff
    return best_dy


def pick_cat_name(texts) -> str:
    """从一组 OCR 文本里挑出猫名。

    猫名可能是玩家自定义的，所以不强行匹配天赋库，只做去噪：
    取 2~6 个字、含汉字、且不含界面词的最长候选。

    Args:
        texts: OCR 出来的文本序列。

    Returns:
        str: 猫名；没有合格候选时返回空串。
    """
    best = ''
    for text in texts:
        text = (text or '').strip()
        if not 2 <= len(text) <= 6:
            continue
        if not any('\u4e00' <= char <= '\u9fff' for char in text):
            continue
        if any(word in text for word in NAME_NOISE):
            continue
        if len(text) > len(best):
            best = text
    return best


def parse_level(texts):
    """从一组 OCR 文本里取指挥喵等级。

    等级条在左下角，OCR 常见结果是 ``LV30`` / ``LV:30`` / ``IV:30``，
    所以优先认带 ``v``/``lv`` 的候选，其余只收「纯数字或单字母+数字」的形态，
    避免把「后勤 101」之类的属性值当成等级。

    Args:
        texts: OCR 出来的文本序列。

    Returns:
        int | None: 等级；识别不到返回 ``None``。
    """
    weak = None
    for text in texts:
        text = (text or '').strip()
        match = re.search(r'(\d{1,3})', text)
        if not match:
            continue
        value = int(match.group(1))
        if not 1 <= value <= 60:
            continue
        lowered = text.lower()
        # OCR 常把 Lv 认成 LV / IV / WV，都会带上 v
        if 'v' in lowered:
            return value
        if weak is None and re.fullmatch(r'[a-z:. ]*\d{1,3}', lowered):
            weak = value
    return weak


# ---------- 扫描用到的坐标与阈值（实机量测） ----------
# 猫窝卡片网格（实机量测）
MEOWFFICER_CATTERY_GRID = ButtonGrid(
    origin=(784, 185), delta=(130, 146), button_shape=(80, 80), grid_shape=(4, 3),
    name='MEOWFFICER_CATTERY_GRID')

# 左侧中部的空白区：主界面上是立绘背景、指挥喵页上是猫的立绘，点它都不会触发任何功能，
# 但侧边栏（聊天窗口等）会因此关闭。用于「认不出当前页面」时先收拾掉可能开着的侧栏。
# 用一个 20×20 的区域表示，点击取中心；color 不会被用到（这里不做 appear 判定）。
INERT_CLICK = (190, 350, 210, 370)
# 「陪玩」结算弹窗右下角的金色「确定」按钮（实机量测：bbox (1081,600)-(1249,654)，均色 (242,212,94)）。
# 进入指挥喵页面时、或陪玩计时到点后会弹出来，盖在页面上；
# 不点掉的话后面所有页面判断都会失败（表现为「找不到天赋页签」）。
# 这里沿用 collect.py 里 MEOWFFICER_SHIFT_DETECT 的做法：内联 Button + 颜色计数判定，
# 不需要新的模板资源。
MEOWFFICER_PLAY_CONFIRM = Button(
    area=(1081, 600, 1249, 654), color=(242, 212, 94),
    button=(1081, 600, 1249, 654), name='MEOWFFICER_PLAY_CONFIRM')
# 该区域共 168×54 像素。用严格容差统计，实测（阈值 -> 命中数）：
#   235: 陪玩结算弹窗 1663，而猫窝 10 / 主界面 2 / 聊天窗口 0
#   225: 陪玩结算弹窗 5843，猫窝 666
# 取 235 能把两侧拉开上百倍。误判的代价很大：会连点右下角，
# 触发 ALAS 的「同一按钮点击次数过多」保护，直接把任务搞崩（实测踩过）。
# 也不能照抄 collect.py 里的 threshold=30 —— 那是很宽松的相似度，几乎任何像素都算命中。
PLAY_CONFIRM_THRESHOLD = 235
PLAY_CONFIRM_COUNT = 1000
# 单次导航最多尝试关几次弹窗：连点会触发 ALAS 的点击保护，到上限就报错收手
MAX_PLAY_POPUP_TRIES = 2

# 左下角「当前显示的猫」名字与等级区域。
# 右边界刻意停在 640：再往右会和右侧天赋面板的左缘（约 690）重叠，
# 实测会把天赋名（如「不动如山」）读成猫名。
CURRENT_CAT_AREA = (100, 565, 640, 618)
# 天赋面板的完整范围（含边距）。识别天赋时只在这一块上跑 OCR：
# recognize() 会把图放大 3 倍再跑两个变体，整屏 1280×720 要 4 秒左右，
# 只取面板能省掉约 2/3 的计算量。范围要比面板稍大，别把最下面半截那行切掉。
TALENT_OCR_AREA = (686, 78, 1279, 615)
# 猫窝列表面板 / 天赋列表面板：只取面板做画面稳定性比较，避免立绘动画干扰
CATTERY_PANEL_AREA = (700, 110, 1275, 565)
TALENT_PANEL_AREA = (690, 90, 1275, 585)

# 「天赋」页签模板匹配的搜索偏移
TALENT_TAB_OFFSET = 10
# 单只猫最多滑动几次以抓全天赋
MAX_TALENT_SWIPES = 4
# 猫窝一屏可见的内容高度：3 行 × 行距 146。整屏前进才能做到「每只猫只访问一次」，
# 从而不需要按内容去重（指挥喵可以重名，按内容合并会丢猫）
CATTERY_SCREEN_HEIGHT = 438
# 猫窝单次小步滑动距离：实机滚动量约为滑动距离的 1.4~1.5 倍，
# 所以一屏要滑 3 次左右；这里按**实测位移**累加，不依赖这个倍率
CATTERY_SWIPE_STEP = 120
# 两次截图的平均像素差小于该值即认为画面已稳定
STABLE_TOLERANCE = 3.0

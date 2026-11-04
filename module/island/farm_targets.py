"""农田/果园/苗圃按作物设置补种目标。

`IslandFarm.CropTargets` 等多行文本每行一条 `作物: 目标库存`，作物名使用
`IslandFarm.INVENTORY_CONFIG` 中的英文名（如 `corn`、`chinese_cabbage`）。
列出的作物用自己的目标，未列出的作物沿用区域阈值（`MinFarm` 等）；目标为 0
表示该作物不补种。本模块不依赖设备与界面，便于离线测试，也供岛屿生产规划器写回。
"""
import re

from module.logger import logger

_LINE_SEPARATOR = re.compile(r'[\n,;，；]+')
_ENTRY = re.compile(r'^\s*([A-Za-z_ \-]+?)\s*[:：=]\s*(\d+)\s*$')


def normalize_crop_name(name):
    """统一作物名写法：小写、空格与连字符转下划线。"""
    return re.sub(r'[\s\-]+', '_', str(name).strip()).lower()


def parse_crop_targets(text, known_crops=None):
    """解析作物目标文本。

    Args:
        text (str): 形如 ``corn: 200\\nwheat: 80`` 的文本，也接受逗号/分号分隔。
        known_crops (iterable[str]): 合法作物名；给定时丢弃未知作物并记录警告。

    Returns:
        dict[str, int]: {作物名: 目标库存}。格式错误的行记录警告后跳过。
    """
    targets = {}
    if not text:
        return targets
    known = {normalize_crop_name(name) for name in known_crops} if known_crops is not None else None
    for line in _LINE_SEPARATOR.split(str(text)):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = _ENTRY.match(line)
        if not match:
            logger.warning(f'[岛屿-农田] 无法解析作物目标「{line}」，格式应为「作物: 数量」')
            continue
        crop = normalize_crop_name(match.group(1))
        if known is not None and crop not in known:
            logger.warning(f'[岛屿-农田] 未知作物「{crop}」，可用作物: {", ".join(sorted(known))}')
            continue
        targets[crop] = int(match.group(2))
    return targets


def format_crop_targets(targets):
    """把 {作物: 目标} 写回为配置文本，按作物名排序，便于比较差异。"""
    return '\n'.join(f'{crop}: {int(amount)}' for crop, amount in sorted(targets.items()))


def crop_target(crop, targets, threshold):
    """作物的补种目标：单独设置优先，否则用区域阈值。"""
    return targets.get(normalize_crop_name(crop), threshold)


def plan_crops_to_restock(inventory, targets, threshold, skip=()):
    """计算需要补种的作物列表。

    Args:
        inventory (dict[str, int]): 仓库库存 {作物: 数量}。
        targets (dict[str, int]): 单独设置的作物目标，见 parse_crop_targets。
        threshold (int): 区域阈值，未单独设置的作物使用。
        skip (iterable[str]): 本轮不考虑的作物（忽略项、非当季作物等）。

    Returns:
        list[str]: 库存低于目标的作物，按「库存/目标」升序排列，缺口比例最大的
            排最前；比例相同时库存少的在前。
    """
    skip = set(skip)
    shortages = []
    for crop, count in inventory.items():
        if crop in skip:
            continue
        target = crop_target(crop, targets, threshold)
        if target <= 0 or count >= target:
            continue
        shortages.append((count / target, count, crop))
    shortages.sort()
    return [crop for _, _, crop in shortages]

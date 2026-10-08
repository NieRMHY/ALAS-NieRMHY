"""指挥喵评分报告读取与管理模块。

将「指挥喵评分」任务产出的 JSON 报告交付给前端渲染，支持只读查询与清理。
报告由 `module/meowfficer/score_task.py` 生成于仓库根目录的 `log/meowfficer_score.json`，
按机器共享一份。
"""

import json
from pathlib import Path

from module.api.protocol import ApiError

REPORT_NAME = 'meowfficer_score.json'


def report_path(root: Path) -> Path:
    """获取指挥喵评分报告文件的完整路径。

    Args:
        root (Path): 仓库根目录。

    Returns:
        Path: 报告文件路径（log/meowfficer_score.json）。
    """
    return root / 'log' / REPORT_NAME


def report(configs, instance, limit=100):
    """读取指挥喵评分报告内容。

    Args:
        configs: 配置管理服务实例，用于实例白名单校验与仓库根定位。
        instance (str): 实例名称，仅用于校验与回显（报告本身按机器共享）。
        limit (int, optional): 最多返回的猫咪记录数量（取最新的若干只）。默认为 100。

    Returns:
        dict: 包含 instance, generatedAt, count, cats 的报告数据字典。

    Raises:
        ApiError: 报告不存在或内容损坏时抛出业务错误。
    """
    configs.path(instance)
    path = report_path(configs.root)
    if not path.is_file():
        raise ApiError('NOT_FOUND', '评分报告尚未生成，请先在「工具 → 指挥喵评分」运行一次任务')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ApiError('INTERNAL', f'评分报告无法解析：{exc}') from exc
    if not isinstance(data, dict) or not isinstance(data.get('cats'), list):
        raise ApiError('INTERNAL', '评分报告结构不正确')
    cats = [cat for cat in data['cats'] if isinstance(cat, dict)][-int(limit):]
    return {'instance': instance, 'generatedAt': str(data.get('generatedAt', '')),
            'count': len(cats), 'cats': cats}


def clear(configs, instance):
    """清空指挥喵评分报告文件。

    联动删除 json / md / html 三份生成产物，面板回到未生成状态。

    Args:
        configs: 配置管理服务实例，用于实例白名单校验与仓库根定位。
        instance (str): 实例名称，仅用于校验。

    Returns:
        dict: 包含 cleared 状态与已删除文件名列表 removed 的字典。

    Raises:
        ApiError: 文件被占用或删除失败时抛出。
    """
    configs.path(instance)
    base = report_path(configs.root)
    removed = []
    for path in (base, base.with_suffix('.md'), base.with_suffix('.html')):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ApiError('INTERNAL', f'评分报告删除失败：{exc}') from exc
        removed.append(path.name)
    return {'cleared': bool(removed), 'removed': removed}

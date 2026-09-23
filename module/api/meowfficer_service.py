"""指挥喵评分报告读取：把「指挥喵评分」任务产出的 JSON 交给前端渲染。

报告由 `module/meowfficer/score_task.py` 写在仓库根的 `log/meowfficer_score.json`，
**按机器共享一份**（任务与实例同工作目录），因此这里只做只读读取，不按实例隔离。
缺少报告属于正常情况（还没跑过任务），返回可展示的业务错误而不是 500。
"""
import json
from pathlib import Path

from module.api.protocol import ApiError

REPORT_NAME = 'meowfficer_score.json'


def report_path(root: Path) -> Path:
    """报告文件路径（仓库根 / log / meowfficer_score.json）。"""
    return root / 'log' / REPORT_NAME


def report(configs, instance, limit=100):
    """读取指挥喵评分报告。

    Args:
        configs (ConfigService): 配置服务，用于实例白名单校验与仓库根定位。
        instance (str): 实例名，仅用于校验与回显（报告本身按机器共享）。
        limit (int): 最多返回多少只猫（取最新的若干只）。

    Returns:
        dict: ``{'instance', 'generatedAt', 'count', 'cats'}``；``cats`` 元素形如
        ``{'source', 'cat', 'tags', 'talents', 'rubrics', ...}``。

    Raises:
        ApiError: 报告不存在或内容损坏时抛出可展示的业务错误。
    """
    configs.path(instance)
    path = report_path(configs.root)
    if not path.is_file():
        raise ApiError('NOT_FOUND', '评分报告尚未生成，请先在「工具Plus → 指挥喵评分」运行一次任务')
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
    """清空指挥喵评分报告。

    三份产物（json / md / html）一起删：面板回到「还没跑过任务」的空状态，
    同时避免「查看完整报告」链接指向一个已经被删掉的文件。

    Args:
        configs (ConfigService): 配置服务，用于实例白名单校验与仓库根定位。
        instance (str): 实例名，仅用于校验（报告按机器共享）。

    Returns:
        dict: ``{'cleared': bool, 'removed': [文件名, ...]}``；本来就没有报告时
        ``cleared`` 为 ``False``（重复点清空不算错误）。

    Raises:
        ApiError: 文件存在但删不掉（例如被占用）时抛出。
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

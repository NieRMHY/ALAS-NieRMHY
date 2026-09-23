"""指挥喵洗点推荐。

评分只回答「这只猫现在几档」，洗点推荐回答「要不要花物资重洗、该往哪个方向补」。
这里**不引入新的攻略结论**，只把 :mod:`module.meowfficer.score` 已经算出来的
档位 / 参考分 / 彩天赋命中 / 各口径备注组织成一条可执行的建议：

- 档位本身就写着「建议喂掉」的（`零食` / `不适合` / `无彩`）→ 不建议投入；
- 还没把任何天赋点到 3 级的 → 先补点，别急着重洗；
- 已投入但**一个彩天赋都没命中** → 洗点性价比最高；
- 其余（已有彩天赋、档位也过得去）→ 保留，洗点收益低于成本。

推荐里的「目标」直接取自主口径备注（攻略原文已经写明缺哪一项、该补什么），
所以不会出现凭空编造的攻略建议。
"""

from dataclasses import dataclass, field

from module.meowfficer.score import (LOWOIL_X, LOWOIL_Y, RESET_COST, SUB_X, SUB_Y, SURFACE_X,
                                     SURFACE_Y, TORPEDO_W, ScoreResult)

# 结论枚举：喂掉 / 先补点 / 建议洗点 / 保留
VERDICT_FEED = 'feed'
VERDICT_PENDING = 'pending'
VERDICT_REROLL = 'reroll'
VERDICT_KEEP = 'keep'

# 档位里出现这些词就说明攻略本身不建议留
_FEED_KEYWORDS = ('零食', '不适合', '无彩')

# 各口径的权重表：用来算「还缺哪些高权重天赋」。
# 和评分同源，所以推荐的目标不会和分数打架。
_RUBRIC_TABLES = {
    'surface': (SURFACE_X, SURFACE_Y),
    'submarine': (SUB_X, SUB_Y),
    'lowoil': (LOWOIL_X, LOWOIL_Y),
    'torpedo': (TORPEDO_W, {}),
}
# 最多列几条目标，太多反而没法照着做
MAX_TARGET_SPECIALS = 3
MAX_TARGET_NORMALS = 2


@dataclass
class ResetAdvice:
    """一只猫的洗点推荐。

    Attributes:
        verdict: 结论，取值见 ``VERDICT_*``。
        headline: 一句话结论，报告与面板直接显示。
        reason: 依据（引用主口径的档位与参考分）。
        cost: 重置消耗的物资；只有已知投入点数时才有值。
        cost_estimated: ``cost`` 是否由天赋等级推算而来。
        targets: 该补哪些天赋，取自主口径备注。
        label: 主口径名称，方便前端单独排版。
        score: 主口径参考分。
        tier: 主口径档位。
    """

    verdict: str
    headline: str
    reason: str
    label: str = ''
    score: int = 0
    tier: str = ''
    cost: int | None = None
    cost_estimated: bool = False
    points_spent: int = 0
    targets: list[str] = field(default_factory=list)


def estimate_points_spent(result: ScoreResult) -> int:
    """按天赋等级推算已投入的天赋点。

    游戏规则是「指挥喵每升 5 级获得 1 点天赋点」，初始天赋为 1 级，
    升到 N 级要花 ``N - 1`` 点，所以总投入约为各条天赋 ``level - 1`` 之和，上限 6。

    这是个**推算值**：扫描/截图取图时不读游戏里的「已投入点数」，
    报告里会标注「约」，仅用于给出洗点成本量级。

    Args:
        result: 评分结果。

    Returns:
        int: 推算的已投入点数（0 表示没投过点）。
    """
    spent = sum(max(0, t.level - 1) for t in result.talents)
    return max(0, min(6, spent))


def missing_targets(result: ScoreResult, key: str) -> list:
    """算出主口径下**还缺哪些高权重天赋**。

    直接复用评分用的权重表：挑出权重最高、但这只猫没有的条目。
    这样「该补什么」和「现在几分」永远一致，不会互相矛盾。

    Args:
        result: 评分结果。
        key: 主口径标识。

    Returns:
        list[str]: 可直接显示的目标描述；口径没有权重表时返回空列表。
    """
    tables = _RUBRIC_TABLES.get(key)
    if not tables:
        return []
    specials, normals = tables
    owned = {t.line for t in result.talents}

    targets = []
    missing_special = sorted((n for n in specials if n not in owned),
                             key=lambda n: -specials[n])[:MAX_TARGET_SPECIALS]
    if missing_special:
        targets.append('优先补：' + '、'.join(missing_special))
    missing_normal = sorted((n for n, w in normals.items() if n not in owned and w >= 1.0),
                            key=lambda n: -normals[n])[:MAX_TARGET_NORMALS]
    if missing_normal:
        targets.append('普通位可补：' + '、'.join(missing_normal))
    return targets


def reset_advice(result: ScoreResult) -> ResetAdvice:
    """根据评分结果给出洗点推荐。

    判断依据只有两样，都来自评分本身：**主口径档位**与**是否已经投入过天赋点**
    （``maxed`` 即有没有天赋点到 3 级）。

    - 档位本身写着建议喂掉的：没投入过就**直接喂掉**；已经投入过则**建议洗点** ——
      已经花掉的点数喂掉就一起没了，重置至少还有博一手的机会。
    - 档位过得去的：没投入过就**先补点**；已投入就**保留**。

    这里刻意**不判断「这个品种值不值得养」**：那取决于玩家自己的取舍（图鉴、代替品、
    物资余量），工具只给出成本与方向，不替玩家做这个决定。

    Args:
        result: :func:`module.meowfficer.score.evaluate` 的返回值。

    Returns:
        :class:`ResetAdvice`；没有主口径（一条天赋都没识别到）时返回 ``None``。
    """
    key = result.primary[0] if result.primary else None
    rubric = result.rubrics.get(key) if key else None
    if rubric is None:
        return None

    score, tier, label = rubric.score100, rubric.tier, rubric.label
    targets = missing_targets(result, key)
    base = f'主口径「{label}」{score}/100（{tier}）'

    # 是否已知投入点数：调用方给了就用调用方的，否则按等级推算
    if result.points_spent in RESET_COST:
        spent, estimated = result.points_spent, False
    else:
        spent, estimated = estimate_points_spent(result), True
    cost = RESET_COST.get(spent) if spent else None

    bad_tier = any(word in tier for word in _FEED_KEYWORDS)
    if bad_tier and not result.maxed:
        advice = ResetAdvice(
            verdict=VERDICT_FEED,
            headline='不建议投入，直接喂掉',
            reason=f'{base}，攻略口径本身就归到建议喂掉的一档；'
                   '而且还没投过天赋点，重置救不回来什么，留位置不如喂给目标猫换经验',
            targets=targets)
    elif bad_tier:
        advice = ResetAdvice(
            verdict=VERDICT_REROLL,
            headline='建议洗点，别直接喂',
            reason=f'{base}。已经投入过 {spent} 点天赋，直接喂掉这些投入就一起没了；'
                   '重置只回到初始天赋、后天天赋会全部消失，属于花物资博一手 ——'
                   '想继续留用就先重置按下面方向重点，不想留再喂也不迟',
            targets=targets)
    elif not result.maxed:
        advice = ResetAdvice(
            verdict=VERDICT_PENDING,
            headline='先按目标补点，暂时不用洗',
            reason=f'{base}，且没有任何天赋点到 3 级，说明还没投过点。'
                   '先把点数补到下面这些方向上，等真要重洗再谈成本',
            targets=targets)
    else:
        rainbow = f'{rubric.x} 个彩天赋、' if rubric.key != 'torpedo' else ''
        advice = ResetAdvice(
            verdict=VERDICT_KEEP,
            headline='保留即可，没必要洗',
            reason=f'{base}，已经有{rainbow}档位也够用，'
                   '洗点的期望收益低于重洗成本',
            targets=targets)

    advice.label, advice.score, advice.tier = label, score, tier
    advice.cost, advice.cost_estimated = cost, (estimated and cost is not None)
    advice.points_spent = spent
    # 只有「先补点」「建议洗点」两种结论才需要照着补天赋；
    # 保留/喂掉还给「优先补某某」会自相矛盾
    if advice.verdict not in (VERDICT_PENDING, VERDICT_REROLL):
        advice.targets = []
    return advice

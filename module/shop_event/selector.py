"""
活动商店商品过滤选择器。

通过正则表达式定义商品分类过滤规则，支持按大类（装备/舰船/PT 等）、
子类（SSR/SR 等）和层级（S1-S8/T1-T6）三级筛选。
提供 Filter 实例用于匹配商品名称，并支持可选的数量后缀解析
（如 "Cube:5" 表示购买 5 个心智魔方）。

Pages: in: EVENT_SHOP
"""
import re

from module.base.filter import Filter

FILTER_REGEX = re.compile(
    '^(ship|equip|pt|gachaticket'
    '|meta|skinbox'
    '|array|chip|cat|pr|dr'
    '|augment'
    '|cube|medal|expbook'
    '|box|plate|coin|oil|food'
    ')'

    '(ur|ssr'
    '|core|change|enhance'
    '|general|gun|torpedo|antiair|plane)?'

    '(s[1-9]|t[1-6])?$'
)
FILTER_ATTR = ('group', 'sub_genre', 'tier')
FILTER = Filter(FILTER_REGEX, FILTER_ATTR)


def parse_filter_amount(filter_string):
    """从活动商店过滤器字符串中解析可选的数量后缀。

    示例：
        Cube:5 > Oil:2 -> {'cube': 5, 'oil': 2}
        EquipSSR > Cube -> {}

    Args:
        filter_string (str): 过滤器配置字符串。

    Returns:
        dict[str, int]: 标准化物品名称与对应购买数量的字典。
    """
    out = {}
    for part in str(filter_string).split('>'):
        part = part.strip()
        if ':' not in part:
            continue
        name, amount = part.rsplit(':', 1)
        name = name.strip()
        try:
            amount = int(amount.strip())
        except ValueError:
            continue
        if amount <= 0:
            continue
        result = FILTER_REGEX.search(name.replace(' ', '').lower())
        if result is None:
            continue
        normalized = ''.join(value or '' for value in result.groups())
        out[normalized] = amount
    return out


def strip_filter_amount(filter_string):
    """移除过滤器中的数量后缀，以便传递给基础 Filter 进行正则匹配。

    Args:
        filter_string (str): 带有数量后缀的过滤器字符串。

    Returns:
        str: 剥离数量后缀后的标准过滤器字符串。
    """
    out = []
    for part in str(filter_string).split('>'):
        part = part.strip()
        if ':' in part:
            name, amount = part.rsplit(':', 1)
            try:
                int(amount.strip())
                part = name.strip()
            except ValueError:
                pass
        out.append(part)
    return ' > '.join(out)


def parse_filter_tokens(filter_string):
    """将过滤器字符串解析为有序的标记字典列表。

    Args:
        filter_string (str): 待解析的过滤器字符串。

    Returns:
        list[dict]: 每个字典包含：
            - 'raw' (str): 原始片段文本；
            - 'name' (str): 物品名称；
            - 'amount' (int | None): 指定购买数量，无后缀为 None；
            - 'key' (str | None): 归一化的正则匹配键名。
    """
    out = []
    for part in str(filter_string).split('>'):
        raw = part.strip()
        if not raw:
            continue
        token = {'raw': raw, 'name': raw, 'amount': None, 'key': None}
        if ':' in raw:
            name, amount = raw.rsplit(':', 1)
            name = name.strip()
            try:
                amount = int(amount.strip())
            except ValueError:
                amount = None
            else:
                token['name'] = name
                token['amount'] = amount
                result = FILTER_REGEX.search(name.replace(' ', '').lower())
                if result is not None:
                    token['key'] = ''.join(value or '' for value in result.groups())
        out.append(token)
    return out


def rebuild_filter_tokens(tokens):
    """根据标记列表重新组装过滤器字符串。

    数量小于等于 0 的标记将被自动剔除。

    Args:
        tokens (list[dict]): 标记字典列表。

    Returns:
        str: 组装后的过滤器字符串。
    """
    parts = []
    for token in tokens:
        amount = token.get('amount')
        name = token.get('name', '').strip()
        if not name:
            continue
        if amount is None:
            parts.append(name)
            continue
        if amount > 0:
            parts.append(f'{name}:{amount}')
    return ' > '.join(parts)


EVENT_SHOP_PRESET_FILTER = {
    'all': """
        EquipUR > EquipSSR > Cube > GachaTicket
        > Array > Chip > CatT3 
        > Meta > SkinBox
        > Oil > Coin > Medal > ExpBookT1 > FoodT1
        > DR > PR
        > AugmentCore > AugmentEnhanceT2 > AugmentChangeT2 > AugmentChangeT1
        > CatT2 > CatT1 > PlateGeneralT3 > PlateT3 > BoxT4
        > ShipSSR
    """,
}

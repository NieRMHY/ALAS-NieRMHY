"""
活动商店商品过滤选择器。

通过正则表达式定义商品分类过滤规则，支持按大类（装备/舰船/PT 等）、
子类（SSR/SR 等）和层级（S1-S9/T1-T6）三级筛选。
提供 Filter 实例用于匹配商品名称，按优先级选择购买商品。

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
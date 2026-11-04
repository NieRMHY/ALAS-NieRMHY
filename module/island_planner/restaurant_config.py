"""餐厅档次与服务员加成数据。

移植自 AzurLaneAutoScript（LmeSzinc/AzurLaneAutoScript，GPL-3.0）的
module/island_handler/restaurant_config.py，去掉了读取 ALAS 配置的函数；
AzurPilot 侧的档次与服务员由 module/island_planner/settings_map.py 从配置换算后传入。
餐厅编号：601 有鱼餐馆、602 白熊饮品、603 啾啾简餐、604 烧烤店、901 啾咖啡。
"""

from collections import OrderedDict

from module.exception import RequestHumanTakeover
from module.logger import logger


WAITRESS_NONE = 'none'
WAITRESS_ANY = 'any'


# Keep the option/bonus data in one place.  ``waitress_effects`` values are
# ``(capacity_delta, sales_bonus)`` and bonuses are only applied for explicitly
# selected named waitresses, matching the previous behaviour.
RESTAURANT_CONFIG = OrderedDict({
    601: {
        'name': 'Koi',
        'waitress_options': ('Chao_Ho', 'Chang_Feng'),
        'waitress_effects': {
            'Chao_Ho': (1, 0.10),
            'Chang_Feng': (1, 0),
        },
    },
    602: {
        'name': 'Bear',
        'waitress_options': ('Cheshire', 'Chang_Feng'),
        'waitress_effects': {
            'Cheshire': (1, 0.05),
            'Chang_Feng': (1, 0),
        },
    },
    603: {
        'name': 'Eatery',
        'waitress_options': ('Helena', 'Prinz_Eugen', 'Chang_Feng'),
        'waitress_effects': {
            'Helena': (1, 0.10),
            'Prinz_Eugen': (0, 0.10),
            'Chang_Feng': (1, 0),
        },
    },
    604: {
        'name': 'Grill',
        'waitress_options': ('August_von_Parseval', 'Prinz_Eugen', 'Chang_Feng'),
        'waitress_effects': {
            'August_von_Parseval': (1, 0.10),
            'Prinz_Eugen': (0, 0.10),
            'Chang_Feng': (1, 0),
        },
    },
    901: {
        'name': 'Cafe',
        'waitress_options': ('Cheshire', 'Belfast', 'Chang_Feng'),
        'waitress_effects': {
            'Cheshire': (1, 0.05),
            'Belfast': (0, 0.10),
            'Chang_Feng': (1, 0),
        },
    },
})

RESTAURANT_IDS = tuple(RESTAURANT_CONFIG.keys())
def get_restaurant_config(restaurant_id):
    return RESTAURANT_CONFIG[restaurant_id]


def get_waitress_options(restaurant_id):
    return (WAITRESS_NONE, WAITRESS_ANY) + tuple(
        get_restaurant_config(restaurant_id)['waitress_options']
    )


def _waitress_sort_key(restaurant_id, value):
    config = get_restaurant_config(restaurant_id)
    if value == WAITRESS_NONE:
        return (2, 0)
    if value == WAITRESS_ANY:
        return (1, 0)
    try:
        index = config['waitress_options'].index(value)
    except ValueError:
        index = len(config['waitress_options'])
    return (0, index)


def normalize_waitress_slots(restaurant_id, values):
    """Validate and return a canonical, unordered pair of waitress values.

    Slot order is canonicalized because the two slots are unordered. Invalid
    combinations are not repaired: they require human intervention.
    """
    allowed = set(get_waitress_options(restaurant_id))
    values = list(values or [])
    cleaned = []
    seen_named = set()
    for value in values:
        if value is None:
            value = WAITRESS_NONE
        if value not in allowed:
            message = f'Invalid waitress value for restaurant {restaurant_id}: {value}'
            logger.error(message)
            raise RequestHumanTakeover(message)
        if value not in (WAITRESS_NONE, WAITRESS_ANY):
            if value in seen_named:
                message = f'Duplicate named waitress for restaurant {restaurant_id}: {value}'
                logger.error(message)
                raise RequestHumanTakeover(message)
            seen_named.add(value)
        cleaned.append(value)

    if len(cleaned) > 2:
        message = f'Restaurant {restaurant_id} has more than two waitress slots'
        logger.error(message)
        raise RequestHumanTakeover(message)

    cleaned.sort(key=lambda value: _waitress_sort_key(restaurant_id, value))
    cleaned.extend([WAITRESS_NONE] * (2 - len(cleaned)))
    return tuple(cleaned)


def is_restaurant_enabled(slots):
    return any(value != WAITRESS_NONE for value in slots)


def get_selected_named_waitresses(slots):
    return {
        value for value in slots
        if value not in (WAITRESS_NONE, WAITRESS_ANY)
    }


def get_waitress_effect(restaurant_id, slots):
    slots = normalize_waitress_slots(restaurant_id, slots)
    capacity_delta = 0
    sales_bonus = 0
    effects = get_restaurant_config(restaurant_id)['waitress_effects']
    for waitress in get_selected_named_waitresses(slots):
        capacity, sales = effects.get(waitress, (0, 0))
        capacity_delta += capacity
        sales_bonus += sales
    return capacity_delta, sales_bonus


def get_initial_capacity_from_grade(grade):
    if grade == 'bronze':
        return 5
    elif grade in ['silver', 'gold', 'diamond']:
        return 6
    else:
        raise ValueError(f"Invalid grade: {grade}")

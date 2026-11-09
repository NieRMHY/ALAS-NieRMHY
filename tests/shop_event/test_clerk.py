from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from module.shop_event.clerk import EventShopClerk, ItemNotFoundError


def make_clerk(counter_results):
    scanner = SimpleNamespace(grids=None, items=[])
    results = iter(counter_results)

    def predict(*args, **kwargs):
        counters = next(results)
        if isinstance(counters[0], int):
            counters = [counters]
        scanner.items = [SimpleNamespace(
            count=count,
            total_count=total_count,
            button=(0, 100, 1, 101),
        ) for count, total_count in counters]

    scanner.predict = Mock(side_effect=predict)
    scanner.extract_template = Mock()
    grid = Mock()
    grid.__getitem__ = Mock(return_value=SimpleNamespace(area=(0, 100, 1, 101)))
    clerk = SimpleNamespace(
        ensure_no_info_bar=Mock(),
        event_shop_items=scanner,
        _get_event_shop_grid=Mock(return_value=grid),
        config=SimpleNamespace(SHOP_EXTRACT_TEMPLATE=False),
        device=SimpleNamespace(image=object(), screenshot=Mock()),
    )
    return clerk, scanner


def test_event_shop_get_items_does_not_reshoot_valid_scan():
    clerk, scanner = make_clerk([(1, 1)])

    EventShopClerk.event_shop_get_items(clerk)

    assert scanner.predict.call_count == 1
    clerk.device.screenshot.assert_not_called()


def test_event_shop_get_items_reshoots_invalid_counter():
    clerk, scanner = make_clerk([(0, 0), (1, 1)])

    items = EventShopClerk.event_shop_get_items(clerk)

    assert (items[0].count, items[0].total_count) == (1, 1)
    assert scanner.predict.call_count == 2
    clerk.device.screenshot.assert_called_once_with()


def test_event_shop_get_items_rejects_persistent_invalid_counter():
    clerk, scanner = make_clerk([(0, 0), (0, 0), (0, 0)])

    with pytest.raises(ItemNotFoundError):
        EventShopClerk.event_shop_get_items(clerk)

    assert scanner.predict.call_count == 3
    assert clerk.device.screenshot.call_count == 2


def test_event_shop_get_items_skips_persistent_invalid_minority():
    # 部分格子持续读不出库存时跳过它们，保留其余商品，不再抛错触发重载
    clerk, scanner = make_clerk([[(5, 5), (0, 0)]] * 3)

    items = EventShopClerk.event_shop_get_items(clerk)

    assert [(item.count, item.total_count) for item in items] == [(5, 5)]
    assert scanner.items == items
    assert scanner.predict.call_count == 3

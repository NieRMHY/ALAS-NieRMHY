"""Exercise the current separate daily/overflow purchase paths without a game device.

The retired combined `_meow_get_buy_count` helper is no longer a runtime contract.
These tests assert the actual UI quantity and confirmation calls instead.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from module.meowfficer.buy import MeowfficerBuy


@pytest.mark.parametrize('bought,coins,target,expected', [
    (0, 100000, 3, 3), (5, 100000, 3, None), (15, 100000, 15, None),
    (0, 500, 3, 1), (1, 500, 3, None), (0, 2500, 5, 2),
    (2, 2500, 5, 1), (0, 0, 1, 1), (1, 0, 2, None),
    (14, 1500, 15, 1), (2, 100000, 5, 3),
])
def test_daily_purchase_uses_remaining_target_and_affordability(bought, coins, target, expected):
    actor = SimpleNamespace(device=SimpleNamespace(image=None), meow_enter=Mock(), ui_ensure_index=Mock())
    with patch('module.meowfficer.buy.MEOWFFICER.ocr', return_value=(15-bought, bought, 15)), \
            patch('module.meowfficer.buy.MEOWFFICER_COINS.ocr', return_value=coins):
        result = MeowfficerBuy.meow_choose(actor, target)
    if expected is None:
        assert result is False
        actor.meow_enter.assert_not_called()
        actor.ui_ensure_index.assert_not_called()
    else:
        assert result is True
        actor.ui_ensure_index.assert_called_once()
        assert actor.ui_ensure_index.call_args.args == (expected,)


@pytest.mark.parametrize('bought,coins,threshold,expected_target', [
    (0, 50000, 50000, None), (0, 40000, 50000, None), (15, 100000, 50000, None),
    (0, 50500, 50000, 1), (0, 53000, 50000, 2), (0, 100000, 50000, 15),
    (5, 53000, 50000, 7), (14, 100000, 50000, 15),
    (1, 1499, 0, None), (0, 0, 0, None), (1, 1500, 0, 2),
    (0, 500, 0, 1), (1, 3000, 0, 3), (16, 100000, 0, None),
])
def test_overflow_purchase_preserves_current_limit_and_confirmation(bought, coins, threshold, expected_target):
    actor = SimpleNamespace(device=SimpleNamespace(image=None),
                            meow_choose=Mock(return_value=True), meow_confirm=Mock())
    with patch('module.meowfficer.buy.MEOWFFICER.ocr', return_value=(15-bought, bought, 15)), \
            patch('module.meowfficer.buy.MEOWFFICER_COINS.ocr', return_value=coins):
        MeowfficerBuy.meow_overflow_buy(actor, threshold)
    if expected_target is None:
        actor.meow_choose.assert_not_called()
        actor.meow_confirm.assert_not_called()
    else:
        actor.meow_choose.assert_called_once_with(count=expected_target)
        actor.meow_confirm.assert_called_once()


def test_overflow_does_not_confirm_when_quantity_selection_fails():
    actor = SimpleNamespace(device=SimpleNamespace(image=None),
                            meow_choose=Mock(return_value=False), meow_confirm=Mock())
    with patch('module.meowfficer.buy.MEOWFFICER.ocr', return_value=(10, 5, 15)), \
            patch('module.meowfficer.buy.MEOWFFICER_COINS.ocr', return_value=53000):
        MeowfficerBuy.meow_overflow_buy(actor, 50000)
    actor.meow_choose.assert_called_once_with(count=7)
    actor.meow_confirm.assert_not_called()


@pytest.mark.parametrize('results,expected_confirmations,success', [
    ([False], 0, True), ([True, False], 1, True), ([True, True, True], 3, False),
])
def test_daily_retry_limit(results, expected_confirmations, success):
    actor = SimpleNamespace(config=SimpleNamespace(Meowfficer_BuyAmount=3),
                            meow_choose=Mock(side_effect=results), meow_confirm=Mock())
    assert MeowfficerBuy.meow_buy(actor) is success
    assert actor.meow_confirm.call_count == expected_confirmations

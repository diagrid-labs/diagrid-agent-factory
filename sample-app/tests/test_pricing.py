import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pricing import (  # noqa: E402
    Position,
    Quote,
    margin_required,
    pip_value,
    position_pnl,
    spread_in_pips,
)


def test_mid():
    assert Quote("EURUSD", 1.1000, 1.1002).mid == 1.1001


def test_spread_in_pips_eurusd():
    assert spread_in_pips(Quote("EURUSD", 1.10000, 1.10012)) == 1.2


def test_pip_value_eurusd():
    assert pip_value("EURUSD", 100_000, 1.1) == 10.0


def test_long_position_pnl():
    pos = Position("EURUSD", "buy", 10_000, 1.1000)
    assert position_pnl(pos, Quote("EURUSD", 1.1050, 1.1052)) == 50.0


def test_margin_required():
    assert margin_required(100_000, 1.1, 30) == 3666.67


def test_margin_required_zero_units():
    assert margin_required(0, 1.1, 20) == 0.0


@pytest.mark.parametrize("leverage", [0, -5])
def test_margin_required_bad_leverage(leverage):
    with pytest.raises(ValueError):
        margin_required(1000, 1.1, leverage)


def test_margin_required_negative_units():
    with pytest.raises(ValueError):
        margin_required(-1, 1.1, 10)


def test_margin_required_negative_price():
    with pytest.raises(ValueError):
        margin_required(1000, -1.1, 10)

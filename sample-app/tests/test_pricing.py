import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pricing import Position, Quote, mid_price, pip_value, position_pnl, spread_in_pips  # noqa: E402


def test_mid():
    assert Quote("EURUSD", 1.1000, 1.1002).mid == 1.1001


def test_mid_price_rounds_to_5_decimals():
    assert mid_price(Quote("EURUSD", 1.100001, 1.100022)) == 1.10001


def test_mid_price_jpy_rounds_to_3_decimals():
    assert mid_price(Quote("USDJPY", 150.1234, 150.1256)) == 150.125


def test_spread_in_pips_eurusd():
    assert spread_in_pips(Quote("EURUSD", 1.10000, 1.10012)) == 1.2


def test_pip_value_eurusd():
    assert pip_value("EURUSD", 100_000, 1.1) == 10.0


def test_long_position_pnl():
    pos = Position("EURUSD", "buy", 10_000, 1.1000)
    assert position_pnl(pos, Quote("EURUSD", 1.1050, 1.1052)) == 50.0

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pricing import Position, Quote, pip_value, position_pnl, spread_in_pips  # noqa: E402


def test_mid():
    assert Quote("EURUSD", 1.1000, 1.1002).mid == 1.1001


def test_spread_in_pips_eurusd():
    assert spread_in_pips(Quote("EURUSD", 1.10000, 1.10012)) == 1.2


def test_pip_value_eurusd():
    assert pip_value("EURUSD", 100_000, 1.1) == 10.0


def test_long_position_pnl():
    pos = Position("EURUSD", "buy", 10_000, 1.1000)
    assert position_pnl(pos, Quote("EURUSD", 1.1050, 1.1052)) == 50.0


def test_spread_in_pips_usdjpy():
    # Spread is (150.115 - 150.100) = 0.015, pip size is 0.01, so 1.5 pips.
    assert spread_in_pips(Quote("USDJPY", 150.100, 150.115)) == 1.5


def test_pip_value_usdjpy():
    # For 100,000 units, pip size is 0.01, pip value is 100000 * 0.01 = 1,000
    assert pip_value("USDJPY", 100_000, 150.10) == 1000.0


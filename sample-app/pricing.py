"""FX pricing helpers: spreads, pip values and position P&L."""

from __future__ import annotations

from dataclasses import dataclass

PIP_SIZE = 0.0001


def pip_size_for_pair(pair: str) -> float:
    """Return appropriate pip size according to currency pair (0.01 for JPY quote, else 0.0001)"""
    return 0.01 if pair[-3:] == "JPY" else 0.0001

@dataclass(frozen=True)
class Quote:
    pair: str  # for example "EURUSD"
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass(frozen=True)
class Position:
    pair: str
    side: str  # "buy" or "sell"
    units: float
    open_price: float


def spread_in_pips(quote: Quote) -> float:
    """The quote's spread in pips."""
    pip_size = pip_size_for_pair(quote.pair)
    return round((quote.ask - quote.bid) / pip_size, 1)


def pip_value(pair: str, units: float, price: float) -> float:
    """Value of one pip, in the quote currency, for a position of `units`."""
    pip_size = pip_size_for_pair(pair)
    return units * pip_size


def position_pnl(position: Position, quote: Quote) -> float:
    """Unrealised profit or loss in the quote currency, closing at the current quote."""
    close = quote.bid if position.side == "buy" else quote.ask
    return round((close - position.open_price) * position.units, 2)

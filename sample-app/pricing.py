"""FX pricing helpers: spreads, pip values and position P&L."""

from __future__ import annotations

from dataclasses import dataclass

PIP_SIZE = 0.0001


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
    return round((quote.ask - quote.bid) / PIP_SIZE, 1)


def pip_value(pair: str, units: float, price: float) -> float:
    """Value of one pip, in the quote currency, for a position of `units`."""
    return units * PIP_SIZE


def position_pnl(position: Position, quote: Quote) -> float:
    """Unrealised profit or loss in the quote currency, closing at the current quote."""
    if position.side == "buy":
        diff = quote.bid - position.open_price
    else:
        diff = position.open_price - quote.ask
    return round(diff * position.units, 2)

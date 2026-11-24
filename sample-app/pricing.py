"""FX pricing helpers: spreads, pip values and position P&L."""

from __future__ import annotations

from dataclasses import dataclass

PIP_SIZE = 0.0001
JPY_PIP_SIZE = 0.01


def pip_size(pair: str) -> float:
    """Pip size for a pair: 0.01 when the quote currency is JPY, else 0.0001."""
    return JPY_PIP_SIZE if pair[-3:].upper() == "JPY" else PIP_SIZE


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
    return round((quote.ask - quote.bid) / pip_size(quote.pair), 1)


def pip_value(pair: str, units: float, price: float) -> float:
    """Value of one pip, in the quote currency, for a position of `units`."""
    return units * pip_size(pair)


def position_pnl(position: Position, quote: Quote) -> float:
    """Unrealised profit or loss in the quote currency, closing at the current quote."""
    close = quote.bid if position.side == "buy" else quote.ask
    return round((close - position.open_price) * position.units, 2)

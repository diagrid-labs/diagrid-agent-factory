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
    close = quote.bid if position.side == "buy" else quote.ask
    return round((close - position.open_price) * position.units, 2)


def margin_required(units: float, price: float, leverage: float) -> float:
    """Return margin required for a position: units * price / leverage, rounded to 2 decimals.
    - leverage must be > 0
    - units and price must be >= 0
    """
    if leverage <= 0:
        raise ValueError("leverage must be > 0")
    if units < 0 or price < 0:
        raise ValueError("units and price must not be negative")
    margin = units * price / leverage
    return round(margin, 2)

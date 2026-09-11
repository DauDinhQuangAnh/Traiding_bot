"""Deterministic in-memory adapters for tests and replay."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from trading_bot.application.dtos import AccountSnapshot, BalanceSnapshot, ExternalPosition
from trading_bot.domain.enums import HealthStatus, Timeframe
from trading_bot.domain.market_models import Candle
from trading_bot.domain.value_objects import ComponentHealth, CostRateEstimate, Quote


@dataclass(slots=True)
class FrozenClock:
    current: datetime
    elapsed: timedelta = timedelta(0)

    def now_utc(self) -> datetime:
        return self.current

    def monotonic(self) -> timedelta:
        return self.elapsed

    def advance(self, duration: timedelta) -> None:
        self.current += duration
        self.elapsed += duration


@dataclass(slots=True)
class InMemoryMarketDataProvider:
    candles: dict[tuple[str, Timeframe], tuple[Candle, ...]] = field(default_factory=dict)
    quotes: dict[str, Quote] = field(default_factory=dict)
    observed_at: datetime | None = None

    def fetch_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime, limit: int
    ) -> tuple[Candle, ...]:
        values = self.candles.get((symbol, timeframe), ())
        return tuple(
            candle for candle in values if candle.open_time >= start and candle.close_time <= end
        )[-limit:]

    def fetch_latest_quote(self, symbol: str) -> Quote:
        return self.quotes[symbol]

    def health(self) -> ComponentHealth:
        if self.observed_at is None:
            raise RuntimeError("fake provider needs observed_at")
        return ComponentHealth("market_data", HealthStatus.HEALTHY, self.observed_at, ())


@dataclass(frozen=True, slots=True)
class StaticFeeModel:
    rates: CostRateEstimate

    def estimate(self, symbol: str, as_of: datetime) -> CostRateEstimate:
        del symbol, as_of
        return self.rates


@dataclass(slots=True)
class InMemoryAccountProvider:
    accounts: dict[str, AccountSnapshot] = field(default_factory=dict)
    balances: dict[str, BalanceSnapshot] = field(default_factory=dict)
    positions: tuple[ExternalPosition, ...] = ()
    observed_at: datetime | None = None

    def get_account_snapshot(self, account_id: str) -> AccountSnapshot:
        return self.accounts[account_id]

    def get_positions(self, symbol: str | None = None) -> tuple[ExternalPosition, ...]:
        if symbol is None:
            return self.positions
        return tuple(position for position in self.positions if position.symbol == symbol)

    def get_balance(self, currency: str) -> BalanceSnapshot:
        return self.balances[currency]

    def health(self) -> ComponentHealth:
        if self.observed_at is None:
            raise RuntimeError("fake provider needs observed_at")
        return ComponentHealth("account", HealthStatus.HEALTHY, self.observed_at, ())

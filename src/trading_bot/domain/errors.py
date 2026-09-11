"""Small typed error hierarchy for invalid data and system boundaries."""


class TradingBotError(Exception):
    """Base class for unexpected or invalid conditions."""


class DomainValidationError(TradingBotError, ValueError):
    """A canonical domain object violates its construction invariants."""


class ConfigurationError(TradingBotError, ValueError):
    """Configuration is missing, unknown or internally inconsistent."""


class MarketDataValidationError(TradingBotError, ValueError):
    """Market data cannot enter the normalized closed-candle pipeline."""


class IndicatorCalculationError(TradingBotError, ArithmeticError):
    """An indicator cannot be calculated without violating its contract."""


class StateTransitionError(TradingBotError):
    """A state/event pair is not present in the approved transition table."""


class PersistenceError(TradingBotError):
    """A local append-only persistence operation failed."""


class HistoricalDataError(TradingBotError):
    """A historical ingestion or repository boundary failed."""


class HistoricalParserError(HistoricalDataError):
    """A raw historical file is unreadable or has an invalid schema."""

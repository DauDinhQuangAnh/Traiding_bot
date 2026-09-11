from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from trading_bot.config.loader import app_config_from_mapping, config_version, load_config
from trading_bot.domain.errors import ConfigurationError


def test_example_config_loads_and_hash_is_stable():
    first = load_config(Path("config/base.example.yaml"))
    second = load_config(Path("config/base.example.yaml"))
    assert first.market.symbol == "BTC-USDT-SWAP"
    assert first.risk.risk_per_trade == Decimal("0.01")
    assert config_version(first) == config_version(second)


def test_unknown_key_is_rejected():
    raw = yaml.safe_load(Path("config/base.example.yaml").read_text(encoding="utf-8"))
    raw["market"]["surprise"] = True
    with pytest.raises(ConfigurationError, match="unknown"):
        app_config_from_mapping(raw)


def test_yaml_float_for_decimal_is_rejected():
    raw = yaml.safe_load(Path("config/base.example.yaml").read_text(encoding="utf-8"))
    raw = deepcopy(raw)
    raw["risk"]["risk_per_trade"] = 0.01
    with pytest.raises(ConfigurationError, match="lossy"):
        app_config_from_mapping(raw)


def test_historical_config_rejects_unknown_key_and_invalid_enum():
    base = yaml.safe_load(Path("config/base.example.yaml").read_text(encoding="utf-8"))
    unknown = deepcopy(base)
    unknown["historical"]["surprise"] = True
    with pytest.raises(ConfigurationError, match="unknown"):
        app_config_from_mapping(unknown)

    invalid = deepcopy(base)
    invalid["historical"]["timestamp_unit"] = "GUESS"
    with pytest.raises(ConfigurationError, match="invalid enum"):
        app_config_from_mapping(invalid)


def test_backtest_config_rejects_unknown_key_float_and_unsafe_policy():
    base = yaml.safe_load(Path("config/base.example.yaml").read_text(encoding="utf-8"))
    unknown = deepcopy(base)
    unknown["backtest"]["surprise"] = True
    with pytest.raises(ConfigurationError, match="unknown"):
        app_config_from_mapping(unknown)

    lossy = deepcopy(base)
    lossy["backtest"]["modeled_spread_rate"] = 0.0002
    with pytest.raises(ConfigurationError, match="lossy"):
        app_config_from_mapping(lossy)

    unsafe = deepcopy(base)
    unsafe["backtest"]["intrabar_ambiguity_policy"] = "OPTIMISTIC"
    with pytest.raises(ConfigurationError, match="invalid enum"):
        app_config_from_mapping(unsafe)

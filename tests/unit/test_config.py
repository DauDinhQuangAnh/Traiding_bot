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

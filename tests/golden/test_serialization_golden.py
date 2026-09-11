from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import canonical_json
from trading_bot.domain.value_objects import VersionSet


def test_version_set_canonical_golden():
    value = VersionSet("code-v1", "strategy-v1", "config-v1", "data-v1")
    assert canonical_json(value) == (
        '{"code_version":"code-v1","config_version":"config-v1",'
        '"data_version":"data-v1","strategy_version":"strategy-v1"}'
    )
    assert deterministic_id("golden", value) == (
        "0a9714aafeb4ab5a11430f0f2976beb51f3840466a0e16a039de7090c4b23d96"
    )

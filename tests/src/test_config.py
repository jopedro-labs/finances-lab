"""Unit tests for src/config.py covering Settings environment parsing,
default values, backwards compatibility aliases, and strategy dataclass weight
validations.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.config import (
    DEFAULT_DIP_CONFIG,
    DEFAULT_ETF_CACHE_TTL_DAYS,
    GDRIVE_CONFIG_FOLDER_ID,
    GDRIVE_SNAPSHOT_FOLDER_ID,
    DipDetectorConfig,
    EtfStrategyConfig,
    Settings,
    StockStrategyConfig,
)


def test_settings_default_values() -> None:
    """Validates that default Settings instance contains expected fallback values."""
    with patch.dict("os.environ", clear=True):
        s: Settings = Settings(_env_file=None)

    assert s.gemini_model == "gemini-3.6-flash"
    assert s.discord_test_mode is False
    assert s.etf_cache_ttl_days == 30
    assert s.min_drop_pct == 5.0
    assert s.max_drop_pct == 10.0
    assert s.lookback_days == 30


def test_settings_environment_override() -> None:
    """Validates environment variables override Settings defaults."""
    env_vars: dict[str, str] = {
        "GEMINI_API_KEY": "test_key_123",
        "GEMINI_MODEL": "gemini-1.5-pro",
        "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test",
        "DISCORD_TEST_MODE": "true",
        "SMTP_PORT": "2525",
        "MIN_DROP_PCT": "7.5",
        "GDRIVE_CONFIG_FOLDER_ID": "folder_abc_123",
    }

    with patch.dict("os.environ", env_vars, clear=True):
        s: Settings = Settings(_env_file=None)
        assert s.gemini_api_key.get_secret_value() == "test_key_123"
        assert s.gemini_model == "gemini-1.5-pro"
        assert (
            s.discord_webhook_url.get_secret_value()
            == "https://discord.com/api/webhooks/test"
        )
        assert s.discord_test_mode is True
        assert s.smtp_port == 2525
        assert s.min_drop_pct == 7.5
        assert s.gdrive_config_folder_id == "folder_abc_123"


def test_backwards_compatibility_aliases() -> None:
    """Validates legacy alias constants exported at module level."""
    assert isinstance(DEFAULT_ETF_CACHE_TTL_DAYS, int)
    assert GDRIVE_CONFIG_FOLDER_ID is None or isinstance(GDRIVE_CONFIG_FOLDER_ID, str)
    assert GDRIVE_SNAPSHOT_FOLDER_ID is None or isinstance(
        GDRIVE_SNAPSHOT_FOLDER_ID, str
    )


def test_dip_detector_config_defaults() -> None:
    """Validates default DipDetectorConfig initialization."""
    config: DipDetectorConfig = DipDetectorConfig()
    assert config.min_drop_pct == DEFAULT_DIP_CONFIG.min_drop_pct
    assert config.max_drop_pct == DEFAULT_DIP_CONFIG.max_drop_pct
    assert config.lookback_days == DEFAULT_DIP_CONFIG.lookback_days


def test_stock_strategy_config_weights_valid() -> None:
    """Validates valid StockStrategyConfig weights sum to 1.0."""
    config: StockStrategyConfig = StockStrategyConfig(
        weight_dip=0.25,
        weight_forward_pe=0.25,
        weight_52w_range=0.25,
        weight_allocation=0.25,
    )
    assert config.weight_dip == 0.25


def test_stock_strategy_config_weights_invalid_raises_value_error() -> None:
    """Validates invalid StockStrategyConfig weights sum raises ValueError."""
    with pytest.raises(
        ValueError, match="Stock strategy weights must sum to 1.0, got 0.8"
    ):
        StockStrategyConfig(
            weight_dip=0.20,
            weight_forward_pe=0.20,
            weight_52w_range=0.20,
            weight_allocation=0.20,
        )


def test_etf_strategy_config_weights_valid() -> None:
    """Validates valid EtfStrategyConfig weights sum to 1.0."""
    config: EtfStrategyConfig = EtfStrategyConfig(
        weight_dip=0.50,
        weight_ter=0.20,
        weight_allocation=0.30,
    )
    assert config.weight_dip == 0.50


def test_etf_strategy_config_weights_invalid_raises_value_error() -> None:
    """Validates invalid EtfStrategyConfig weights sum raises ValueError."""
    with pytest.raises(
        ValueError, match="ETF strategy weights must sum to 1.0, got 0.9"
    ):
        EtfStrategyConfig(
            weight_dip=0.30,
            weight_ter=0.30,
            weight_allocation=0.30,
        )

"""Global configuration module loading environment variables via
Pydantic Settings and defining strategy parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic.types import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base Paths
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR / "data"
PLOTS_DIR: Path = DATA_DIR / "plots"
OUTPUT_DIR: Path = BASE_DIR / "output"


class Settings(BaseSettings):
    """Centralized environment configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Gemini AI
    gemini_api_key: SecretStr = Field(default=SecretStr(""), alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.6-flash", alias="GEMINI_MODEL")

    # Discord Notifications
    discord_webhook_url: SecretStr = Field(
        default=SecretStr(""), alias="DISCORD_WEBHOOK_URL"
    )
    discord_test_mode: bool = Field(default=False, alias="DISCORD_TEST_MODE")

    # Google Drive Integration
    gdrive_service_account_file: str | None = Field(
        default=None, alias="GDRIVE_SERVICE_ACCOUNT_FILE"
    )
    gdrive_client_secret_file: Path = Field(
        default=DATA_DIR / "credentials.json",
        alias="GDRIVE_CLIENT_SECRET_FILE",
    )
    gdrive_token_file: Path = Field(
        default=DATA_DIR / "token.json", alias="GDRIVE_TOKEN_FILE"
    )
    gdrive_config_folder_id: str | None = Field(
        default=None, alias="GDRIVE_CONFIG_FOLDER_ID"
    )
    gdrive_database_folder_id: str | None = Field(
        default=None, alias="GDRIVE_DATABASE_FOLDER_ID"
    )
    gdrive_snapshot_folder_id: str | None = Field(
        default=None, alias="GDRIVE_SNAPSHOT_FOLDER_ID"
    )
    gdrive_reports_folder_id: str | None = Field(
        default=None, alias="GDRIVE_REPORTS_FOLDER_ID"
    )

    # Cache Settings
    etf_cache_ttl_days: int = Field(default=30, alias="ETF_CACHE_TTL_DAYS")

    # Dip Detector Settings
    min_drop_pct: float = Field(default=5.0, alias="MIN_DROP_PCT")
    max_drop_pct: float = Field(default=10.0, alias="MAX_DROP_PCT")
    lookback_days: int = Field(default=30, alias="LOOKBACK_DAYS")

    # Stock Strategy Settings
    stock_dip_min_pct: float = Field(default=5.0, alias="STOCK_DIP_MIN_PCT")
    stock_dip_max_pct: float = Field(default=20.0, alias="STOCK_DIP_MAX_PCT")
    stock_weight_dip: float = Field(default=0.35, alias="STOCK_WEIGHT_DIP")
    stock_weight_forward_pe: float = Field(
        default=0.35, alias="STOCK_WEIGHT_FORWARD_PE"
    )
    stock_weight_52w_range: float = Field(default=0.15, alias="STOCK_WEIGHT_52W_RANGE")
    stock_weight_allocation: float = Field(
        default=0.15, alias="STOCK_WEIGHT_ALLOCATION"
    )
    stock_alloc_gap_max_pct: float = Field(
        default=10.0, alias="STOCK_ALLOC_GAP_MAX_PCT"
    )
    # Penalty decay divisor: how steeply the dip score falls beyond dip_max_pct
    stock_dip_penalty_divisor: float = Field(
        default=30.0, alias="STOCK_DIP_PENALTY_DIVISOR"
    )
    # Score floor for below-dip-min region (max achievable score fraction)
    stock_dip_undershoot_cap: float = Field(
        default=0.2, alias="STOCK_DIP_UNDERSHOOT_CAP"
    )
    # P/E growth bonus multiplier: scales earnings-growth gain toward 1.0
    stock_pe_growth_multiplier: float = Field(
        default=2.4, alias="STOCK_PE_GROWTH_MULTIPLIER"
    )
    # P/E neutral starting score for earnings-growth and contraction regions
    stock_pe_neutral_score: float = Field(default=0.6, alias="STOCK_PE_NEUTRAL_SCORE")
    # 52-week range: relative position threshold below which score is maximum
    stock_52w_bottom_band: float = Field(default=0.30, alias="STOCK_52W_BOTTOM_BAND")

    # ETF Strategy Settings
    etf_weight_dip: float = Field(default=0.60, alias="ETF_WEIGHT_DIP")
    etf_weight_ter: float = Field(default=0.20, alias="ETF_WEIGHT_TER")
    etf_weight_allocation: float = Field(default=0.20, alias="ETF_WEIGHT_ALLOCATION")
    etf_dip_min_pct: float = Field(default=5.0, alias="ETF_DIP_MIN_PCT")
    etf_dip_max_pct: float = Field(default=10.0, alias="ETF_DIP_MAX_PCT")
    etf_ter_low_pct: float = Field(default=0.10, alias="ETF_TER_LOW_PCT")
    etf_ter_high_pct: float = Field(default=0.50, alias="ETF_TER_HIGH_PCT")
    etf_alloc_gap_max_pct: float = Field(default=10.0, alias="ETF_ALLOC_GAP_MAX_PCT")

    # Exposure Penalty Settings
    exposure_sector_penalty_weight: float = Field(
        default=0.30, alias="EXPOSURE_SECTOR_PENALTY_WEIGHT"
    )
    exposure_country_penalty_weight: float = Field(
        default=0.20, alias="EXPOSURE_COUNTRY_PENALTY_WEIGHT"
    )

    # Exposure Policy Limits
    max_country_allocation_pct: float = Field(
        default=60.0, alias="MAX_COUNTRY_ALLOCATION_PCT"
    )
    max_tech_allocation_pct: float = Field(
        default=50.0, alias="MAX_TECH_ALLOCATION_PCT"
    )
    max_other_sector_allocation_pct: float = Field(
        default=15.0, alias="MAX_OTHER_SECTOR_ALLOCATION_PCT"
    )
    max_company_allocation_pct: float = Field(
        default=15.0, alias="MAX_COMPANY_ALLOCATION_PCT"
    )

    # SMTP / Email Settings
    smtp_server: str = Field(default="", alias="SMTP_SERVER")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: SecretStr = Field(default=SecretStr(""), alias="SMTP_PASSWORD")
    alert_email_recipient: str = Field(default="", alias="ALERT_EMAIL_RECIPIENT")

    @field_validator("smtp_port", mode="before")
    @classmethod
    def parse_smtp_port(cls, v: Any) -> int:
        """Converts empty string to default SMTP port."""
        if isinstance(v, str) and not v.strip():
            return 587
        return int(v) if v is not None else 587


settings: Settings = Settings()

# Backwards Compatibility Aliases
CREDS_PATH_GDRIVE: Path = settings.gdrive_client_secret_file
TOKEN_PATH_GDRIVE: Path = settings.gdrive_token_file
GDRIVE_CONFIG_FOLDER_ID: str | None = settings.gdrive_config_folder_id
GDRIVE_DATABASE_FOLDER_ID: str | None = settings.gdrive_database_folder_id
GDRIVE_SNAPSHOT_FOLDER_ID: str | None = settings.gdrive_snapshot_folder_id
GDRIVE_REPORTS_FOLDER_ID: str | None = settings.gdrive_reports_folder_id

ETF_CACHE_FILE: Path = DATA_DIR / "etf_cache.json"
DEFAULT_ETF_CACHE_TTL_DAYS: int = settings.etf_cache_ttl_days


@dataclass(frozen=True)
class DipDetectorConfig:
    """Configuration parameters for generic dip detection scans."""

    min_drop_pct: float = settings.min_drop_pct
    max_drop_pct: float = settings.max_drop_pct
    lookback_days: int = settings.lookback_days


DEFAULT_DIP_CONFIG: DipDetectorConfig = DipDetectorConfig()


@dataclass(frozen=True)
class StockStrategyConfig:
    """Configuration parameters for individual stock scoring strategy."""

    dip_min_pct: float = settings.stock_dip_min_pct
    dip_max_pct: float = settings.stock_dip_max_pct
    weight_dip: float = settings.stock_weight_dip
    weight_forward_pe: float = settings.stock_weight_forward_pe
    weight_52w_range: float = settings.stock_weight_52w_range
    weight_allocation: float = settings.stock_weight_allocation
    alloc_gap_max_pct: float = settings.stock_alloc_gap_max_pct
    dip_penalty_divisor: float = settings.stock_dip_penalty_divisor
    dip_undershoot_cap: float = settings.stock_dip_undershoot_cap
    pe_growth_multiplier: float = settings.stock_pe_growth_multiplier
    pe_neutral_score: float = settings.stock_pe_neutral_score
    range_bottom_band: float = settings.stock_52w_bottom_band

    def __post_init__(self) -> None:
        """Validates that stock scoring criteria weights sum to 1.0."""
        total_weight: float = round(
            self.weight_dip
            + self.weight_forward_pe
            + self.weight_52w_range
            + self.weight_allocation,
            2,
        )
        if abs(total_weight - 1.0) > 1e-9:
            raise ValueError(
                f"Stock strategy weights must sum to 1.0, got {total_weight}"
            )


DEFAULT_STOCK_CONFIG: StockStrategyConfig = StockStrategyConfig()


@dataclass(frozen=True)
class EtfStrategyConfig:
    """Configuration parameters for ETF scoring strategy."""

    weight_dip: float = settings.etf_weight_dip
    weight_ter: float = settings.etf_weight_ter
    weight_allocation: float = settings.etf_weight_allocation

    dip_min_pct: float = settings.etf_dip_min_pct
    dip_max_pct: float = settings.etf_dip_max_pct

    ter_low_pct: float = settings.etf_ter_low_pct
    ter_high_pct: float = settings.etf_ter_high_pct

    alloc_gap_max_pct: float = settings.etf_alloc_gap_max_pct

    def __post_init__(self) -> None:
        """Validates that ETF scoring criteria weights sum to 1.0."""
        total_weight: float = round(
            self.weight_dip + self.weight_ter + self.weight_allocation, 2
        )
        if abs(total_weight - 1.0) > 1e-9:
            raise ValueError(
                f"ETF strategy weights must sum to 1.0, got {total_weight}"
            )


DEFAULT_ETF_CONFIG: EtfStrategyConfig = EtfStrategyConfig()

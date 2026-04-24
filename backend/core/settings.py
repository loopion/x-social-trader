from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Values persisted in DB (table `settings`) will
    override these in phase 2. Defaults here are the last line of defense
    for INV-1 (paper mode) and INV-3 (risk limits)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Trading mode (INV-1) ------------------------------------------------
    trading_mode: str = Field(default="paper", description="paper | live")
    paper_trading: bool = Field(default=True)

    # ---- Kill switch (INV-2) -------------------------------------------------
    kill_switch: int = Field(default=0, ge=0, le=1)

    # ---- Risk manager (INV-3) ------------------------------------------------
    max_capital_usd: float = 1000.0
    max_position_pct: float = 2.0
    max_total_exposure_pct: float = 20.0
    max_trades_per_day: int = 10
    max_daily_drawdown_pct: float = 3.0
    allow_after_hours: bool = False

    # ---- Market calendar (RISK-01) — ISO 10383 MIC code ---------------------
    # XNYS = NYSE, XPAR = Euronext Paris (CAC 40), XLON = LSE, etc.
    # Validated at startup against exchange_calendars' built-in list.
    market: str = "XNYS"

    # ---- Interactive Brokers (phase 5) ---------------------------------------
    ib_gateway_url: str = ""
    ib_expected_account_id: str = ""

    # ---- twitterapi.io (phase 7) ---------------------------------------------
    twitterapi_io_key: str = ""
    twitterapi_io_max_usd: float = 50.0

    # ---- LLM (phase 8) -------------------------------------------------------
    llm_provider: str = "openai_compatible"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_max_usd_per_day: float = 5.0

    # ---- Telegram (phases 11 + 13) -------------------------------------------
    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""

    # ---- Infrastructure ------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    redis_url: str = "redis://redis:6379/0"

    @property
    def is_live_trading(self) -> bool:
        """INV-1 double opt-in helper. Kill switch is checked separately."""
        return self.trading_mode == "live" and not self.paper_trading


def get_settings() -> Settings:
    return Settings()

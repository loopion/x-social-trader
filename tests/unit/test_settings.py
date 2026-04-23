from backend.core.settings import Settings, get_settings


def test_safe_defaults_enforce_paper_mode() -> None:
    """INV-1: paper is the default until double opt-in."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.trading_mode == "paper"
    assert s.paper_trading is True
    assert s.is_live_trading is False


def test_kill_switch_default_inactive() -> None:
    """INV-2: kill switch defaults off, but flipping it to 1 must be trivial."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.kill_switch == 0


def test_risk_defaults_match_claudemd() -> None:
    """INV-3: limits from CLAUDE.md §2."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.max_position_pct == 2.0
    assert s.max_total_exposure_pct == 20.0
    assert s.max_trades_per_day == 10
    assert s.max_daily_drawdown_pct == 3.0
    assert s.allow_after_hours is False


def test_is_live_trading_requires_both_flags() -> None:
    """INV-1: live mode requires trading_mode=live AND paper_trading=false."""
    s = Settings(_env_file=None, trading_mode="live", paper_trading=True)  # type: ignore[call-arg]
    assert s.is_live_trading is False

    s = Settings(_env_file=None, trading_mode="paper", paper_trading=False)  # type: ignore[call-arg]
    assert s.is_live_trading is False

    s = Settings(_env_file=None, trading_mode="live", paper_trading=False)  # type: ignore[call-arg]
    assert s.is_live_trading is True


def test_get_settings_returns_settings_instance() -> None:
    assert isinstance(get_settings(), Settings)

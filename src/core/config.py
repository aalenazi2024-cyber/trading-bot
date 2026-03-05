"""Configuration management for the 0DTE SPX trading bot."""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class BrokerConfig:
    """Alpaca broker config (used if BROKER=alpaca)."""
    api_key: str = ""
    secret_key: str = ""
    base_url: str = "https://paper-api.alpaca.markets"
    trading_mode: str = "paper"  # "paper" or "live"

    def __post_init__(self):
        self.api_key = self.api_key or os.getenv("ALPACA_API_KEY", "")
        self.secret_key = self.secret_key or os.getenv("ALPACA_SECRET_KEY", "")
        self.base_url = os.getenv("ALPACA_BASE_URL", self.base_url)
        self.trading_mode = os.getenv("TRADING_MODE", self.trading_mode)


@dataclass
class IBKRConfig:
    """Interactive Brokers TWS/Gateway connection config."""
    host: str = "127.0.0.1"
    port: int = 7497                       # 7497=paper, 7496=live
    client_id: int = 1
    trading_mode: str = "paper"            # "paper" or "live"

    def __post_init__(self):
        self.host = os.getenv("IBKR_HOST", self.host)
        self.port = int(os.getenv("IBKR_PORT", self.port))
        self.client_id = int(os.getenv("IBKR_CLIENT_ID", self.client_id))
        self.trading_mode = os.getenv("IBKR_TRADING_MODE", self.trading_mode)


@dataclass
class TradingViewConfig:
    """TradingView webhook server config."""
    enabled: bool = False
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 5000
    webhook_token: str = ""                # Secret token to verify alerts

    def __post_init__(self):
        self.enabled = os.getenv("TRADINGVIEW_ENABLED", "false").lower() == "true"
        self.webhook_host = os.getenv("TRADINGVIEW_HOST", self.webhook_host)
        self.webhook_port = int(os.getenv("TRADINGVIEW_PORT", self.webhook_port))
        self.webhook_token = os.getenv("TRADINGVIEW_TOKEN", self.webhook_token)


@dataclass
class RiskConfig:
    """Aggressive risk settings for max risk/max reward 0DTE trading."""
    max_position_size: float = 5000.0       # Max dollars per trade
    max_daily_loss: float = 2000.0          # Stop trading after this loss
    max_open_positions: int = 3             # Simultaneous positions
    profit_target_pct: float = 100.0        # 100% profit target (aggressive)
    stop_loss_pct: float = 50.0             # 50% stop loss (aggressive)
    trailing_stop_pct: float = 30.0         # Trailing stop after profit
    scale_in_enabled: bool = True           # Add to winners
    max_contracts_per_trade: int = 20       # Max contracts
    min_option_price: float = 0.50          # Min premium to buy
    max_option_price: float = 10.00         # Max premium to buy
    use_aggressive_mode: bool = True        # Full send mode

    def __post_init__(self):
        self.max_position_size = float(os.getenv("MAX_POSITION_SIZE", self.max_position_size))
        self.max_daily_loss = float(os.getenv("MAX_DAILY_LOSS", self.max_daily_loss))
        self.max_open_positions = int(os.getenv("MAX_OPEN_POSITIONS", self.max_open_positions))


@dataclass
class StrategyConfig:
    """Which strategies to run and their parameters."""
    # Opening Range Breakout
    orb_enabled: bool = True
    orb_range_minutes: int = 15             # First 15 min for range
    orb_breakout_threshold: float = 0.3     # Points beyond range to trigger

    # VWAP strategy
    vwap_enabled: bool = True
    vwap_bounce_threshold: float = 1.0      # Points from VWAP to trigger
    vwap_confirmation_candles: int = 2       # Candles to confirm bounce

    # Momentum scalp
    momentum_enabled: bool = True
    momentum_lookback: int = 5              # Candle lookback period
    momentum_min_move: float = 3.0          # Min SPX point move to trigger

    # Mean reversion
    mean_reversion_enabled: bool = True
    mean_reversion_std_threshold: float = 2.0  # Std deviations for entry
    mean_reversion_lookback: int = 20          # Candle lookback

    # TradingView signals (requires webhook enabled)
    tradingview_signals_enabled: bool = True


@dataclass
class TradingHours:
    """Market hours for 0DTE trading."""
    market_open_hour: int = 9
    market_open_minute: int = 30
    # Start trading after opening range forms
    trading_start_hour: int = 9
    trading_start_minute: int = 46
    # Stop entering new positions before close
    last_entry_hour: int = 15
    last_entry_minute: int = 30
    # Force close everything
    force_close_hour: int = 15
    force_close_minute: int = 55
    market_close_hour: int = 16
    market_close_minute: int = 0


@dataclass
class BotConfig:
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    ibkr: IBKRConfig = field(default_factory=IBKRConfig)
    tradingview: TradingViewConfig = field(default_factory=TradingViewConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    hours: TradingHours = field(default_factory=TradingHours)
    broker_type: str = "ibkr"              # "ibkr" or "alpaca"
    ticker: str = "SPX"
    data_interval: str = "1min"            # Candle interval
    log_level: str = "INFO"

    def __post_init__(self):
        self.broker_type = os.getenv("BROKER", self.broker_type)

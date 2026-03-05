"""
TradingView Signal Strategy - Executes trades from TradingView webhook alerts.

This strategy doesn't analyze market data itself. Instead, it reads signals
that came in from TradingView webhooks and passes them to the trading engine.

This lets you use ANY TradingView indicator or strategy as your signal source:
- Custom Pine Script strategies
- Popular indicators (EMA cross, RSI divergence, etc.)
- TradingView's built-in strategies
- Screener-based alerts
"""

from typing import Optional

from loguru import logger

from src.strategies.base import BaseStrategy, Signal
from src.data.market_data import MarketData
from src.core.tradingview_webhook import TradingViewWebhook


class TradingViewStrategy(BaseStrategy):
    """
    Strategy that executes trades based on TradingView webhook signals.

    Unlike other strategies that analyze market data, this one simply
    forwards signals received from TradingView alerts.
    """

    def __init__(self, webhook: TradingViewWebhook):
        super().__init__("TRADINGVIEW")
        self.webhook = webhook

    def evaluate(self, data: MarketData) -> Optional[Signal]:
        """
        Check for pending TradingView signals.
        Returns the most recent signal if any are pending.
        """
        signals = self.webhook.get_pending_signals()

        if not signals:
            return None

        # Take the most recent signal
        latest = signals[-1]

        # Skip sell/close signals here (handled by engine)
        if latest.direction == "close":
            logger.info(f"TradingView CLOSE signal received - "
                         f"engine will handle position closing")
            return None

        logger.info(f"TradingView signal: {latest.direction.upper()} | "
                     f"Strength: {latest.strength:.2f} | "
                     f"Reason: {latest.reason}")

        return latest

    def get_optimal_strike_offset(self, data: MarketData, direction: str) -> float:
        """Strike offset is provided by the TradingView alert."""
        if direction == "call":
            return 2.0
        return -2.0

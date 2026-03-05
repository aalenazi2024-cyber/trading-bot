"""
Mean Reversion Strategy for 0DTE SPX.

How it works:
1. When SPX makes an extreme move (2+ standard deviations), it tends to revert
2. Detect overextended price action using Bollinger Band-like logic
3. BUY PUTS after extreme up moves (fade the spike)
4. BUY CALLS after extreme down moves (buy the dip)

This strategy works best on:
- Choppy/range-bound days
- After panic selling or euphoric buying
- When no clear trend exists
"""

from typing import Optional

import numpy as np
from loguru import logger

from src.strategies.base import BaseStrategy, Signal
from src.data.market_data import MarketData


class MeanReversion(BaseStrategy):
    """
    Mean reversion strategy for fading extreme 0DTE SPX moves.

    Counter-trend strategy that buys when others are panicking
    and sells when others are euphoric. High risk, high reward.
    """

    def __init__(self, std_threshold: float = 2.0, lookback: int = 20):
        super().__init__("MEAN_REVERSION")
        self.std_threshold = std_threshold
        self.lookback = lookback

    def evaluate(self, data: MarketData) -> Optional[Signal]:
        """Detect overextended moves for mean reversion entries."""
        if len(data.candles) < self.lookback + 5:
            return None

        current_price = data.get_latest_price()
        closes = data.candles["close"].values

        # Calculate z-score of current price relative to recent mean
        recent = closes[-self.lookback:]
        mean = np.mean(recent)
        std = np.std(recent)

        if std == 0:
            return None

        z_score = (current_price - mean) / std
        rsi = data.get_rsi(14)

        # OVERBOUGHT: Price is 2+ std devs above mean → BUY PUTS (fade the spike)
        if z_score > self.std_threshold:
            if rsi < 65:  # Need RSI to confirm overbought
                return None

            strength = min(1.0, (z_score - self.std_threshold) / 2.0 + 0.5)

            # Extra confirmation: bearish candle pattern
            pattern = data.get_candle_pattern()
            if pattern == "bearish_engulfing":
                strength = min(1.0, strength + 0.2)

            offset = self.get_optimal_strike_offset(data, "put")

            logger.info(f"MEAN REVERSION SHORT: Z-score {z_score:.2f} | "
                         f"RSI: {rsi:.1f} | Price {current_price:.2f} vs Mean {mean:.2f}")

            return Signal(
                direction="put",
                strength=strength,
                strategy_name=self.name,
                strike_offset=offset,
                reason=f"Overbought reversion: z={z_score:.2f}, RSI={rsi:.1f}"
            )

        # OVERSOLD: Price is 2+ std devs below mean → BUY CALLS (buy the dip)
        if z_score < -self.std_threshold:
            if rsi > 35:  # Need RSI to confirm oversold
                return None

            strength = min(1.0, (abs(z_score) - self.std_threshold) / 2.0 + 0.5)

            pattern = data.get_candle_pattern()
            if pattern in ("bullish_engulfing", "hammer"):
                strength = min(1.0, strength + 0.2)

            offset = self.get_optimal_strike_offset(data, "call")

            logger.info(f"MEAN REVERSION LONG: Z-score {z_score:.2f} | "
                         f"RSI: {rsi:.1f} | Price {current_price:.2f} vs Mean {mean:.2f}")

            return Signal(
                direction="call",
                strength=strength,
                strategy_name=self.name,
                strike_offset=offset,
                reason=f"Oversold reversion: z={z_score:.2f}, RSI={rsi:.1f}"
            )

        return None

    def get_optimal_strike_offset(self, data: MarketData, direction: str) -> float:
        """
        For mean reversion, use ATM or slightly ITM since we expect
        a reversal back toward the mean.
        """
        if direction == "call":
            return -1.0  # Slightly ITM call for higher delta
        else:
            return 1.0   # Slightly ITM put for higher delta

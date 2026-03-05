"""
VWAP Bounce/Rejection Strategy for 0DTE SPX.

How it works:
1. VWAP (Volume Weighted Average Price) is THE institutional reference price
2. When price pulls back TO VWAP and bounces → trade in direction of bounce
3. In uptrends: VWAP acts as support → BUY CALLS on bounce
4. In downtrends: VWAP acts as resistance → BUY PUTS on rejection

This is one of the most reliable intraday strategies used by prop traders.
"""

from typing import Optional

from loguru import logger

from src.strategies.base import BaseStrategy, Signal
from src.data.market_data import MarketData


class VWAPStrategy(BaseStrategy):
    """
    VWAP Bounce/Rejection for 0DTE SPX options.

    Works best when:
    - Clear trend exists (not choppy/range-bound)
    - Price approaches VWAP with decreasing momentum
    - Candle pattern confirms bounce/rejection
    """

    def __init__(self, bounce_threshold: float = 1.0, confirmation_candles: int = 2):
        super().__init__("VWAP")
        self.bounce_threshold = bounce_threshold  # Points from VWAP
        self.confirmation_candles = confirmation_candles
        self.last_signal_price = 0.0

    def evaluate(self, data: MarketData) -> Optional[Signal]:
        """Look for VWAP bounces or rejections."""
        vwap = data.calculate_vwap()
        if vwap == 0:
            return None

        current_price = data.get_latest_price()
        distance_from_vwap = current_price - vwap

        # Only trigger when price is near VWAP
        if abs(distance_from_vwap) > self.bounce_threshold * 3:
            return None

        # Avoid repeat signals at same price level
        if abs(current_price - self.last_signal_price) < 1.0:
            return None

        candle_pattern = data.get_candle_pattern()
        rsi = data.get_rsi(14)
        momentum = data.get_momentum(self.confirmation_candles)

        # VWAP BOUNCE (Bullish): Price at/below VWAP, then bounces up
        if (abs(distance_from_vwap) < self.bounce_threshold and
                momentum > 0 and
                candle_pattern in ("bullish_engulfing", "hammer", "neutral") and
                rsi < 60):

            strength = 0.6
            if candle_pattern in ("bullish_engulfing", "hammer"):
                strength += 0.2
            if rsi < 40:  # Oversold bounce
                strength += 0.15

            self.last_signal_price = current_price
            offset = self.get_optimal_strike_offset(data, "call")

            logger.info(f"VWAP BOUNCE: Price {current_price:.2f} near VWAP {vwap:.2f} | "
                         f"RSI: {rsi:.1f} | Pattern: {candle_pattern}")

            return Signal(
                direction="call",
                strength=min(1.0, strength),
                strategy_name=self.name,
                strike_offset=offset,
                reason=f"VWAP bounce at {vwap:.2f}, RSI={rsi:.1f}, {candle_pattern}"
            )

        # VWAP REJECTION (Bearish): Price at/above VWAP, then rejects down
        if (abs(distance_from_vwap) < self.bounce_threshold and
                momentum < 0 and
                candle_pattern in ("bearish_engulfing", "neutral") and
                rsi > 40):

            strength = 0.6
            if candle_pattern == "bearish_engulfing":
                strength += 0.2
            if rsi > 70:  # Overbought rejection
                strength += 0.15

            self.last_signal_price = current_price
            offset = self.get_optimal_strike_offset(data, "put")

            logger.info(f"VWAP REJECTION: Price {current_price:.2f} near VWAP {vwap:.2f} | "
                         f"RSI: {rsi:.1f} | Pattern: {candle_pattern}")

            return Signal(
                direction="put",
                strength=min(1.0, strength),
                strategy_name=self.name,
                strike_offset=offset,
                reason=f"VWAP rejection at {vwap:.2f}, RSI={rsi:.1f}, {candle_pattern}"
            )

        return None

    def get_optimal_strike_offset(self, data: MarketData, direction: str) -> float:
        """
        VWAP trades are higher probability, so we can go slightly ITM
        for higher delta (more responsive to price movement).
        """
        if direction == "call":
            return 0.0  # ATM for best delta exposure
        else:
            return 0.0  # ATM puts

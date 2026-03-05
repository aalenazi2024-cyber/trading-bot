"""
Opening Range Breakout (ORB) Strategy - The #1 most popular 0DTE strategy.

How it works:
1. Wait for the first 15 minutes of market open to establish the range
2. If price breaks above the opening range high → BUY CALLS
3. If price breaks below the opening range low → BUY PUTS
4. Use volume confirmation to avoid false breakouts

This strategy has the highest win rate for 0DTE SPX options when
combined with volume and trend confirmation.
"""

from typing import Optional

from loguru import logger

from src.strategies.base import BaseStrategy, Signal
from src.data.market_data import MarketData


class OpeningRangeBreakout(BaseStrategy):
    """
    Opening Range Breakout strategy for 0DTE SPX.

    Most successful when:
    - Market has clear directional bias
    - Opening range is narrow (tight consolidation = explosive breakout)
    - Volume confirms the breakout
    """

    def __init__(self, range_minutes: int = 15, breakout_threshold: float = 0.3):
        super().__init__("ORB")
        self.range_minutes = range_minutes
        self.breakout_threshold = breakout_threshold  # Points beyond range
        self.range_established = False

    def evaluate(self, data: MarketData) -> Optional[Signal]:
        """Check for opening range breakout."""
        # Calculate opening range if not done
        or_high, or_low = data.calculate_opening_range(self.range_minutes)

        if or_high == 0 or or_low == 0:
            return None

        self.range_established = True
        current_price = data.get_latest_price()
        range_size = or_high - or_low

        # Avoid trading if range is too wide (choppy market)
        if range_size > 15:
            logger.debug(f"ORB: Range too wide ({range_size:.1f} pts), skipping")
            return None

        # BULLISH BREAKOUT: Price breaks above opening range high
        if current_price > or_high + self.breakout_threshold:
            # Confirm with momentum
            momentum = data.get_momentum(3)
            if momentum <= 0:
                return None

            # Confirm price is above VWAP (institutional buying)
            above_vwap = data.is_above_vwap()

            strength = min(1.0, (current_price - or_high) / range_size)
            if above_vwap:
                strength = min(1.0, strength + 0.2)

            offset = self.get_optimal_strike_offset(data, "call")

            logger.info(f"ORB BULLISH BREAKOUT: Price {current_price:.2f} > "
                         f"Range High {or_high:.2f} | Strength: {strength:.2f}")

            return Signal(
                direction="call",
                strength=strength,
                strategy_name=self.name,
                strike_offset=offset,
                reason=f"ORB breakout above {or_high:.2f}, momentum={momentum:.2f}"
            )

        # BEARISH BREAKOUT: Price breaks below opening range low
        if current_price < or_low - self.breakout_threshold:
            momentum = data.get_momentum(3)
            if momentum >= 0:
                return None

            below_vwap = not data.is_above_vwap()

            strength = min(1.0, (or_low - current_price) / range_size)
            if below_vwap:
                strength = min(1.0, strength + 0.2)

            offset = self.get_optimal_strike_offset(data, "put")

            logger.info(f"ORB BEARISH BREAKOUT: Price {current_price:.2f} < "
                         f"Range Low {or_low:.2f} | Strength: {strength:.2f}")

            return Signal(
                direction="put",
                strength=strength,
                strategy_name=self.name,
                strike_offset=offset,
                reason=f"ORB breakdown below {or_low:.2f}, momentum={momentum:.2f}"
            )

        return None

    def get_optimal_strike_offset(self, data: MarketData, direction: str) -> float:
        """
        For aggressive 0DTE, buy slightly OTM for maximum leverage.
        Closer strikes = higher premium but higher probability.
        Further strikes = cheaper but need bigger move.

        For max risk/reward: go 2-5 points OTM.
        """
        volatility = data.get_volatility()

        if direction == "call":
            # Slightly OTM call: strike above current price
            if volatility > 0.3:  # High vol: go further OTM for cheaper entry
                return 5.0
            return 2.0
        else:
            # Slightly OTM put: strike below current price
            if volatility > 0.3:
                return -5.0
            return -2.0

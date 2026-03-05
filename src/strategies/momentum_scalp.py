"""
Momentum Scalp Strategy for 0DTE SPX.

How it works:
1. Detect strong directional moves (3+ SPX points in last 5 candles)
2. Confirm trend with EMA alignment and RSI
3. Enter in the direction of momentum
4. Quick profits — ride the wave then get out

This strategy catches the big intraday SPX moves that happen
during economic data releases, Fed speakers, or sector rotations.
"""

from typing import Optional

from loguru import logger

from src.strategies.base import BaseStrategy, Signal
from src.data.market_data import MarketData


class MomentumScalp(BaseStrategy):
    """
    Momentum-based scalping for 0DTE SPX options.

    Best for:
    - Strong trending days
    - After economic data releases
    - Breakouts from consolidation
    """

    def __init__(self, lookback: int = 5, min_move: float = 3.0):
        super().__init__("MOMENTUM")
        self.lookback = lookback
        self.min_move = min_move  # Minimum SPX point move
        self.last_signal_time = None

    def evaluate(self, data: MarketData) -> Optional[Signal]:
        """Detect strong momentum and generate signal."""
        momentum = data.get_momentum(self.lookback)

        # Need significant move
        if abs(momentum) < self.min_move:
            return None

        current_price = data.get_latest_price()
        rsi = data.get_rsi(14)
        ema_9 = data.get_ema(9)
        ema_21 = data.get_ema(21)

        # BULLISH MOMENTUM
        if momentum > self.min_move:
            # Confirm with EMA alignment
            if ema_9 <= ema_21:
                return None  # EMAs not aligned, skip

            # Don't chase if RSI is extremely overbought
            if rsi > 85:
                logger.debug(f"MOMENTUM: RSI too high ({rsi:.1f}), skipping bullish entry")
                return None

            # Strength based on momentum magnitude
            strength = min(1.0, abs(momentum) / (self.min_move * 3))

            # Boost if VWAP confirms
            if data.is_above_vwap():
                strength = min(1.0, strength + 0.15)

            offset = self.get_optimal_strike_offset(data, "call")

            logger.info(f"MOMENTUM BULLISH: +{momentum:.2f} pts | "
                         f"RSI: {rsi:.1f} | EMA9>{ema_9:.2f} EMA21>{ema_21:.2f}")

            return Signal(
                direction="call",
                strength=strength,
                strategy_name=self.name,
                strike_offset=offset,
                reason=f"Strong bullish momentum +{momentum:.2f}pts, RSI={rsi:.1f}"
            )

        # BEARISH MOMENTUM
        if momentum < -self.min_move:
            if ema_9 >= ema_21:
                return None  # EMAs not aligned

            if rsi < 15:
                logger.debug(f"MOMENTUM: RSI too low ({rsi:.1f}), skipping bearish entry")
                return None

            strength = min(1.0, abs(momentum) / (self.min_move * 3))

            if not data.is_above_vwap():
                strength = min(1.0, strength + 0.15)

            offset = self.get_optimal_strike_offset(data, "put")

            logger.info(f"MOMENTUM BEARISH: {momentum:.2f} pts | "
                         f"RSI: {rsi:.1f} | EMA9<{ema_9:.2f} EMA21<{ema_21:.2f}")

            return Signal(
                direction="put",
                strength=strength,
                strategy_name=self.name,
                strike_offset=offset,
                reason=f"Strong bearish momentum {momentum:.2f}pts, RSI={rsi:.1f}"
            )

        return None

    def get_optimal_strike_offset(self, data: MarketData, direction: str) -> float:
        """
        For momentum trades, go slightly OTM for maximum leverage.
        Strong momentum can push OTM options to massive gains.
        """
        momentum = abs(data.get_momentum(self.lookback))

        if direction == "call":
            if momentum > 8:  # Very strong move
                return 3.0   # Go further OTM, cheaper premium, bigger % gains
            return 1.0
        else:
            if momentum > 8:
                return -3.0
            return -1.0

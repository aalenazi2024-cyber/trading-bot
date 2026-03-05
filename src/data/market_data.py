"""Market data collection and processing for SPX 0DTE trading."""

from datetime import datetime, timedelta, date
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

try:
    import alpaca_trade_api as tradeapi
except ImportError:
    tradeapi = None


class MarketData:
    """Collects and processes intraday SPX market data."""

    def __init__(self, api):
        self.api = api
        self.candles: pd.DataFrame = pd.DataFrame()
        self.vwap: float = 0.0
        self.opening_range_high: float = 0.0
        self.opening_range_low: float = 0.0
        self.daily_high: float = 0.0
        self.daily_low: float = 0.0
        self.prev_close: float = 0.0

    def fetch_intraday_bars(self, symbol: str = "SPY", interval: str = "1Min",
                            lookback_days: int = 1) -> pd.DataFrame:
        """
        Fetch intraday bars. Uses SPY as SPX proxy.
        Prices are multiplied by 10 to approximate SPX levels.
        """
        try:
            end = datetime.now()
            start = end - timedelta(days=lookback_days)
            bars = self.api.get_bars(
                symbol,
                interval,
                start=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                end=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                feed="iex",
            ).df

            if bars.empty:
                logger.warning("No bars returned")
                return pd.DataFrame()

            # Scale to approximate SPX
            for col in ["open", "high", "low", "close"]:
                bars[col] = bars[col] * 10.0
            bars["volume"] = bars["volume"]

            self.candles = bars
            self._update_levels()
            return bars

        except Exception as e:
            logger.error(f"Error fetching bars: {e}")
            return pd.DataFrame()

    def _update_levels(self):
        """Update key price levels from current data."""
        if self.candles.empty:
            return

        today = date.today()
        today_candles = self.candles[self.candles.index.date == today]

        if not today_candles.empty:
            self.daily_high = today_candles["high"].max()
            self.daily_low = today_candles["low"].min()

        # Previous close
        prev_candles = self.candles[self.candles.index.date < today]
        if not prev_candles.empty:
            self.prev_close = prev_candles["close"].iloc[-1]

    def calculate_opening_range(self, range_minutes: int = 15) -> tuple[float, float]:
        """
        Calculate the opening range (first N minutes high/low).
        This is the core of the ORB strategy.
        """
        if self.candles.empty:
            return 0.0, 0.0

        today = date.today()
        today_candles = self.candles[self.candles.index.date == today]

        if today_candles.empty:
            return 0.0, 0.0

        market_open = today_candles.index[0]
        range_end = market_open + timedelta(minutes=range_minutes)
        range_candles = today_candles[today_candles.index <= range_end]

        if range_candles.empty:
            return 0.0, 0.0

        self.opening_range_high = range_candles["high"].max()
        self.opening_range_low = range_candles["low"].min()

        logger.info(f"Opening range ({range_minutes}min): "
                     f"High={self.opening_range_high:.2f}, Low={self.opening_range_low:.2f}")

        return self.opening_range_high, self.opening_range_low

    def calculate_vwap(self) -> float:
        """Calculate Volume Weighted Average Price for today."""
        if self.candles.empty:
            return 0.0

        today = date.today()
        today_candles = self.candles[self.candles.index.date == today].copy()

        if today_candles.empty:
            return 0.0

        typical_price = (today_candles["high"] + today_candles["low"] + today_candles["close"]) / 3
        cumulative_tp_vol = (typical_price * today_candles["volume"]).cumsum()
        cumulative_vol = today_candles["volume"].cumsum()

        vwap_series = cumulative_tp_vol / cumulative_vol
        self.vwap = vwap_series.iloc[-1] if not vwap_series.empty else 0.0

        return self.vwap

    def get_latest_price(self) -> float:
        """Get the most recent close price."""
        if self.candles.empty:
            return 0.0
        return self.candles["close"].iloc[-1]

    def get_momentum(self, lookback: int = 5) -> float:
        """
        Calculate price momentum over last N candles.
        Returns the point change.
        """
        if len(self.candles) < lookback:
            return 0.0
        return self.candles["close"].iloc[-1] - self.candles["close"].iloc[-lookback]

    def get_volatility(self, lookback: int = 20) -> float:
        """Calculate rolling standard deviation of returns."""
        if len(self.candles) < lookback:
            return 0.0
        returns = self.candles["close"].pct_change().dropna()
        if len(returns) < lookback:
            return 0.0
        return returns.iloc[-lookback:].std() * np.sqrt(252 * 390)  # Annualized

    def get_rsi(self, period: int = 14) -> float:
        """Calculate RSI."""
        if len(self.candles) < period + 1:
            return 50.0

        close = self.candles["close"]
        delta = close.diff().dropna()
        gains = delta.where(delta > 0, 0.0)
        losses = (-delta.where(delta < 0, 0.0))

        avg_gain = gains.rolling(window=period).mean().iloc[-1]
        avg_loss = losses.rolling(window=period).mean().iloc[-1]

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def get_ema(self, period: int = 9) -> float:
        """Calculate EMA."""
        if len(self.candles) < period:
            return 0.0
        return self.candles["close"].ewm(span=period).mean().iloc[-1]

    def is_above_vwap(self) -> bool:
        """Check if current price is above VWAP."""
        price = self.get_latest_price()
        vwap = self.calculate_vwap()
        return price > vwap

    def get_candle_pattern(self) -> str:
        """Detect basic candle patterns on last few candles."""
        if len(self.candles) < 3:
            return "unknown"

        last = self.candles.iloc[-1]
        prev = self.candles.iloc[-2]

        body = last["close"] - last["open"]
        prev_body = prev["close"] - prev["open"]

        # Bullish engulfing
        if prev_body < 0 and body > 0 and abs(body) > abs(prev_body):
            return "bullish_engulfing"

        # Bearish engulfing
        if prev_body > 0 and body < 0 and abs(body) > abs(prev_body):
            return "bearish_engulfing"

        # Hammer (bullish)
        candle_range = last["high"] - last["low"]
        if candle_range > 0:
            lower_wick = min(last["open"], last["close"]) - last["low"]
            upper_wick = last["high"] - max(last["open"], last["close"])
            if lower_wick > 2 * abs(body) and upper_wick < abs(body) * 0.5:
                return "hammer"

        return "neutral"

    def get_support_resistance(self, lookback: int = 50) -> tuple[float, float]:
        """Find nearest support and resistance levels."""
        if len(self.candles) < lookback:
            lookback = len(self.candles)
        if lookback < 5:
            return 0.0, 0.0

        recent = self.candles.iloc[-lookback:]
        price = self.get_latest_price()

        highs = recent["high"].values
        lows = recent["low"].values

        resistance = min(h for h in highs if h > price) if any(h > price for h in highs) else price + 5
        support = max(l for l in lows if l < price) if any(l < price for l in lows) else price - 5

        return support, resistance

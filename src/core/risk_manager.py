"""Risk management for aggressive 0DTE trading."""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

from loguru import logger

from src.core.config import RiskConfig


@dataclass
class Position:
    """Tracks an open option position."""
    symbol: str
    option_type: str          # "call" or "put"
    strike: float
    entry_price: float        # Per contract premium
    qty: int
    entry_time: datetime
    strategy: str             # Which strategy opened this
    highest_price: float = 0.0  # For trailing stop
    stop_loss: float = 0.0
    profit_target: float = 0.0

    @property
    def cost_basis(self) -> float:
        return self.entry_price * self.qty * 100  # Options are 100 shares

    def update_trailing_stop(self, current_price: float, trailing_pct: float):
        """Update trailing stop as price moves up."""
        if current_price > self.highest_price:
            self.highest_price = current_price
            self.stop_loss = self.highest_price * (1 - trailing_pct / 100)


class RiskManager:
    """
    Manages risk for max risk/max reward 0DTE trading.

    Aggressive mode features:
    - Large position sizing relative to account
    - Wide stop losses to avoid premature exits
    - High profit targets for big wins
    - Trailing stops to lock in gains
    - Scale-in on winners
    """

    def __init__(self, config: RiskConfig):
        self.config = config
        self.positions: dict[str, Position] = {}
        self.daily_pnl: float = 0.0
        self.trades_today: int = 0
        self.wins_today: int = 0
        self.losses_today: int = 0
        self.is_halted: bool = False

    def can_open_position(self) -> tuple[bool, str]:
        """Check if we're allowed to open a new position."""
        if self.is_halted:
            return False, "Trading halted - daily loss limit reached"

        if abs(self.daily_pnl) >= self.config.max_daily_loss and self.daily_pnl < 0:
            self.is_halted = True
            return False, f"Daily loss limit reached: ${self.daily_pnl:.2f}"

        if len(self.positions) >= self.config.max_open_positions:
            return False, f"Max open positions reached: {len(self.positions)}"

        return True, "OK"

    def calculate_position_size(self, option_price: float, buying_power: float) -> int:
        """
        Calculate number of contracts to buy.
        Aggressive sizing for max reward.
        """
        if option_price <= 0:
            return 0

        cost_per_contract = option_price * 100  # Options = 100 multiplier

        # Use max position size or available buying power, whichever is less
        available = min(self.config.max_position_size, buying_power * 0.8)

        contracts = int(available / cost_per_contract)

        # Cap at max contracts
        contracts = min(contracts, self.config.max_contracts_per_trade)

        # Minimum 1 contract
        return max(1, contracts)

    def calculate_stops(self, entry_price: float) -> tuple[float, float]:
        """
        Calculate stop loss and profit target for aggressive trading.

        Returns (stop_loss_price, profit_target_price)
        """
        stop_loss = entry_price * (1 - self.config.stop_loss_pct / 100)
        profit_target = entry_price * (1 + self.config.profit_target_pct / 100)

        return max(0.01, stop_loss), profit_target

    def register_position(self, symbol: str, option_type: str, strike: float,
                          entry_price: float, qty: int, strategy: str) -> Position:
        """Register a new open position."""
        stop_loss, profit_target = self.calculate_stops(entry_price)

        position = Position(
            symbol=symbol,
            option_type=option_type,
            strike=strike,
            entry_price=entry_price,
            qty=qty,
            entry_time=datetime.now(),
            strategy=strategy,
            highest_price=entry_price,
            stop_loss=stop_loss,
            profit_target=profit_target,
        )

        self.positions[symbol] = position
        self.trades_today += 1
        logger.info(f"Position opened: {qty}x {symbol} @ ${entry_price:.2f} | "
                     f"Stop: ${stop_loss:.2f} | Target: ${profit_target:.2f} | "
                     f"Strategy: {strategy}")
        return position

    def check_exit_signals(self, symbol: str, current_price: float) -> tuple[bool, str]:
        """
        Check if a position should be exited.

        Returns (should_exit, reason)
        """
        if symbol not in self.positions:
            return False, "Position not found"

        pos = self.positions[symbol]

        # Update trailing stop
        pos.update_trailing_stop(current_price, self.config.trailing_stop_pct)

        # Check profit target
        if current_price >= pos.profit_target:
            return True, f"PROFIT TARGET HIT: ${current_price:.2f} >= ${pos.profit_target:.2f}"

        # Check stop loss
        if current_price <= pos.stop_loss:
            return True, f"STOP LOSS HIT: ${current_price:.2f} <= ${pos.stop_loss:.2f}"

        # Check trailing stop (only after we're in profit)
        if pos.highest_price > pos.entry_price * 1.2:  # 20% above entry
            trailing_stop = pos.highest_price * (1 - self.config.trailing_stop_pct / 100)
            if current_price <= trailing_stop:
                return True, f"TRAILING STOP: ${current_price:.2f} <= ${trailing_stop:.2f}"

        # Option approaching worthless
        if current_price < 0.10:
            return True, "Option nearly worthless"

        return False, "Hold"

    def should_scale_in(self, symbol: str, current_price: float) -> bool:
        """
        Check if we should add to a winning position.
        Only scale in if price has moved 30%+ in our favor.
        """
        if not self.config.scale_in_enabled:
            return False

        if symbol not in self.positions:
            return False

        pos = self.positions[symbol]
        gain_pct = (current_price - pos.entry_price) / pos.entry_price * 100

        return gain_pct >= 30.0

    def record_close(self, symbol: str, exit_price: float):
        """Record a position close and update daily P&L."""
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]
        pnl = (exit_price - pos.entry_price) * pos.qty * 100

        self.daily_pnl += pnl
        if pnl > 0:
            self.wins_today += 1
        else:
            self.losses_today += 1

        logger.info(f"Position closed: {symbol} | PnL: ${pnl:+.2f} | "
                     f"Daily PnL: ${self.daily_pnl:+.2f}")

        del self.positions[symbol]

        # Check if we should halt
        if self.daily_pnl <= -self.config.max_daily_loss:
            self.is_halted = True
            logger.warning(f"TRADING HALTED: Daily loss ${self.daily_pnl:.2f} "
                            f"exceeds limit ${self.config.max_daily_loss:.2f}")

    def get_daily_summary(self) -> dict:
        """Get summary of today's trading."""
        return {
            "daily_pnl": self.daily_pnl,
            "trades": self.trades_today,
            "wins": self.wins_today,
            "losses": self.losses_today,
            "win_rate": self.wins_today / max(1, self.trades_today) * 100,
            "open_positions": len(self.positions),
            "is_halted": self.is_halted,
        }

    def reset_daily(self):
        """Reset daily stats (call at start of each trading day)."""
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.wins_today = 0
        self.losses_today = 0
        self.is_halted = False
        logger.info("Daily risk stats reset")

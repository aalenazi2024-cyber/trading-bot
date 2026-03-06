"""Risk management for all-in 0DTE compounding strategy.

Plan: $50K starting equity, all-in each trade, target 30% per trade,
compound gains, trade as many times as opportunities arise.

The bot picks the highest-conviction signal and goes all-in.
After each trade (win or loss), it looks for the next opportunity.
No daily trade limit — trades all day as long as there's equity.
"""

from dataclasses import dataclass
from datetime import datetime
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
        return self.entry_price * self.qty * 100

    def update_trailing_stop(self, current_price: float, trailing_pct: float):
        """Update trailing stop as price moves up."""
        if current_price > self.highest_price:
            self.highest_price = current_price
            new_stop = self.highest_price * (1 - trailing_pct / 100)
            # Only ratchet up, never down
            if new_stop > self.stop_loss:
                self.stop_loss = new_stop


class RiskManager:
    """
    All-in risk manager for maximum compounding.

    Key behaviors:
    - Uses full account equity for each trade (95% default)
    - Only ONE position at a time (all-in)
    - Targets 30% per trade
    - Unlimited trades per day — keeps trading as long as there's equity
    - Trailing stop activates at 15% gain to lock profits
    - Compounds all gains into the next trade
    - Tracks progress toward $200M goal
    """

    def __init__(self, config: RiskConfig):
        self.config = config
        self.positions: dict[str, Position] = {}
        self.daily_pnl: float = 0.0
        self.trades_today: int = 0
        self.wins_today: int = 0
        self.losses_today: int = 0
        self.is_halted: bool = False
        self.starting_equity: float = 0.0
        self.current_equity: float = 0.0

    def can_open_position(self) -> tuple[bool, str]:
        """Check if we're allowed to open a new position."""
        if self.is_halted:
            return False, "Trading halted for the day"

        # All-in = only 1 position at a time
        if len(self.positions) >= self.config.max_open_positions:
            return False, "Already in a position (all-in mode)"

        # Check if we hit our goal
        if self.current_equity >= self.config.account_goal:
            logger.info(f"GOAL REACHED: ${self.current_equity:,.2f} >= "
                         f"${self.config.account_goal:,.2f}")
            return False, "GOAL REACHED"

        return True, "OK"

    def calculate_position_size(self, option_price: float, buying_power: float) -> int:
        """
        ALL-IN position sizing.

        Uses 95% of available equity to maximize each trade.
        Every dollar works on every trade for maximum compounding.
        """
        if option_price <= 0:
            return 0

        cost_per_contract = option_price * 100  # Options = 100 multiplier

        # All-in: use configured percentage of buying power
        if self.config.max_position_size > 0:
            available = min(self.config.max_position_size, buying_power)
        else:
            available = buying_power * (self.config.account_equity_pct / 100)

        contracts = int(available / cost_per_contract)

        # Cap at max contracts if set
        if self.config.max_contracts_per_trade > 0:
            contracts = min(contracts, self.config.max_contracts_per_trade)

        if contracts < 1:
            logger.warning(f"Cannot afford even 1 contract at ${option_price:.2f} "
                            f"(need ${cost_per_contract:.2f}, have ${available:.2f})")
            return 0

        logger.info(f"ALL-IN SIZING: {contracts} contracts @ ${option_price:.2f} = "
                     f"${contracts * cost_per_contract:,.2f} "
                     f"({available / buying_power * 100:.0f}% of buying power)")

        return contracts

    def calculate_stops(self, entry_price: float) -> tuple[float, float]:
        """
        Calculate stop loss and profit target.

        Target: 30-50% profit (configurable, default 40%)
        Stop: 40% loss (give room for 0DTE volatility)
        """
        stop_loss = entry_price * (1 - self.config.stop_loss_pct / 100)
        profit_target = entry_price * (1 + self.config.profit_target_pct / 100)

        return max(0.01, stop_loss), profit_target

    def register_position(self, symbol: str, option_type: str, strike: float,
                          entry_price: float, qty: int, strategy: str) -> Position:
        """Register a new all-in position."""
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

        cost = entry_price * qty * 100
        target_gain = (profit_target - entry_price) * qty * 100
        max_loss = (entry_price - stop_loss) * qty * 100

        logger.info("=" * 60)
        logger.info(f"ALL-IN TRADE #{self.trades_today}")
        logger.info(f"  {qty}x {symbol} @ ${entry_price:.2f}")
        logger.info(f"  Cost: ${cost:,.2f}")
        logger.info(f"  Stop Loss: ${stop_loss:.2f} (max loss: ${max_loss:,.2f})")
        logger.info(f"  Target: ${profit_target:.2f} (potential gain: ${target_gain:,.2f})")
        logger.info(f"  Strategy: {strategy}")
        logger.info("=" * 60)

        return position

    def check_exit_signals(self, symbol: str, current_price: float) -> tuple[bool, str]:
        """Check if position should be exited."""
        if symbol not in self.positions:
            return False, "Position not found"

        pos = self.positions[symbol]
        gain_pct = (current_price - pos.entry_price) / pos.entry_price * 100

        # Activate trailing stop after threshold gain
        if gain_pct >= self.config.trailing_activation_pct:
            pos.update_trailing_stop(current_price, self.config.trailing_stop_pct)

        # Check profit target (40% gain)
        if current_price >= pos.profit_target:
            pnl = (current_price - pos.entry_price) * pos.qty * 100
            return True, (f"PROFIT TARGET HIT +{gain_pct:.1f}% | "
                          f"${current_price:.2f} >= ${pos.profit_target:.2f} | "
                          f"PnL: ${pnl:+,.2f}")

        # Check stop loss
        if current_price <= pos.stop_loss:
            pnl = (current_price - pos.entry_price) * pos.qty * 100
            return True, (f"STOP LOSS HIT {gain_pct:.1f}% | "
                          f"${current_price:.2f} <= ${pos.stop_loss:.2f} | "
                          f"PnL: ${pnl:+,.2f}")

        # Check trailing stop (only if activated)
        if pos.highest_price > pos.entry_price * (1 + self.config.trailing_activation_pct / 100):
            trailing_stop = pos.highest_price * (1 - self.config.trailing_stop_pct / 100)
            if current_price <= trailing_stop:
                pnl = (current_price - pos.entry_price) * pos.qty * 100
                return True, (f"TRAILING STOP at +{gain_pct:.1f}% | "
                              f"high was ${pos.highest_price:.2f} | "
                              f"PnL: ${pnl:+,.2f}")

        # Option approaching worthless
        if current_price < 0.05:
            return True, "Option nearly worthless — cutting loss"

        return False, f"HOLDING +{gain_pct:+.1f}%"

    def should_scale_in(self, symbol: str, current_price: float) -> bool:
        """No scale-in in all-in mode — already fully deployed."""
        return False

    def record_close(self, symbol: str, exit_price: float):
        """Record a position close, update P&L and equity."""
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]
        pnl = (exit_price - pos.entry_price) * pos.qty * 100
        pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100

        self.daily_pnl += pnl
        self.current_equity += pnl

        if pnl > 0:
            self.wins_today += 1
        else:
            self.losses_today += 1

        logger.info("=" * 60)
        if pnl > 0:
            logger.info(f"WINNER! +${pnl:,.2f} (+{pnl_pct:.1f}%)")
        else:
            logger.info(f"LOSS: ${pnl:,.2f} ({pnl_pct:.1f}%)")
        logger.info(f"  Daily PnL: ${self.daily_pnl:+,.2f}")
        logger.info(f"  Account Equity: ${self.current_equity:,.2f}")
        logger.info(f"  Goal Progress: ${self.current_equity:,.0f} / "
                     f"${self.config.account_goal:,.0f} "
                     f"({self.current_equity / self.config.account_goal * 100:.4f}%)")
        logger.info("=" * 60)

        del self.positions[symbol]

        # Keep trading — look for the next opportunity
        if pnl < 0:
            logger.warning(f"Loss taken. Looking for next opportunity. "
                            f"Remaining equity: ${self.current_equity:,.2f}")

    def set_account_equity(self, equity: float):
        """Set current account equity (called on startup)."""
        self.starting_equity = equity
        self.current_equity = equity
        logger.info(f"Account equity: ${equity:,.2f}")
        logger.info(f"Goal: ${self.config.account_goal:,.2f}")
        logger.info(f"Progress: {equity / self.config.account_goal * 100:.4f}%")

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
            "current_equity": self.current_equity,
            "starting_equity": self.starting_equity,
            "goal": self.config.account_goal,
            "goal_pct": self.current_equity / max(1, self.config.account_goal) * 100,
        }

    def reset_daily(self):
        """Reset daily stats (call at start of each trading day)."""
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.wins_today = 0
        self.losses_today = 0
        self.is_halted = False
        logger.info("Daily stats reset. Equity carries forward for compounding.")
        logger.info(f"Today's starting equity: ${self.current_equity:,.2f}")

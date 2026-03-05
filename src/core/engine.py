"""Core trading engine - orchestrates strategies, risk, and execution."""

import time
from datetime import datetime, date
from typing import Optional

from loguru import logger

from src.core.config import BotConfig
from src.core.broker import AlpacaBroker
from src.core.risk_manager import RiskManager
from src.core.option_selector import OptionSelector
from src.data.market_data import MarketData
from src.strategies.base import Signal, BaseStrategy
from src.strategies.opening_range_breakout import OpeningRangeBreakout
from src.strategies.vwap_strategy import VWAPStrategy
from src.strategies.momentum_scalp import MomentumScalp
from src.strategies.mean_reversion import MeanReversion


class TradingEngine:
    """
    Main engine that runs the 0DTE SPX trading bot.

    Flow:
    1. Fetch latest market data
    2. Run all enabled strategies
    3. Take the strongest signal
    4. Execute trade with proper sizing
    5. Monitor positions for exits
    6. Repeat until market close
    """

    def __init__(self, config: BotConfig):
        self.config = config
        self.broker = AlpacaBroker(config)
        self.risk_manager = RiskManager(config.risk)
        self.market_data = MarketData(self.broker.api)
        self.option_selector = OptionSelector(self.broker, config.risk)
        self.strategies: list[BaseStrategy] = []
        self._init_strategies()

    def _init_strategies(self):
        """Initialize enabled strategies."""
        cfg = self.config.strategy

        if cfg.orb_enabled:
            self.strategies.append(
                OpeningRangeBreakout(cfg.orb_range_minutes, cfg.orb_breakout_threshold)
            )
            logger.info("Strategy enabled: Opening Range Breakout")

        if cfg.vwap_enabled:
            self.strategies.append(
                VWAPStrategy(cfg.vwap_bounce_threshold, cfg.vwap_confirmation_candles)
            )
            logger.info("Strategy enabled: VWAP Bounce/Rejection")

        if cfg.momentum_enabled:
            self.strategies.append(
                MomentumScalp(cfg.momentum_lookback, cfg.momentum_min_move)
            )
            logger.info("Strategy enabled: Momentum Scalp")

        if cfg.mean_reversion_enabled:
            self.strategies.append(
                MeanReversion(cfg.mean_reversion_std_threshold, cfg.mean_reversion_lookback)
            )
            logger.info("Strategy enabled: Mean Reversion")

    def is_trading_hours(self) -> bool:
        """Check if current time is within trading window."""
        now = datetime.now()
        h = self.config.hours

        trading_start = now.replace(hour=h.trading_start_hour, minute=h.trading_start_minute,
                                    second=0, microsecond=0)
        last_entry = now.replace(hour=h.last_entry_hour, minute=h.last_entry_minute,
                                 second=0, microsecond=0)

        return trading_start <= now <= last_entry

    def is_force_close_time(self) -> bool:
        """Check if we should force close all positions."""
        now = datetime.now()
        h = self.config.hours
        force_close = now.replace(hour=h.force_close_hour, minute=h.force_close_minute,
                                  second=0, microsecond=0)
        return now >= force_close

    def run_cycle(self):
        """
        Run one complete trading cycle:
        1. Update data
        2. Check existing positions
        3. Look for new entries
        """
        try:
            # Update market data
            self.market_data.fetch_intraday_bars()

            # Monitor and manage existing positions
            self._manage_positions()

            # Force close near end of day
            if self.is_force_close_time():
                self._force_close_all()
                return

            # Look for new entry signals
            if self.is_trading_hours():
                self._scan_for_entries()

        except Exception as e:
            logger.error(f"Error in trading cycle: {e}")

    def _scan_for_entries(self):
        """Run all strategies and take the best signal."""
        can_trade, reason = self.risk_manager.can_open_position()
        if not can_trade:
            logger.debug(f"Cannot open position: {reason}")
            return

        signals: list[Signal] = []

        for strategy in self.strategies:
            try:
                signal = strategy.evaluate(self.market_data)
                if signal and signal.strength >= 0.5:  # Min strength threshold
                    signals.append(signal)
            except Exception as e:
                logger.error(f"Strategy {strategy.name} error: {e}")

        if not signals:
            return

        # Take the strongest signal
        best_signal = max(signals, key=lambda s: s.strength)
        logger.info(f"Best signal: {best_signal.strategy_name} | "
                     f"{best_signal.direction.upper()} | "
                     f"Strength: {best_signal.strength:.2f} | "
                     f"Reason: {best_signal.reason}")

        self._execute_signal(best_signal)

    def _execute_signal(self, signal: Signal):
        """Execute a trade based on a strategy signal."""
        current_price = self.market_data.get_latest_price()

        # Select option contract
        contract = self.option_selector.select_contract(
            current_price=current_price,
            direction=signal.direction,
            strike_offset=signal.strike_offset,
        )

        if not contract:
            logger.warning("No suitable contract found")
            return

        # Get contract price
        option_price = self.option_selector.get_contract_price(contract)
        if not self.option_selector.validate_contract(contract, option_price):
            return

        # Calculate position size
        buying_power = self.broker.get_buying_power()
        qty = self.risk_manager.calculate_position_size(option_price, buying_power)

        if qty <= 0:
            logger.warning("Position size is 0, insufficient funds")
            return

        symbol = contract.get("symbol", "")

        # Place order
        order = self.broker.buy_option(
            symbol=symbol,
            qty=qty,
            order_type="limit",
            limit_price=round(option_price * 1.02, 2),  # 2% slippage allowance
        )

        if not order:
            return

        # Wait for fill
        filled_order = self.broker.wait_for_fill(order.id, timeout=15)
        if not filled_order or filled_order.status != "filled":
            logger.warning(f"Order not filled, canceling")
            try:
                self.broker.api.cancel_order(order.id)
            except Exception:
                pass
            return

        # Register position with risk manager
        fill_price = float(filled_order.filled_avg_price)
        strike = float(contract.get("strike_price", 0))

        self.risk_manager.register_position(
            symbol=symbol,
            option_type=signal.direction,
            strike=strike,
            entry_price=fill_price,
            qty=qty,
            strategy=signal.strategy_name,
        )

    def _manage_positions(self):
        """Monitor open positions and handle exits."""
        positions_to_close = []

        for symbol, position in self.risk_manager.positions.items():
            try:
                quote = self.broker.get_option_quote(symbol)
                if not quote:
                    continue

                bid = float(quote.get("bid_price", 0) or 0)
                ask = float(quote.get("ask_price", 0) or 0)
                current_price = (bid + ask) / 2 if bid > 0 and ask > 0 else bid or ask

                if current_price <= 0:
                    continue

                should_exit, reason = self.risk_manager.check_exit_signals(symbol, current_price)

                if should_exit:
                    logger.info(f"EXIT SIGNAL for {symbol}: {reason}")
                    positions_to_close.append((symbol, position.qty, current_price))

                # Check for scale-in opportunity
                elif self.risk_manager.should_scale_in(symbol, current_price):
                    self._scale_in(symbol, position, current_price)

            except Exception as e:
                logger.error(f"Error managing position {symbol}: {e}")

        # Execute closes
        for symbol, qty, price in positions_to_close:
            order = self.broker.sell_option(symbol, qty)
            if order:
                filled = self.broker.wait_for_fill(order.id, timeout=15)
                exit_price = float(filled.filled_avg_price) if filled and filled.status == "filled" else price
                self.risk_manager.record_close(symbol, exit_price)

    def _scale_in(self, symbol: str, position, current_price: float):
        """Add to a winning position."""
        can_trade, _ = self.risk_manager.can_open_position()
        if not can_trade:
            return

        # Add half the original position size
        additional_qty = max(1, position.qty // 2)
        buying_power = self.broker.get_buying_power()
        cost = current_price * additional_qty * 100

        if cost > buying_power * 0.5:
            return

        logger.info(f"SCALING IN: Adding {additional_qty}x {symbol} @ ${current_price:.2f}")
        order = self.broker.buy_option(symbol, additional_qty, "limit",
                                        round(current_price * 1.02, 2))
        if order:
            filled = self.broker.wait_for_fill(order.id, timeout=10)
            if filled and filled.status == "filled":
                position.qty += additional_qty
                logger.info(f"Scale-in filled. New qty: {position.qty}")

    def _force_close_all(self):
        """Force close all positions near end of day."""
        if not self.risk_manager.positions:
            return

        logger.warning("FORCE CLOSING ALL POSITIONS - End of day")
        for symbol, position in list(self.risk_manager.positions.items()):
            order = self.broker.sell_option(symbol, position.qty)
            if order:
                filled = self.broker.wait_for_fill(order.id, timeout=30)
                if filled and filled.status == "filled":
                    self.risk_manager.record_close(symbol, float(filled.filled_avg_price))
                else:
                    # Emergency market order
                    self.broker.sell_option(symbol, position.qty, "market")
                    self.risk_manager.record_close(symbol, 0.01)

    def print_status(self):
        """Print current bot status."""
        summary = self.risk_manager.get_daily_summary()
        logger.info("=" * 60)
        logger.info(f"DAILY P&L: ${summary['daily_pnl']:+.2f}")
        logger.info(f"Trades: {summary['trades']} | "
                     f"Wins: {summary['wins']} | "
                     f"Losses: {summary['losses']} | "
                     f"Win Rate: {summary['win_rate']:.0f}%")
        logger.info(f"Open Positions: {summary['open_positions']}")
        logger.info(f"Halted: {summary['is_halted']}")
        logger.info("=" * 60)

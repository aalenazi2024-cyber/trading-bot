#!/usr/bin/env python3
"""
0DTE SPX Options Trading Bot
=============================

Automated bot that trades 0-day-to-expiration SPX options using
multiple proven strategies for maximum risk and maximum reward.

Strategies:
1. Opening Range Breakout (ORB) - Trades breakouts from the first 15 min range
2. VWAP Bounce/Rejection - Trades bounces off the institutional VWAP level
3. Momentum Scalp - Catches strong directional moves
4. Mean Reversion - Fades extreme overextended moves

WARNING: This bot trades with aggressive settings. 0DTE options can lose
100% of their value in minutes. Only use money you can afford to lose.

Setup:
1. Copy .env.example to .env
2. Add your Alpaca API keys
3. Start with TRADING_MODE=paper
4. Run: python main.py

Usage:
    python main.py              # Run the bot
    python main.py --paper      # Force paper trading mode
    python main.py --once       # Run one cycle and exit (for testing)
"""

import sys
import time
import signal
import argparse
from datetime import datetime, date

from loguru import logger

from src.core.config import BotConfig
from src.core.engine import TradingEngine


# Configure logging
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
)
logger.add(
    "logs/trading_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="DEBUG",
)


class TradingBot:
    """Main bot runner with scheduling and lifecycle management."""

    def __init__(self, paper_mode: bool = False):
        self.config = BotConfig()
        if paper_mode:
            self.config.broker.base_url = "https://paper-api.alpaca.markets"
            self.config.broker.trading_mode = "paper"

        self.engine: TradingEngine = None
        self.running = False

    def start(self):
        """Initialize and start the trading bot."""
        logger.info("=" * 60)
        logger.info("  0DTE SPX OPTIONS TRADING BOT")
        logger.info(f"  Mode: {self.config.broker.trading_mode.upper()}")
        logger.info(f"  Date: {date.today()}")
        logger.info(f"  Max Position Size: ${self.config.risk.max_position_size:,.0f}")
        logger.info(f"  Max Daily Loss: ${self.config.risk.max_daily_loss:,.0f}")
        logger.info(f"  Profit Target: {self.config.risk.profit_target_pct}%")
        logger.info(f"  Stop Loss: {self.config.risk.stop_loss_pct}%")
        logger.info("=" * 60)

        # Validate API keys
        if not self.config.broker.api_key or not self.config.broker.secret_key:
            logger.error("API keys not set! Copy .env.example to .env and add your keys.")
            sys.exit(1)

        try:
            self.engine = TradingEngine(self.config)
            logger.info("Trading engine initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize engine: {e}")
            sys.exit(1)

        # Print enabled strategies
        for strategy in self.engine.strategies:
            logger.info(f"  Active Strategy: {strategy.name}")

        self.running = True
        logger.info("Bot started. Waiting for trading hours...")

    def run(self, single_cycle: bool = False):
        """Main trading loop."""
        self.start()

        # Set up graceful shutdown
        signal.signal(signal.SIGINT, self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)

        cycle_count = 0
        status_interval = 30  # Print status every 30 cycles

        while self.running:
            try:
                now = datetime.now()
                h = self.config.hours

                # Only run during market hours (9:30 AM - 4:00 PM ET)
                market_open = now.replace(hour=h.market_open_hour,
                                          minute=h.market_open_minute,
                                          second=0)
                market_close = now.replace(hour=h.market_close_hour,
                                           minute=h.market_close_minute,
                                           second=0)

                if now < market_open:
                    wait_seconds = (market_open - now).total_seconds()
                    logger.info(f"Market not open yet. Waiting {wait_seconds/60:.0f} minutes...")
                    time.sleep(min(wait_seconds, 60))
                    continue

                if now > market_close:
                    logger.info("Market closed. Printing final summary.")
                    self.engine.print_status()
                    if not single_cycle:
                        logger.info("Waiting for next trading day...")
                        self.engine.risk_manager.reset_daily()
                        time.sleep(3600)  # Sleep 1 hour then re-check
                    break

                # Run trading cycle
                self.engine.run_cycle()
                cycle_count += 1

                # Periodic status update
                if cycle_count % status_interval == 0:
                    self.engine.print_status()

                if single_cycle:
                    self.engine.print_status()
                    break

                # Wait before next cycle (poll every 15 seconds for responsive trading)
                time.sleep(15)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                time.sleep(30)

        self._shutdown()

    def _shutdown_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.warning(f"Received signal {signum}, shutting down...")
        self.running = False

    def _shutdown(self):
        """Clean shutdown: close positions and print summary."""
        logger.info("Shutting down trading bot...")

        if self.engine:
            # Close all remaining positions
            if self.engine.risk_manager.positions:
                logger.warning("Closing all open positions before shutdown...")
                self.engine._force_close_all()

            self.engine.print_status()

        logger.info("Bot shutdown complete.")


def main():
    parser = argparse.ArgumentParser(description="0DTE SPX Options Trading Bot")
    parser.add_argument("--paper", action="store_true",
                        help="Force paper trading mode")
    parser.add_argument("--once", action="store_true",
                        help="Run single cycle then exit (for testing)")
    args = parser.parse_args()

    bot = TradingBot(paper_mode=args.paper)
    bot.run(single_cycle=args.once)


if __name__ == "__main__":
    main()

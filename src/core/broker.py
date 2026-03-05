"""Broker interface for Alpaca options trading."""

import time
from datetime import datetime, date
from typing import Optional

from loguru import logger

try:
    import alpaca_trade_api as tradeapi
    from alpaca_trade_api.rest import APIError
except ImportError:
    tradeapi = None
    APIError = Exception

from src.core.config import BotConfig


class AlpacaBroker:
    """Handles all broker interactions for SPX 0DTE options."""

    def __init__(self, config: BotConfig):
        self.config = config
        if tradeapi is None:
            raise ImportError("alpaca-trade-api is required. Run: pip install alpaca-trade-api")
        self.api = tradeapi.REST(
            key_id=config.broker.api_key,
            secret_key=config.broker.secret_key,
            base_url=config.broker.base_url,
        )
        self._validate_connection()

    def _validate_connection(self):
        """Verify API connection and account status."""
        try:
            account = self.api.get_account()
            logger.info(f"Connected to Alpaca ({self.config.broker.trading_mode} mode)")
            logger.info(f"Account equity: ${float(account.equity):,.2f}")
            logger.info(f"Buying power: ${float(account.buying_power):,.2f}")
            if account.trading_blocked:
                raise RuntimeError("Account trading is blocked")
        except APIError as e:
            raise ConnectionError(f"Failed to connect to Alpaca: {e}")

    def get_account(self):
        """Get current account info."""
        return self.api.get_account()

    def get_buying_power(self) -> float:
        """Get available buying power."""
        account = self.api.get_account()
        return float(account.buying_power)

    def get_spx_price(self) -> float:
        """Get current SPX price via snapshot."""
        try:
            snapshot = self.api.get_snapshot("SPY")
            # SPY is ~1/10th of SPX, multiply by 10 for approximate SPX
            spy_price = float(snapshot.latest_trade.price)
            return spy_price * 10.0
        except Exception as e:
            logger.error(f"Error getting SPX price: {e}")
            raise

    def get_options_chain(self, expiration: str, option_type: str = "call",
                          strike_price_gte: Optional[float] = None,
                          strike_price_lte: Optional[float] = None,
                          limit: int = 50):
        """
        Get SPX options chain for a given expiration.

        Args:
            expiration: Date string YYYY-MM-DD
            option_type: "call" or "put"
            strike_price_gte: Min strike price
            strike_price_lte: Max strike price
            limit: Max number of contracts to return
        """
        try:
            params = {
                "underlying_symbols": "SPXW",  # SPX weeklies (0DTE)
                "expiration_date": expiration,
                "type": option_type,
                "limit": limit,
                "status": "active",
            }
            if strike_price_gte:
                params["strike_price_gte"] = str(strike_price_gte)
            if strike_price_lte:
                params["strike_price_lte"] = str(strike_price_lte)

            # Use Alpaca options API
            response = self.api.get(
                "/v2/options/contracts",
                data=params,
            )
            return response
        except Exception as e:
            logger.error(f"Error fetching options chain: {e}")
            return []

    def get_option_quote(self, symbol: str) -> dict:
        """Get latest quote for an option contract."""
        try:
            response = self.api.get(f"/v2/options/contracts/{symbol}")
            return response
        except Exception as e:
            logger.error(f"Error getting option quote for {symbol}: {e}")
            return {}

    def buy_option(self, symbol: str, qty: int, order_type: str = "market",
                   limit_price: Optional[float] = None) -> Optional[dict]:
        """
        Buy an option contract.

        Args:
            symbol: Option contract symbol
            qty: Number of contracts
            order_type: "market" or "limit"
            limit_price: Limit price (required for limit orders)
        """
        try:
            order_params = {
                "symbol": symbol,
                "qty": str(qty),
                "side": "buy",
                "type": order_type,
                "time_in_force": "day",
            }
            if order_type == "limit" and limit_price:
                order_params["limit_price"] = str(limit_price)

            logger.info(f"BUYING {qty}x {symbol} @ {order_type} {limit_price or ''}")
            order = self.api.submit_order(**order_params)
            logger.info(f"Order submitted: {order.id} - Status: {order.status}")
            return order
        except APIError as e:
            logger.error(f"Order failed: {e}")
            return None

    def sell_option(self, symbol: str, qty: int, order_type: str = "market",
                    limit_price: Optional[float] = None) -> Optional[dict]:
        """Sell (close) an option position."""
        try:
            order_params = {
                "symbol": symbol,
                "qty": str(qty),
                "side": "sell",
                "type": order_type,
                "time_in_force": "day",
            }
            if order_type == "limit" and limit_price:
                order_params["limit_price"] = str(limit_price)

            logger.info(f"SELLING {qty}x {symbol} @ {order_type} {limit_price or ''}")
            order = self.api.submit_order(**order_params)
            logger.info(f"Sell order submitted: {order.id} - Status: {order.status}")
            return order
        except APIError as e:
            logger.error(f"Sell order failed: {e}")
            return None

    def get_positions(self) -> list:
        """Get all open positions."""
        try:
            return self.api.list_positions()
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []

    def get_option_positions(self) -> list:
        """Get only option positions."""
        positions = self.get_positions()
        return [p for p in positions if hasattr(p, 'asset_class') and p.asset_class == 'options']

    def close_position(self, symbol: str) -> bool:
        """Close an entire position by symbol."""
        try:
            self.api.close_position(symbol)
            logger.info(f"Closed position: {symbol}")
            return True
        except APIError as e:
            logger.error(f"Failed to close position {symbol}: {e}")
            return False

    def close_all_positions(self) -> bool:
        """Emergency: close all positions."""
        try:
            self.api.close_all_positions()
            logger.warning("CLOSED ALL POSITIONS")
            return True
        except APIError as e:
            logger.error(f"Failed to close all positions: {e}")
            return False

    def get_order_status(self, order_id: str) -> Optional[dict]:
        """Check status of a specific order."""
        try:
            return self.api.get_order(order_id)
        except Exception as e:
            logger.error(f"Error getting order {order_id}: {e}")
            return None

    def wait_for_fill(self, order_id: str, timeout: int = 30) -> Optional[dict]:
        """Wait for an order to fill."""
        start = time.time()
        while time.time() - start < timeout:
            order = self.get_order_status(order_id)
            if order and order.status == "filled":
                logger.info(f"Order {order_id} filled at {order.filled_avg_price}")
                return order
            if order and order.status in ("canceled", "expired", "rejected"):
                logger.warning(f"Order {order_id} ended with status: {order.status}")
                return order
            time.sleep(1)
        logger.warning(f"Order {order_id} not filled within {timeout}s")
        return None

    def get_today_expiration(self) -> str:
        """Get today's date as expiration string for 0DTE."""
        return date.today().strftime("%Y-%m-%d")

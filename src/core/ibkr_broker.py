"""Interactive Brokers (IBKR) broker interface for SPX 0DTE options trading.

Connects to IBKR via TWS/IB Gateway using the ib_insync library.

Prerequisites:
1. Install TWS or IB Gateway
2. Enable API connections in TWS: Configure > API > Settings
   - Check "Enable ActiveX and Socket Clients"
   - Set Socket port (default 7497 for paper, 7496 for live)
   - Add 127.0.0.1 to trusted IPs
3. Enable SPX options trading permissions in your IBKR account
"""

import time
from datetime import datetime, date
from typing import Optional

from loguru import logger

try:
    from ib_insync import (
        IB, Stock, Index, Option, Contract,
        MarketOrder, LimitOrder,
        util,
    )
    IB_AVAILABLE = True
except ImportError:
    IB_AVAILABLE = False

from src.core.config import BotConfig


class IBKRBroker:
    """Handles all IBKR interactions for SPX 0DTE options."""

    def __init__(self, config: BotConfig):
        self.config = config
        if not IB_AVAILABLE:
            raise ImportError(
                "ib_insync is required for IBKR. Run: pip install ib_insync"
            )
        self.ib = IB()
        self._connect()

    def _connect(self):
        """Connect to TWS / IB Gateway."""
        ibkr = self.config.ibkr
        try:
            self.ib.connect(
                host=ibkr.host,
                port=ibkr.port,
                clientId=ibkr.client_id,
                readonly=False,
            )
            logger.info(f"Connected to IBKR at {ibkr.host}:{ibkr.port} "
                         f"(clientId={ibkr.client_id})")
            self._validate_connection()
        except Exception as e:
            raise ConnectionError(f"Failed to connect to IBKR: {e}")

    def _validate_connection(self):
        """Verify connection and account."""
        account_values = self.ib.accountSummary()
        for av in account_values:
            if av.tag == "NetLiquidation":
                logger.info(f"IBKR Account: {av.account} | "
                             f"Net Liquidation: ${float(av.value):,.2f}")
            if av.tag == "BuyingPower":
                logger.info(f"Buying Power: ${float(av.value):,.2f}")

    def disconnect(self):
        """Disconnect from IBKR."""
        if self.ib.isConnected():
            self.ib.disconnect()
            logger.info("Disconnected from IBKR")

    def get_buying_power(self) -> float:
        """Get available buying power."""
        for av in self.ib.accountSummary():
            if av.tag == "BuyingPower":
                return float(av.value)
        return 0.0

    def get_spx_price(self) -> float:
        """Get current SPX index price."""
        spx = Index("SPX", "CBOE")
        self.ib.qualifyContracts(spx)
        self.ib.reqMktData(spx)
        self.ib.sleep(1)  # Wait for data
        ticker = self.ib.ticker(spx)
        if ticker and ticker.last and ticker.last > 0:
            return ticker.last
        if ticker and ticker.close and ticker.close > 0:
            return ticker.close
        raise RuntimeError("Could not get SPX price from IBKR")

    def get_options_chain(self, expiration: str, option_type: str = "call",
                          strike_price_gte: Optional[float] = None,
                          strike_price_lte: Optional[float] = None,
                          limit: int = 50) -> list:
        """
        Get SPX options chain for today (0DTE).

        Args:
            expiration: YYYY-MM-DD format
            option_type: "call" or "put"
            strike_price_gte: Min strike
            strike_price_lte: Max strike
            limit: Max contracts to return
        """
        try:
            # IBKR uses YYYYMMDD format
            exp_formatted = expiration.replace("-", "")
            right = "C" if option_type == "call" else "P"

            # Get SPX option chains
            spx = Index("SPX", "CBOE")
            self.ib.qualifyContracts(spx)
            chains = self.ib.reqSecDefOptParams(
                spx.symbol, "", spx.secType, spx.conId
            )

            if not chains:
                logger.warning("No option chains returned from IBKR")
                return []

            # Find the SPXW (weekly) chain or SPX chain
            target_chain = None
            for chain in chains:
                if exp_formatted in chain.expirations:
                    target_chain = chain
                    break

            if not target_chain:
                logger.warning(f"No chain found for expiration {expiration}")
                return []

            # Filter strikes
            strikes = sorted(target_chain.strikes)
            if strike_price_gte:
                strikes = [s for s in strikes if s >= strike_price_gte]
            if strike_price_lte:
                strikes = [s for s in strikes if s <= strike_price_lte]

            # Limit number of strikes
            strikes = strikes[:limit]

            # Build contract objects
            contracts = []
            for strike in strikes:
                contract = Option(
                    symbol="SPX",
                    lastTradeDateOrContractMonth=exp_formatted,
                    strike=strike,
                    right=right,
                    exchange="SMART",
                    multiplier="100",
                )
                contracts.append({
                    "symbol": f"SPX{exp_formatted}{right}{int(strike)}",
                    "strike_price": strike,
                    "option_type": option_type,
                    "expiration": expiration,
                    "ib_contract": contract,
                })

            return contracts

        except Exception as e:
            logger.error(f"Error fetching IBKR options chain: {e}")
            return []

    def get_option_quote(self, symbol: str, ib_contract=None) -> dict:
        """Get latest quote for an option contract."""
        try:
            if ib_contract is None:
                # Parse symbol to reconstruct contract
                ib_contract = self._parse_option_symbol(symbol)
                if not ib_contract:
                    return {}

            self.ib.qualifyContracts(ib_contract)
            self.ib.reqMktData(ib_contract)
            self.ib.sleep(0.5)

            ticker = self.ib.ticker(ib_contract)
            if not ticker:
                return {}

            return {
                "bid_price": ticker.bid if ticker.bid and ticker.bid > 0 else 0,
                "ask_price": ticker.ask if ticker.ask and ticker.ask > 0 else 0,
                "last_price": ticker.last if ticker.last and ticker.last > 0 else 0,
                "volume": ticker.volume or 0,
            }
        except Exception as e:
            logger.error(f"Error getting IBKR option quote for {symbol}: {e}")
            return {}

    def buy_option(self, symbol: str, qty: int, order_type: str = "market",
                   limit_price: Optional[float] = None,
                   ib_contract=None) -> Optional[object]:
        """Buy an option contract via IBKR."""
        try:
            if ib_contract is None:
                ib_contract = self._parse_option_symbol(symbol)
                if not ib_contract:
                    logger.error(f"Cannot parse contract from symbol: {symbol}")
                    return None

            self.ib.qualifyContracts(ib_contract)

            if order_type == "limit" and limit_price:
                order = LimitOrder("BUY", qty, limit_price)
            else:
                order = MarketOrder("BUY", qty)

            logger.info(f"IBKR BUYING {qty}x {symbol} @ {order_type} "
                         f"{limit_price or ''}")

            trade = self.ib.placeOrder(ib_contract, order)
            self.ib.sleep(0.5)

            logger.info(f"IBKR Order placed: {trade.order.orderId} - "
                         f"Status: {trade.orderStatus.status}")

            # Wrap in a compatible object
            return _IBKROrder(trade)

        except Exception as e:
            logger.error(f"IBKR order failed: {e}")
            return None

    def sell_option(self, symbol: str, qty: int, order_type: str = "market",
                    limit_price: Optional[float] = None,
                    ib_contract=None) -> Optional[object]:
        """Sell (close) an option position via IBKR."""
        try:
            if ib_contract is None:
                ib_contract = self._parse_option_symbol(symbol)
                if not ib_contract:
                    return None

            self.ib.qualifyContracts(ib_contract)

            if order_type == "limit" and limit_price:
                order = LimitOrder("SELL", qty, limit_price)
            else:
                order = MarketOrder("SELL", qty)

            logger.info(f"IBKR SELLING {qty}x {symbol} @ {order_type} "
                         f"{limit_price or ''}")

            trade = self.ib.placeOrder(ib_contract, order)
            self.ib.sleep(0.5)

            return _IBKROrder(trade)

        except Exception as e:
            logger.error(f"IBKR sell order failed: {e}")
            return None

    def get_positions(self) -> list:
        """Get all open positions."""
        try:
            return self.ib.positions()
        except Exception as e:
            logger.error(f"Error getting IBKR positions: {e}")
            return []

    def close_all_positions(self) -> bool:
        """Close all open positions."""
        try:
            positions = self.ib.positions()
            for pos in positions:
                if pos.position != 0:
                    side = "SELL" if pos.position > 0 else "BUY"
                    qty = abs(pos.position)
                    order = MarketOrder(side, qty)
                    self.ib.placeOrder(pos.contract, order)
                    logger.info(f"Closing IBKR position: {pos.contract.localSymbol}")
            self.ib.sleep(1)
            return True
        except Exception as e:
            logger.error(f"Error closing IBKR positions: {e}")
            return False

    def get_order_status(self, order_id: str) -> Optional[object]:
        """Check order status."""
        try:
            for trade in self.ib.trades():
                if str(trade.order.orderId) == str(order_id):
                    return _IBKROrder(trade)
            return None
        except Exception as e:
            logger.error(f"Error getting IBKR order {order_id}: {e}")
            return None

    def wait_for_fill(self, order_id: str, timeout: int = 30) -> Optional[object]:
        """Wait for an order to fill."""
        start = time.time()
        while time.time() - start < timeout:
            self.ib.sleep(1)
            for trade in self.ib.trades():
                if str(trade.order.orderId) == str(order_id):
                    if trade.orderStatus.status == "Filled":
                        logger.info(f"IBKR Order {order_id} filled at "
                                     f"{trade.orderStatus.avgFillPrice}")
                        return _IBKROrder(trade)
                    if trade.orderStatus.status in ("Cancelled", "Inactive"):
                        logger.warning(f"IBKR Order {order_id}: "
                                        f"{trade.orderStatus.status}")
                        return _IBKROrder(trade)
        logger.warning(f"IBKR Order {order_id} not filled within {timeout}s")
        return None

    def cancel_order(self, order_id: str):
        """Cancel an open order."""
        for trade in self.ib.trades():
            if str(trade.order.orderId) == str(order_id):
                self.ib.cancelOrder(trade.order)
                return
        logger.warning(f"Order {order_id} not found to cancel")

    def get_today_expiration(self) -> str:
        """Get today's date as expiration string for 0DTE."""
        return date.today().strftime("%Y-%m-%d")

    def _parse_option_symbol(self, symbol: str) -> Optional[object]:
        """Parse our internal symbol format back to an IB contract."""
        try:
            # Look up from stored contracts first
            if hasattr(self, '_contract_cache') and symbol in self._contract_cache:
                return self._contract_cache[symbol]

            # Try to reconstruct: SPX20260305C5800
            if not symbol.startswith("SPX"):
                return None

            rest = symbol[3:]
            exp = rest[:8]
            right = rest[8]
            strike = float(rest[9:])

            contract = Option(
                symbol="SPX",
                lastTradeDateOrContractMonth=exp,
                strike=strike,
                right=right,
                exchange="SMART",
                multiplier="100",
            )
            return contract
        except Exception as e:
            logger.error(f"Cannot parse IBKR symbol {symbol}: {e}")
            return None

    def cache_contract(self, symbol: str, contract):
        """Cache an IB contract object for later use."""
        if not hasattr(self, '_contract_cache'):
            self._contract_cache = {}
        self._contract_cache[symbol] = contract


class _IBKROrder:
    """Wrapper to make IBKR trade objects compatible with our engine interface."""

    def __init__(self, trade):
        self._trade = trade
        self.id = str(trade.order.orderId)

        status_map = {
            "Filled": "filled",
            "Submitted": "submitted",
            "PreSubmitted": "submitted",
            "Cancelled": "canceled",
            "Inactive": "rejected",
        }
        self.status = status_map.get(trade.orderStatus.status,
                                      trade.orderStatus.status.lower())
        self.filled_avg_price = str(trade.orderStatus.avgFillPrice or 0)

"""Option contract selection for 0DTE SPX trades."""

from datetime import date
from typing import Optional

from loguru import logger

from src.core.config import RiskConfig


class OptionSelector:
    """Selects the best option contract for a given signal."""

    def __init__(self, broker, risk_config: RiskConfig):
        self.broker = broker
        self.risk_config = risk_config

    def select_contract(self, current_price: float, direction: str,
                        strike_offset: float = 0.0) -> Optional[dict]:
        """
        Select the best 0DTE option contract.

        Args:
            current_price: Current SPX price
            direction: "call" or "put"
            strike_offset: Points from ATM for strike selection

        Returns:
            Contract info dict or None
        """
        expiration = date.today().strftime("%Y-%m-%d")

        # Calculate target strike (round to nearest 5 for SPX)
        target_strike = round((current_price + strike_offset) / 5) * 5

        # Search range around target strike
        strike_range = 10  # +/- 10 points
        contracts = self.broker.get_options_chain(
            expiration=expiration,
            option_type=direction,
            strike_price_gte=target_strike - strike_range,
            strike_price_lte=target_strike + strike_range,
        )

        if not contracts:
            logger.warning(f"No {direction} contracts found near strike {target_strike}")
            return None

        # Find the contract closest to our target strike within price range
        best_contract = None
        best_distance = float('inf')

        for contract in contracts:
            strike = float(contract.get("strike_price", 0))
            distance = abs(strike - target_strike)

            if distance < best_distance:
                best_distance = distance
                best_contract = contract

        if best_contract:
            logger.info(f"Selected contract: {best_contract.get('symbol', 'N/A')} | "
                         f"Strike: {best_contract.get('strike_price', 'N/A')} | "
                         f"Type: {direction}")

        return best_contract

    def get_contract_price(self, contract: dict) -> float:
        """Get the current bid/ask midpoint price for a contract."""
        try:
            symbol = contract.get("symbol", "")
            quote = self.broker.get_option_quote(symbol)

            bid = float(quote.get("bid_price", 0) or 0)
            ask = float(quote.get("ask_price", 0) or 0)

            if bid > 0 and ask > 0:
                return (bid + ask) / 2
            elif ask > 0:
                return ask
            return 0.0
        except Exception as e:
            logger.error(f"Error getting contract price: {e}")
            return 0.0

    def validate_contract(self, contract: dict, price: float) -> bool:
        """Validate that a contract is suitable for trading."""
        if price < self.risk_config.min_option_price:
            logger.debug(f"Contract too cheap: ${price:.2f}")
            return False
        if price > self.risk_config.max_option_price:
            logger.debug(f"Contract too expensive: ${price:.2f}")
            return False
        return True

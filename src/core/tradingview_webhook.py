"""
TradingView Webhook Server for receiving alerts and converting them to trades.

Setup in TradingView:
1. Create an alert on any indicator/strategy
2. Set webhook URL to: http://YOUR_SERVER_IP:5000/webhook
3. Set alert message to JSON format:

{
    "action": "buy",
    "direction": "call",
    "ticker": "SPX",
    "price": {{close}},
    "indicator": "EMA Crossover",
    "strength": 0.8,
    "strike_offset": 2.0,
    "token": "YOUR_WEBHOOK_TOKEN"
}

Supported fields:
- action: "buy" or "sell" (required)
- direction: "call" or "put" (required for buy)
- ticker: symbol (default "SPX")
- price: current price at alert time
- indicator: name of the indicator/strategy
- strength: signal strength 0.0-1.0 (default 0.8)
- strike_offset: points from ATM (default auto)
- token: security token to verify alerts (required)
"""

import json
import threading
from typing import Optional, Callable
from datetime import datetime

from loguru import logger

try:
    from flask import Flask, request, jsonify
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

from src.strategies.base import Signal


class TradingViewWebhook:
    """
    HTTP webhook server that receives TradingView alerts
    and converts them into trading signals.
    """

    def __init__(self, token: str, host: str = "0.0.0.0", port: int = 5000):
        if not FLASK_AVAILABLE:
            raise ImportError("Flask is required for TradingView webhooks. "
                              "Run: pip install flask")
        self.token = token
        self.host = host
        self.port = port
        self.app = Flask(__name__)
        self._signal_callback: Optional[Callable] = None
        self._last_signal: Optional[Signal] = None
        self._signal_queue: list[Signal] = []
        self._setup_routes()

    def _setup_routes(self):
        """Set up Flask routes."""

        @self.app.route("/webhook", methods=["POST"])
        def webhook():
            try:
                data = request.get_json(force=True)
                if not data:
                    return jsonify({"error": "No JSON body"}), 400

                # Verify token
                if data.get("token") != self.token:
                    logger.warning(f"Invalid webhook token received")
                    return jsonify({"error": "Invalid token"}), 403

                signal = self._parse_alert(data)
                if signal:
                    self._signal_queue.append(signal)
                    self._last_signal = signal
                    logger.info(f"TradingView signal received: "
                                 f"{signal.direction.upper()} | "
                                 f"Strength: {signal.strength} | "
                                 f"Source: {signal.reason}")

                    # Call callback if registered
                    if self._signal_callback:
                        self._signal_callback(signal)

                    return jsonify({
                        "status": "ok",
                        "signal": signal.direction,
                        "strategy": signal.strategy_name,
                    }), 200
                else:
                    return jsonify({"error": "Invalid signal data"}), 400

            except Exception as e:
                logger.error(f"Webhook error: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/health", methods=["GET"])
        def health():
            return jsonify({
                "status": "ok",
                "signals_received": len(self._signal_queue),
                "last_signal": self._last_signal.direction if self._last_signal else None,
            }), 200

        @self.app.route("/signals", methods=["GET"])
        def signals():
            return jsonify({
                "pending": len(self._signal_queue),
                "signals": [
                    {
                        "direction": s.direction,
                        "strength": s.strength,
                        "strategy": s.strategy_name,
                        "reason": s.reason,
                    }
                    for s in self._signal_queue[-10:]  # Last 10
                ],
            }), 200

    def _parse_alert(self, data: dict) -> Optional[Signal]:
        """Parse a TradingView alert into a trading Signal."""
        action = data.get("action", "").lower()
        direction = data.get("direction", "").lower()

        if action not in ("buy", "sell"):
            logger.warning(f"Invalid action: {action}")
            return None

        # For sell actions, we handle position closing differently
        if action == "sell":
            # Create a sell signal - engine will handle closing
            return Signal(
                direction=direction or "close",
                strength=1.0,
                strategy_name="TRADINGVIEW",
                strike_offset=0.0,
                reason=f"TradingView SELL alert: {data.get('indicator', 'manual')}",
            )

        if direction not in ("call", "put"):
            logger.warning(f"Invalid direction: {direction}")
            return None

        strength = min(1.0, max(0.1, float(data.get("strength", 0.8))))
        strike_offset = float(data.get("strike_offset", 2.0 if direction == "call" else -2.0))
        indicator = data.get("indicator", "TradingView Alert")
        price = data.get("price", 0)

        return Signal(
            direction=direction,
            strength=strength,
            strategy_name="TRADINGVIEW",
            strike_offset=strike_offset,
            reason=f"TV:{indicator} @ {price}" if price else f"TV:{indicator}",
        )

    def on_signal(self, callback: Callable):
        """Register a callback for when signals are received."""
        self._signal_callback = callback

    def get_pending_signals(self) -> list[Signal]:
        """Get and clear pending signals."""
        signals = list(self._signal_queue)
        self._signal_queue.clear()
        return signals

    def start(self):
        """Start the webhook server in a background thread."""
        logger.info(f"Starting TradingView webhook server on "
                     f"{self.host}:{self.port}")
        logger.info(f"Webhook URL: http://{self.host}:{self.port}/webhook")

        thread = threading.Thread(
            target=self._run_server,
            daemon=True,
            name="tradingview-webhook",
        )
        thread.start()
        return thread

    def _run_server(self):
        """Run Flask server (called in background thread)."""
        # Suppress Flask's default logging to avoid noise
        import logging
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.WARNING)

        self.app.run(
            host=self.host,
            port=self.port,
            debug=False,
            use_reloader=False,
        )

# 0DTE SPX Options Trading Bot

Automated trading bot that buys SPX 0-day-to-expiration (0DTE) calls and puts using multiple proven intraday strategies. Connected to **IBKR** and **TradingView**. Built for **maximum risk and maximum reward**.

## Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| **Opening Range Breakout (ORB)** | Trades breakouts from the first 15-min range | Trending days, directional moves |
| **VWAP Bounce/Rejection** | Trades bounces off institutional VWAP | All market conditions |
| **Momentum Scalp** | Catches strong directional momentum | News events, big moves |
| **Mean Reversion** | Fades extreme overextended moves | Choppy/range-bound days |
| **TradingView Signals** | Executes trades from TradingView webhook alerts | Any custom indicator |

## Supported Brokers

### IBKR (Interactive Brokers) - Default
- Trades real SPX options directly (not SPY proxy)
- Connects via TWS or IB Gateway API
- Full options chain access

### Alpaca Markets - Alternative
- Cloud-based API, no local software needed
- Uses SPY as SPX proxy for data

## Setup

### Option A: IBKR (Recommended)

1. **Install TWS or IB Gateway** from Interactive Brokers
2. **Enable API** in TWS: Configure > API > Settings
   - Check "Enable ActiveX and Socket Clients"
   - Set port: `7497` (paper) or `7496` (live)
   - Uncheck "Read-Only API"
3. **Enable SPX options** permissions in your IBKR account
4. **Configure bot:**
```bash
cp .env.example .env
# Edit .env: BROKER=ibkr, set IBKR_PORT
```
5. **Install & run:**
```bash
pip install -r requirements.txt
python main.py --paper          # Paper trading
python main.py                  # Live trading (port 7496)
```

### Option B: Alpaca

```bash
cp .env.example .env
# Edit .env: BROKER=alpaca, add ALPACA_API_KEY and ALPACA_SECRET_KEY
pip install -r requirements.txt
python main.py --broker alpaca --paper
```

## TradingView Integration

Use any TradingView indicator or strategy to send signals to this bot.

### Setup

1. Enable webhooks in `.env`:
```
TRADINGVIEW_ENABLED=true
TRADINGVIEW_TOKEN=your_secret_token_here
```

2. Run bot with TradingView flag:
```bash
python main.py --tradingview
```

3. In TradingView, create an alert:
   - Set webhook URL: `http://YOUR_SERVER_IP:5000/webhook`
   - Set alert message (JSON):

```json
{
    "action": "buy",
    "direction": "call",
    "ticker": "SPX",
    "price": {{close}},
    "indicator": "EMA Crossover",
    "strength": 0.8,
    "strike_offset": 2.0,
    "token": "your_secret_token_here"
}
```

### Alert Fields

| Field | Required | Values | Description |
|-------|----------|--------|-------------|
| `action` | Yes | `buy`, `sell` | Trade action |
| `direction` | Yes (buy) | `call`, `put` | Option type |
| `token` | Yes | string | Your webhook secret token |
| `price` | No | number | Current price at alert |
| `indicator` | No | string | Name of indicator |
| `strength` | No | 0.0-1.0 | Signal strength (default 0.8) |
| `strike_offset` | No | number | Points from ATM (default auto) |

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/webhook` | POST | Receive TradingView alerts |
| `/health` | GET | Check bot status |
| `/signals` | GET | View recent signals |

## Configuration

Edit `.env` or `src/core/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `BROKER` | `ibkr` | Broker: `ibkr` or `alpaca` |
| `MAX_POSITION_SIZE` | $5,000 | Max dollars per trade |
| `MAX_DAILY_LOSS` | $2,000 | Stop trading after this loss |
| `MAX_OPEN_POSITIONS` | 3 | Simultaneous positions |
| Profit Target | 100% | Close at 2x entry price |
| Stop Loss | 50% | Close at 50% loss |
| Trailing Stop | 30% | Lock in gains after 20% profit |

## How It Works

1. **Pre-market**: Bot waits for market open (9:30 AM ET)
2. **Opening Range** (9:30-9:45): Establishes the first 15-min high/low
3. **Active Trading** (9:46-3:30 PM): Scans all strategies every 15 seconds
4. **TradingView signals** are processed in real-time via webhook
5. **Best Signal Wins**: Takes the strongest signal from any strategy
6. **Position Management**: Monitors stops, targets, and trailing stops
7. **End of Day** (3:55 PM): Force closes all remaining positions

## CLI Options

```
python main.py [OPTIONS]

--broker {ibkr,alpaca}    Broker to use (default: ibkr)
--paper                   Force paper trading mode
--tradingview             Enable TradingView webhook server
--once                    Run single cycle then exit (for testing)
```

## Project Structure

```
trading-bot/
├── main.py                          # Entry point
├── requirements.txt                 # Dependencies
├── .env.example                     # Environment template
├── src/
│   ├── core/
│   │   ├── config.py               # All configuration
│   │   ├── broker.py               # Alpaca API interface
│   │   ├── ibkr_broker.py          # IBKR API interface
│   │   ├── engine.py               # Main trading engine
│   │   ├── risk_manager.py         # Position & risk management
│   │   ├── option_selector.py      # Option contract selection
│   │   └── tradingview_webhook.py  # TradingView webhook server
│   ├── strategies/
│   │   ├── base.py                 # Strategy interface
│   │   ├── opening_range_breakout.py
│   │   ├── vwap_strategy.py
│   │   ├── momentum_scalp.py
│   │   ├── mean_reversion.py
│   │   └── tradingview_strategy.py # TradingView signal strategy
│   └── data/
│       └── market_data.py          # Market data & indicators
```

# 0DTE SPX Options Trading Bot

Automated trading bot that buys SPX 0-day-to-expiration (0DTE) calls and puts using multiple proven intraday strategies. Built for **maximum risk and maximum reward**.

## Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| **Opening Range Breakout (ORB)** | Trades breakouts from the first 15-min range | Trending days, directional moves |
| **VWAP Bounce/Rejection** | Trades bounces off institutional VWAP | All market conditions |
| **Momentum Scalp** | Catches strong directional momentum | News events, big moves |
| **Mean Reversion** | Fades extreme overextended moves | Choppy/range-bound days |

## Setup

### 1. Get Alpaca API Keys
- Sign up at [Alpaca Markets](https://app.alpaca.markets/)
- Enable options trading on your account
- Get your API key and secret key

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run (Paper Trading First!)
```bash
# Paper trading (recommended to start)
python main.py --paper

# Single test cycle
python main.py --paper --once

# Live trading (real money - be careful!)
# Edit .env: TRADING_MODE=live, ALPACA_BASE_URL=https://api.alpaca.markets
python main.py
```

## Configuration

Edit `.env` or `src/core/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
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
4. **Best Signal Wins**: Takes the strongest signal from any strategy
5. **Position Management**: Monitors stops, targets, and trailing stops
6. **End of Day** (3:55 PM): Force closes all remaining positions

## Risk Warning

**0DTE options are extremely risky.** Options can lose 100% of value in minutes. This bot uses aggressive settings designed for maximum reward, which also means maximum risk. Only trade with money you can afford to lose completely. Always start with paper trading.

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
│   │   ├── engine.py               # Main trading engine
│   │   ├── risk_manager.py         # Position & risk management
│   │   └── option_selector.py      # Option contract selection
│   ├── strategies/
│   │   ├── base.py                 # Strategy interface
│   │   ├── opening_range_breakout.py
│   │   ├── vwap_strategy.py
│   │   ├── momentum_scalp.py
│   │   └── mean_reversion.py
│   └── data/
│       └── market_data.py          # Market data & indicators
```

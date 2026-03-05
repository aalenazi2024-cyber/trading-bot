# Deployment Guide: AWS + IBKR + TradingView

Complete step-by-step guide to deploy the 0DTE SPX trading bot on AWS, connected to your IBKR account and TradingView.

---

## Overview

```
┌──────────────────┐     webhook      ┌──────────────────────────────────┐
│   TradingView    │ ──────────────►  │         AWS EC2 Server           │
│  (your charts)   │   JSON alerts    │                                  │
└──────────────────┘                  │  ┌────────────┐  ┌───────────┐  │
                                      │  │ Trading Bot │──│IB Gateway │  │
                                      │  │  (Python)   │  │ (headless)│  │
                                      │  └────────────┘  └─────┬─────┘  │
                                      └────────────────────────┼────────┘
                                                               │ API
                                      ┌────────────────────────▼────────┐
                                      │     Interactive Brokers          │
                                      │     (your brokerage account)     │
                                      └─────────────────────────────────┘
```

---

## Step 1: Create an AWS Account

1. Go to **https://aws.amazon.com** and click "Create an AWS Account"
2. Enter your email, create a password
3. Add a credit card (you'll pay ~$15-30/month for the server)
4. Complete the sign-up process
5. Sign in to the **AWS Console**

---

## Step 2: Launch an EC2 Server

1. In the AWS Console, search for **"EC2"** and click it
2. Click **"Launch Instance"**
3. Configure:

| Setting | Value |
|---------|-------|
| **Name** | `trading-bot` |
| **OS** | Ubuntu Server 24.04 LTS (free tier eligible) |
| **Instance type** | `t3.medium` (2 vCPU, 4 GB RAM) — ~$30/month |
| **Key pair** | Click "Create new key pair" → name it `trading-bot-key` → Download the `.pem` file → **SAVE THIS FILE** |
| **Network** | Allow SSH (port 22), HTTP (port 80), Custom TCP (port 5000) |
| **Storage** | 20 GB gp3 |

4. Under **"Network settings"**, click **"Edit"** and add these rules:
   - **SSH** (port 22) — your IP only
   - **Custom TCP** (port 5000) — anywhere (for TradingView webhooks)

5. Click **"Launch Instance"**
6. Wait 1-2 minutes for it to start

---

## Step 3: Connect to Your Server

### On Mac/Linux:
```bash
# Make key file secure
chmod 400 ~/Downloads/trading-bot-key.pem

# Connect (replace YOUR_EC2_IP with your server's public IP)
ssh -i ~/Downloads/trading-bot-key.pem ubuntu@YOUR_EC2_IP
```

### On Windows:
1. Download **PuTTY** from https://www.putty.org
2. Convert `.pem` to `.ppk` using PuTTYgen
3. In PuTTY: Host = `YOUR_EC2_IP`, Connection > SSH > Auth > browse to `.ppk`
4. Click "Open"

### Find your EC2 IP:
- In AWS Console → EC2 → Instances → click your instance
- Copy the **"Public IPv4 address"** (e.g., `54.123.45.67`)

---

## Step 4: Install Everything on the Server

Once connected via SSH:

```bash
# Clone your repo
git clone https://github.com/aalenazi2024-cyber/trading-bot.git
cd trading-bot

# Run the setup script
chmod +x deploy/aws_setup.sh
./deploy/aws_setup.sh
```

This installs Python, IB Gateway, IBC (auto-login), and all dependencies.

---

## Step 5: Configure IBKR Connection

### 5a. Get your IBKR credentials ready
- Your IBKR **username** and **password**
- Make sure **API trading** is enabled in your IBKR account settings:
  - Log in to IBKR web → Settings → API → enable "Enable ActiveX and Socket Clients"

### 5b. Configure IBC (auto-login for IB Gateway)
```bash
# Copy the config template
sudo cp deploy/ibc_config.ini /opt/ibc/config.ini

# Edit with your IBKR credentials
sudo nano /opt/ibc/config.ini
```

Change these lines:
```ini
IbLoginId=YOUR_IBKR_USERNAME
IbPassword=YOUR_IBKR_PASSWORD
TradingMode=paper          # Change to "live" when ready
OverrideTwsApiPort=4002    # Paper trading port
```

**Save**: `Ctrl+X`, then `Y`, then `Enter`

### 5c. Configure the bot
```bash
nano .env
```

Set these values:
```env
BROKER=ibkr
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_TRADING_MODE=paper

TRADINGVIEW_ENABLED=true
TRADINGVIEW_PORT=5000
TRADINGVIEW_TOKEN=GENERATE_ONE_BELOW
```

Generate a webhook token:
```bash
python3 -c "import secrets; print(secrets.token_hex(16))"
```
Copy the output and paste it as your `TRADINGVIEW_TOKEN`.

**Save**: `Ctrl+X`, then `Y`, then `Enter`

---

## Step 6: Install the Services (Auto-Start)

```bash
# Copy service files
sudo cp deploy/ibgateway.service /etc/systemd/system/
sudo cp deploy/trading-bot.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable ibgateway
sudo systemctl enable trading-bot

# Start IB Gateway first
sudo systemctl start ibgateway

# Wait 30 seconds for IB Gateway to connect
sleep 30

# Start the trading bot
sudo systemctl start trading-bot
```

### Check if everything is running:
```bash
# Check IB Gateway
sudo systemctl status ibgateway

# Check trading bot
sudo systemctl status trading-bot

# Watch bot logs live
sudo journalctl -u trading-bot -f

# Check log files
tail -f logs/trading_*.log
```

---

## Step 7: Set Up TradingView Webhooks

### 7a. Get your webhook URL
Your webhook URL is:
```
http://YOUR_EC2_IP:5000/webhook
```
Replace `YOUR_EC2_IP` with your EC2 public IP (e.g., `http://54.123.45.67:5000/webhook`)

### 7b. Test the webhook
```bash
# From your local machine, test it:
curl -X POST http://YOUR_EC2_IP:5000/health
# Should return: {"status": "ok", ...}
```

### 7c. Create TradingView alerts

1. Open **TradingView** and go to your SPX chart
2. Add your favorite indicator (e.g., EMA crossover, RSI, MACD)
3. Right-click the indicator → **"Add Alert"**
4. Configure the alert:

| Setting | Value |
|---------|-------|
| **Condition** | Your indicator signal |
| **Alert name** | `SPX 0DTE Call` or `SPX 0DTE Put` |
| **Webhook URL** | `http://YOUR_EC2_IP:5000/webhook` |

5. In the **"Message"** box, paste this JSON:

**For CALL (bullish) signals:**
```json
{
    "action": "buy",
    "direction": "call",
    "ticker": "SPX",
    "price": {{close}},
    "indicator": "EMA Crossover",
    "strength": 0.9,
    "strike_offset": 2.0,
    "token": "YOUR_TRADINGVIEW_TOKEN"
}
```

**For PUT (bearish) signals:**
```json
{
    "action": "buy",
    "direction": "put",
    "ticker": "SPX",
    "price": {{close}},
    "indicator": "EMA Crossover",
    "strength": 0.9,
    "strike_offset": -2.0,
    "token": "YOUR_TRADINGVIEW_TOKEN"
}
```

Replace `YOUR_TRADINGVIEW_TOKEN` with the token from your `.env` file.

6. Click **"Create"**

### 7d. Recommended TradingView indicators for 0DTE SPX

Set up alerts for these popular indicators:
- **EMA 9/21 Crossover** — bullish cross = call, bearish cross = put
- **RSI** — below 30 = call (oversold), above 70 = put (overbought)
- **VWAP** — price crosses above = call, below = put
- **MACD** — bullish cross = call, bearish cross = put
- **Supertrend** — buy signal = call, sell signal = put

---

## Step 8: Go Live (When Ready)

After paper trading successfully:

### 8a. Switch IB Gateway to live
```bash
sudo nano /opt/ibc/config.ini
```
Change:
```ini
TradingMode=live
OverrideTwsApiPort=4001    # Live trading port
```

### 8b. Switch bot to live
```bash
nano .env
```
Change:
```env
IBKR_PORT=4001
IBKR_TRADING_MODE=live
```

### 8c. Restart everything
```bash
sudo systemctl restart ibgateway
sleep 30
sudo systemctl restart trading-bot
```

---

## Daily Operations

### Monitor the bot
```bash
# Live logs
sudo journalctl -u trading-bot -f

# Today's log file
tail -f logs/trading_$(date +%Y-%m-%d).log

# Check bot health
curl http://localhost:5000/health

# Check recent TradingView signals
curl http://localhost:5000/signals
```

### Restart the bot
```bash
sudo systemctl restart trading-bot
```

### Stop the bot
```bash
sudo systemctl stop trading-bot
```

### Stop everything (emergencies)
```bash
sudo systemctl stop trading-bot
sudo systemctl stop ibgateway
```

---

## Security Checklist

- [ ] EC2 security group: SSH only from YOUR IP (not 0.0.0.0)
- [ ] Webhook token is random and long (32+ chars)
- [ ] `.env` file is NOT committed to git (check `.gitignore`)
- [ ] IBC config permissions: `sudo chmod 600 /opt/ibc/config.ini`
- [ ] Consider using AWS Secrets Manager for credentials
- [ ] Enable 2FA on your IBKR account
- [ ] Enable 2FA on your AWS account
- [ ] Set up AWS CloudWatch billing alerts ($50/month alert)

---

## Troubleshooting

### Bot won't connect to IB Gateway
```bash
# Check if IB Gateway is running
sudo systemctl status ibgateway
# Check IB Gateway logs
sudo journalctl -u ibgateway --since today
# Restart IB Gateway
sudo systemctl restart ibgateway
```

### TradingView webhooks not arriving
```bash
# Test webhook manually
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{"action":"buy","direction":"call","token":"YOUR_TOKEN","indicator":"test"}'

# Check if port 5000 is open
sudo ss -tlnp | grep 5000

# Check EC2 security group allows port 5000 inbound
```

### Bot crashes or restarts
```bash
# Check crash logs
sudo journalctl -u trading-bot --since "1 hour ago"

# Check Python logs
cat logs/trading_$(date +%Y-%m-%d).log
```

### IB Gateway disconnects overnight
IBC should auto-reconnect, but if not:
```bash
sudo systemctl restart ibgateway
sleep 30
sudo systemctl restart trading-bot
```

---

## Cost Summary

| Service | Monthly Cost |
|---------|-------------|
| AWS EC2 t3.medium | ~$30 |
| AWS data transfer | ~$1-2 |
| TradingView Pro (for webhooks) | $15-30 |
| IBKR market data | $0-10 |
| **Total** | **~$50-70/month** |

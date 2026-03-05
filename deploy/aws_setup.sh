#!/bin/bash
# ============================================================
# AWS EC2 Setup Script for 0DTE SPX Trading Bot
# Run this AFTER you SSH into your EC2 instance
# ============================================================

set -e

echo "=========================================="
echo "  0DTE Trading Bot - AWS Setup"
echo "=========================================="

# 1. Update system
echo "[1/7] Updating system packages..."
sudo apt-get update -y
sudo apt-get upgrade -y

# 2. Install Python 3.11+ and dependencies
echo "[2/7] Installing Python and system dependencies..."
sudo apt-get install -y python3 python3-pip python3-venv git wget unzip curl

# 3. Install IB Gateway (headless IBKR - no GUI needed)
echo "[3/7] Installing IB Gateway..."
# Install Java (required by IB Gateway)
sudo apt-get install -y default-jre xvfb

# Download IB Gateway (stable version)
cd /tmp
wget -q https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh
chmod +x ibgateway-stable-standalone-linux-x64.sh
# Install in unattended mode
sudo ./ibgateway-stable-standalone-linux-x64.sh -q -dir /opt/ibgateway
cd -

echo "IB Gateway installed to /opt/ibgateway"

# 4. Install IBC (automated IB Gateway login - keeps it running)
echo "[4/7] Installing IBC (auto-login for IB Gateway)..."
IBC_VERSION="3.18.0"
cd /tmp
wget -q "https://github.com/IbcAlpha/IBC/releases/download/${IBC_VERSION}/IBCLinux-${IBC_VERSION}.zip"
sudo mkdir -p /opt/ibc
sudo unzip -o "IBCLinux-${IBC_VERSION}.zip" -d /opt/ibc
sudo chmod +x /opt/ibc/*.sh /opt/ibc/*/*.sh 2>/dev/null || true
cd -

echo "IBC installed to /opt/ibc"

# 5. Clone and set up the trading bot
echo "[5/7] Setting up trading bot..."
cd /home/ubuntu

if [ ! -d "trading-bot" ]; then
    echo "Please clone your repo first:"
    echo "  git clone <your-repo-url> trading-bot"
    echo "Then re-run this script."
fi

cd trading-bot

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

echo "Python dependencies installed."

# 6. Create log directory
echo "[6/7] Creating log directory..."
mkdir -p logs

# 7. Set up environment file
echo "[7/7] Setting up environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "=========================================="
    echo "  IMPORTANT: Edit your .env file!"
    echo "=========================================="
    echo "  nano .env"
    echo ""
    echo "  Set these values:"
    echo "    BROKER=ibkr"
    echo "    IBKR_HOST=127.0.0.1"
    echo "    IBKR_PORT=4002   (IB Gateway paper)"
    echo "    TRADINGVIEW_ENABLED=true"
    echo "    TRADINGVIEW_TOKEN=<generate one>"
    echo ""
fi

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "  Next steps:"
echo "  1. Edit .env:           nano .env"
echo "  2. Configure IBC:       nano /opt/ibc/config.ini"
echo "  3. Start IB Gateway:    sudo systemctl start ibgateway"
echo "  4. Start bot:           sudo systemctl start trading-bot"
echo ""
echo "  See DEPLOYMENT_GUIDE.md for full instructions."
echo ""

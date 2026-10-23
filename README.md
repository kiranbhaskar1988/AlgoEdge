# AlgoEdge — Angel One Algo Trading System
## Python 3.10 / 3.11 / 3.12 Compatible

---

## QUICK START

### Windows
```
1. Double-click install.bat
2. Fill in .env with your Angel One credentials
3. Double-click install.bat again to verify
4. Open PowerShell in this folder and run:
   .\venv\Scripts\Activate.ps1
   python main.py --paper
5. Open http://localhost:5000 in your browser
```

### Linux / Mac
```
chmod +x install.sh && ./install.sh
source venv/bin/activate
python main.py --paper
```

---

## STEP BY STEP

### Step 1 — Get Angel One SmartAPI credentials
1. Go to https://smartapi.angelone.in
2. Login → My Apps → Create App → name it "AlgoEdge"
3. Copy your API Key
4. Client ID = your Angel One login ID (e.g. A123456)
5. Password = your 4-digit MPIN
6. TOTP Secret:
   - Open Angel One mobile app
   - Profile → Two-Factor Authentication → Enable TOTP
   - Copy the TEXT KEY (not QR code) — looks like JBSWY3DPEHPK3PXP

### Step 2 — Fill in .env
```
ANGEL_API_KEY       = your_key_here
ANGEL_CLIENT_ID     = A123456
ANGEL_PASSWORD      = 1234
ANGEL_TOTP_SECRET   = your_26_char_secret
CAPITAL             = 100000
MAX_DAILY_LOSS      = 5000
MAX_CAPITAL_PER_TRADE = 10000
MAX_OPEN_POSITIONS  = 5
```

### Step 3 — Verify setup
```bash
python verify.py
# If any failures: python verify.py --fix
```

### Step 4 — Check market conditions
```bash
python main.py --regime
```

### Step 5 — Backtest (always do this first)
```bash
python backtest.py --strategy ORB --symbol RELIANCE --days 60
python backtest.py --all
```

### Step 6 — Paper trade (minimum 5 days)
```bash
python main.py --paper
# Open http://localhost:5000
```

### Step 7 — Go live
```bash
python main.py
```

---

## COMMANDS REFERENCE

| Command | What it does |
|---------|-------------|
| python verify.py | Check all packages and credentials |
| python verify.py --fix | Auto-install missing packages |
| python main.py --regime | Show market regime |
| python main.py --paper | Paper trading (no real money) |
| python main.py | Live trading |
| python main.py --dashboard-only | Dashboard only |
| python backtest.py --all | Backtest all strategies |
| python backtest.py --strategy ORB --symbol RELIANCE --days 60 | Single backtest |

---

## 10 BUILT-IN STRATEGIES

| Strategy | Type | Timeframe |
|----------|------|-----------|
| OpeningRangeBreakout | Intraday | 5-min |
| VWAPSupertrend | Intraday | 5-min |
| EMAMomentum | Intraday | 3-min |
| RSIDivergence | Swing | Daily |
| BollingerSqueeze | Swing | Daily |
| MACDHistogram | Swing | Daily |
| SupertrendFutures | Futures | 15-min (auto-loads) |
| ShortStraddleExpiry | Options | Thursday only |
| IronCondor | Options | Thursday only |
| MomentumBreakout | Long-term | Monthly |

---

## TROUBLESHOOTING

| Error | Fix |
|-------|-----|
| pandas build fails | Run: pip install "pandas>=2.2.0" --prefer-binary |
| Activate.ps1 blocked | Run: Set-ExecutionPolicy RemoteSigned -Scope CurrentUser |
| Login rejected | Check MPIN and TOTP; sync clock: w32tm /resync /force |
| TOTP wrong code | Sync Windows time: Settings → Time → Sync now |
| Port 5000 in use | Change DASHBOARD_PORT=5001 in .env |
| Module not found | Run: python verify.py --fix |

---

## DISCLAIMER
This software is for educational purposes. Algo trading involves significant
financial risk. Always backtest, use paper trading first, and never risk money
you cannot afford to lose. Not SEBI-registered investment advice.

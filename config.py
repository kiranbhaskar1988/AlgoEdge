import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ANGEL_API_KEY     = os.getenv("ANGEL_API_KEY", "")
ANGEL_CLIENT_ID   = os.getenv("ANGEL_CLIENT_ID", "")
ANGEL_PASSWORD    = os.getenv("ANGEL_PASSWORD", "")
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")

MAX_DAILY_LOSS        = float(os.getenv("MAX_DAILY_LOSS",        "5000"))
MAX_CAPITAL_PER_TRADE = float(os.getenv("MAX_CAPITAL_PER_TRADE", "10000"))
MAX_OPEN_POSITIONS    = int(  os.getenv("MAX_OPEN_POSITIONS",    "5"))
CAPITAL               = float(os.getenv("CAPITAL",               "100000"))

DASHBOARD_PORT       = int(os.getenv("DASHBOARD_PORT", "5000"))
DASHBOARD_SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY", "algoedge-secret")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

BASE_DIR = Path(__file__).parent
LOG_DIR  = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

NSE = "NSE"
BSE = "BSE"
NFO = "NFO"

def validate():
    missing = [k for k, v in {
        "ANGEL_API_KEY": ANGEL_API_KEY, "ANGEL_CLIENT_ID": ANGEL_CLIENT_ID,
        "ANGEL_PASSWORD": ANGEL_PASSWORD, "ANGEL_TOTP_SECRET": ANGEL_TOTP_SECRET,
    }.items() if not v or "your_" in v]
    if missing:
        raise EnvironmentError(
            f"\n\nMissing credentials in .env file: {', '.join(missing)}\n"
            "Open .env and fill in your Angel One SmartAPI details.\n"
            "Get your API key from: https://smartapi.angelone.in\n")

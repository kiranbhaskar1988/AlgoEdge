"""Angel One SmartAPI wrapper — AlgoEdge"""
from __future__ import annotations
import time, pyotp, pandas as pd
from datetime import datetime, timedelta
from logzero import logger

try:
    from SmartApi import SmartConnect
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2
except ImportError:
    raise ImportError("Run: pip install smartapi-python>=1.3.9")

import config

class BrokerLoginError(Exception): pass
class BrokerOrderError(Exception): pass
class BrokerDataError(Exception):  pass

class AngelOneBroker:
    def __init__(self):
        self._api = self._jwt = self._feed_token = self._refresh_token = None
        self._logged_in = False
        self._session_expiry = None

    def login(self):
        logger.info("Logging in to Angel One as %s …", config.ANGEL_CLIENT_ID)
        try:
            self._api = SmartConnect(api_key=config.ANGEL_API_KEY)
            totp = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
            data = self._api.generateSession(config.ANGEL_CLIENT_ID, config.ANGEL_PASSWORD, totp)
            if data.get("status") is False:
                raise BrokerLoginError(f"Login rejected: {data.get('message','Unknown')}")
            self._jwt            = data["data"]["jwtToken"]
            self._refresh_token  = data["data"]["refreshToken"]
            self._feed_token     = self._api.getfeedToken()
            self._logged_in      = True
            self._session_expiry = datetime.now() + timedelta(hours=8)
            logger.info("✔ Login OK — session until %s", self._session_expiry.strftime("%H:%M"))
        except BrokerLoginError: raise
        except Exception as exc: raise BrokerLoginError(f"Login failed: {exc}") from exc

    def ensure_session(self):
        if not self._logged_in:
            self.login(); return
        if self._session_expiry and datetime.now() >= self._session_expiry - timedelta(minutes=10):
            try:
                self._api.generateToken(self._refresh_token)
                self._session_expiry = datetime.now() + timedelta(hours=8)
            except Exception: self.login()

    def logout(self):
        if self._api and self._logged_in:
            try: self._api.terminateSession(config.ANGEL_CLIENT_ID); self._logged_in = False
            except Exception as exc: logger.warning("Logout: %s", exc)

    def place_order(self, symbol, token, exchange, side, qty,
                    order_type="MARKET", product="INTRADAY", price=0, stoploss=0):
        self.ensure_session()
        try:
            oid = self._api.placeOrder({
                "variety": "NORMAL", "tradingsymbol": symbol, "symboltoken": token,
                "transactiontype": side, "exchange": exchange, "ordertype": order_type,
                "producttype": product, "duration": "DAY",
                "price": str(price), "squareoff": "0",
                "stoploss": str(stoploss), "quantity": str(qty)})
            if not oid: raise BrokerOrderError(f"Empty order ID for {symbol}")
            logger.info("✔ Order: %s %s×%d ID=%s", side, symbol, qty, oid)
            return str(oid)
        except BrokerOrderError: raise
        except Exception as exc: raise BrokerOrderError(f"Order failed {symbol}: {exc}") from exc

    def cancel_order(self, order_id, variety="NORMAL"):
        self.ensure_session()
        try: self._api.cancelOrder(order_id, variety); return True
        except Exception as exc: logger.error("Cancel %s: %s", order_id, exc); return False

    def get_ltp(self, exchange, symbol, token):
        self.ensure_session()
        try: return float(self._api.ltpData(exchange, symbol, token)["data"]["ltp"])
        except Exception as exc: raise BrokerDataError(f"LTP failed {symbol}: {exc}") from exc

    def get_candles(self, symbol, token, exchange, interval, from_date, to_date):
        self.ensure_session()
        try:
            raw  = self._api.getCandleData({"exchange": exchange, "symboltoken": token,
                "interval": interval, "fromdate": from_date, "todate": to_date})
            cols = ["datetime","open","high","low","close","volume"]
            df   = pd.DataFrame(raw["data"], columns=cols)
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
            for c in cols[1:]: df[c] = pd.to_numeric(df[c])
            return df
        except Exception as exc: raise BrokerDataError(f"Candles failed {symbol}: {exc}") from exc

    def get_candles_days(self, symbol, token, exchange, interval, days):
        to_dt = datetime.now(); from_dt = to_dt - timedelta(days=days)
        return self.get_candles(symbol, token, exchange, interval,
            from_dt.strftime("%Y-%m-%d %H:%M"), to_dt.strftime("%Y-%m-%d %H:%M"))

    def get_positions(self):
        self.ensure_session()
        try: return self._api.position().get("data") or []
        except Exception as exc: raise BrokerDataError(f"Positions: {exc}") from exc

    def get_holdings(self):
        self.ensure_session()
        try: return self._api.holding().get("data") or []
        except Exception as exc: raise BrokerDataError(f"Holdings: {exc}") from exc

    def get_funds(self):
        self.ensure_session()
        try: return self._api.rmsLimit().get("data") or {}
        except Exception as exc: raise BrokerDataError(f"Funds: {exc}") from exc

    def square_off_all(self):
        count = 0
        for pos in self.get_positions():
            qty = int(pos.get("netqty", 0))
            if qty == 0: continue
            try:
                self.place_order(symbol=pos["tradingsymbol"], token=pos["symboltoken"],
                    exchange=pos["exchange"], side="SELL" if qty > 0 else "BUY",
                    qty=abs(qty), order_type="MARKET", product="INTRADAY")
                count += 1
            except BrokerOrderError as exc: logger.error("SqOff failed %s: %s", pos["tradingsymbol"], exc)
        logger.info("Square-off done: %d positions.", count)
        return count

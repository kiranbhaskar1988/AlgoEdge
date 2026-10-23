"""Futures contract token resolver — AlgoEdge"""
from __future__ import annotations
import json, urllib.request
from datetime import date, timedelta
from logzero import logger
import config
from broker.angel_one import AngelOneBroker, BrokerDataError

SCRIP_URL  = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
ROLLOVER   = 5
LOT_SIZES  = {"NIFTY":50,"BANKNIFTY":15,"FINNIFTY":40,"MIDCPNIFTY":75,
              "SENSEX":10,"RELIANCE":250,"TCS":150,"INFY":300,"HDFCBANK":550,
              "ICICIBANK":700,"SBIN":1500,"AXISBANK":1200,"TATAMOTORS":1425}

def _last_thursday(year, month):
    if month==12: first_next=date(year+1,1,1)
    else: first_next=date(year,month+1,1)
    d=first_next-timedelta(days=1)
    while d.weekday()!=3: d-=timedelta(days=1)
    return d

def _active_expiry(today=None):
    today=today or date.today()
    cur=_last_thursday(today.year,today.month)
    if (cur-today).days<=ROLLOVER:
        return _last_thursday(today.year,today.month+1) if today.month<12 else _last_thursday(today.year+1,1)
    return cur

class FuturesResolver:
    def __init__(self, broker: AngelOneBroker):
        self.broker=broker; self._cache=[]; self._cache_date=None

    def _load(self):
        today=date.today()
        if self._cache_date==today and self._cache: return self._cache
        logger.info("[FuturesToken] Loading ScripMaster...")
        try:
            with urllib.request.urlopen(SCRIP_URL,timeout=30) as r:
                data=json.loads(r.read().decode())
            self._cache=[x for x in data if x.get("exch_seg","").upper()=="NFO" and "FUT" in x.get("symbol","").upper()]
            self._cache_date=today
            logger.info("[FuturesToken] %d futures loaded.",len(self._cache))
        except Exception as exc: raise BrokerDataError(f"ScripMaster failed: {exc}") from exc
        return self._cache

    def get(self, underlying: str) -> dict:
        expiry=_active_expiry(); exp_str=expiry.strftime("%d%b%y").upper()
        target=f"{underlying.upper()}{exp_str}FUT"
        logger.info("[FuturesToken] Resolving %s expiry=%s",underlying,exp_str)
        instruments=self._load()
        for inst in instruments:
            if inst.get("symbol","").upper()==target:
                return {"symbol":inst["symbol"],"token":str(inst.get("token","")),"expiry":expiry,
                        "lot_size":int(inst.get("lotsize",LOT_SIZES.get(underlying.upper(),1))),"exchange":config.NFO}
        for inst in instruments:
            s=inst.get("symbol","").upper()
            if underlying.upper() in s and exp_str[:5] in s and "FUT" in s:
                return {"symbol":s,"token":str(inst.get("token","")),"expiry":expiry,
                        "lot_size":int(inst.get("lotsize",LOT_SIZES.get(underlying.upper(),1))),"exchange":config.NFO}
        raise BrokerDataError(f"Cannot find futures for {underlying} expiry={exp_str}")

    def days_to_expiry(self, underlying="NIFTY") -> int:
        return (_active_expiry()-date.today()).days

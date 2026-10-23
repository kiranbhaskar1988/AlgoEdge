"""Option chain token resolver — AlgoEdge"""
from __future__ import annotations
import json, urllib.request
from datetime import date, timedelta
from logzero import logger
import config
from broker.angel_one import AngelOneBroker, BrokerDataError

SCRIP_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"

def next_thursday(from_date=None):
    d = from_date or date.today()
    days = 3 - d.weekday()
    if days <= 0: days += 7
    return d + timedelta(days=days)

def nearest_strike(spot, step=50):
    return round(spot / step) * step

def format_expiry(d):
    return d.strftime("%d%b%y").upper()

class OptionChainResolver:
    def __init__(self, broker: AngelOneBroker):
        self.broker = broker
        self._cache = []; self._cache_date = None

    def _load(self):
        today = date.today()
        if self._cache_date == today and self._cache: return self._cache
        logger.info("[OptionChain] Loading ScripMaster...")
        try:
            with urllib.request.urlopen(SCRIP_URL, timeout=30) as r:
                data = json.loads(r.read().decode())
            self._cache = [x for x in data if x.get("exch_seg","").upper()=="NFO"]
            self._cache_date = today
            logger.info("[OptionChain] %d NFO instruments loaded.", len(self._cache))
        except Exception as exc:
            raise BrokerDataError(f"ScripMaster failed: {exc}") from exc
        return self._cache

    def _find(self, underlying, strike, otype, expiry_str):
        instruments = self._load()
        target = f"{underlying}{expiry_str}{strike}{otype}"
        for inst in instruments:
            if inst.get("name","").upper()==target or inst.get("symbol","").upper()==target:
                return target, str(inst.get("token",""))
        for inst in instruments:
            s = inst.get("symbol","").upper()
            if underlying in s and str(strike) in s and otype in s and expiry_str[:5] in s:
                return s, str(inst.get("token",""))
        logger.warning("[OptionChain] No match for %s", target)
        return None

    def get_straddle_tokens(self, underlying, spot, expiry_type="weekly", step=50):
        expiry = next_thursday()
        exp_str = format_expiry(expiry)
        atm = nearest_strike(spot, step)
        logger.info("[OptionChain] Straddle %s expiry=%s ATM=%d", underlying, exp_str, atm)
        ce = self._find(underlying, atm, "CE", exp_str)
        pe = self._find(underlying, atm, "PE", exp_str)
        if not ce or not pe:
            raise BrokerDataError(f"Cannot resolve {underlying} {exp_str} {atm} CE/PE")
        return {"CE": ce, "PE": pe, "atm_strike": atm, "expiry_str": exp_str, "expiry_date": expiry}

    def get_iron_condor_tokens(self, underlying, spot, wing_width=100, buy_offset=100, step=50):
        expiry = next_thursday(); exp_str = format_expiry(expiry)
        atm = nearest_strike(spot, step)
        cs = atm + wing_width; cb = cs + buy_offset
        ps = atm - wing_width; pb = ps - buy_offset
        result = {"expiry_date": expiry}
        for label, strike, otype in [("SELL_CE",cs,"CE"),("BUY_CE",cb,"CE"),
                                      ("SELL_PE",ps,"PE"),("BUY_PE",pb,"PE")]:
            found = self._find(underlying, strike, otype, exp_str)
            if not found:
                raise BrokerDataError(f"Cannot resolve IC leg {label} {underlying}{exp_str}{strike}{otype}")
            result[label] = found
        result["strikes"] = {"call_sell":cs,"call_buy":cb,"put_sell":ps,"put_buy":pb}
        return result

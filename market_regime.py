"""Market Regime Detector — AlgoEdge"""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from logzero import logger
import config
from broker.angel_one import AngelOneBroker, BrokerDataError

class MarketRegime:
    NIFTY_TOKEN="99926000"; VIX_TOKEN="99926017"
    BULL="BULL"; BEAR="BEAR"; RANGE="RANGE"; CRASH="CRASH"; UNKNOWN="UNKNOWN"

    def __init__(self, broker: AngelOneBroker):
        self.broker=broker; self._regime=self.UNKNOWN
        self._vix=0.0; self._nifty=0.0; self._last=None

    def detect(self, force=False) -> str:
        if not force and self._last and (datetime.now()-self._last).seconds < 900:
            return self._regime
        try:
            df = self.broker.get_candles_days("NIFTY 50",self.NIFTY_TOKEN,config.NSE,"ONE_DAY",220)
            if len(df) < 60: self._regime=self.UNKNOWN; return self._regime
            import pandas_ta as ta
            df.ta.sma(length=50,append=True); df.ta.sma(length=200,append=True)
            last=df.iloc[-1]; prev=df.iloc[-2]
            close=float(last["close"])
            sma50  = float(last[[c for c in df.columns if "SMA_50"  in c][0]]) if any("SMA_50"  in c for c in df.columns) else close
            sma200 = float(last[[c for c in df.columns if "SMA_200" in c][0]]) if any("SMA_200" in c for c in df.columns) else close
            day_chg=(close-float(prev["close"]))/float(prev["close"])*100
            try: self._vix=self.broker.get_ltp(config.NSE,"INDIA VIX",self.VIX_TOKEN)
            except BrokerDataError: self._vix=15.0
            self._nifty=close
            if self._vix>25 or day_chg<-2.0:          self._regime=self.CRASH
            elif close>sma50 and close>sma200 and self._vix<18: self._regime=self.BULL
            elif close<sma50 and close<sma200:         self._regime=self.BEAR
            else:                                       self._regime=self.RANGE
            self._last=datetime.now()
            logger.info("[Regime] %s Nifty=%.0f VIX=%.1f DayChg=%.2f%%",
                        self._regime,close,self._vix,day_chg)
            try:
                sf=config.DATA_DIR/"risk_state.json"
                s=json.loads(sf.read_text()) if sf.exists() else {}
                s.update({"regime":self._regime,"vix":round(self._vix,2),"nifty":round(self._nifty,2)})
                sf.write_text(json.dumps(s,indent=2))
            except Exception: pass
        except BrokerDataError as exc:
            logger.warning("[Regime] %s",exc); self._regime=self.UNKNOWN
        return self._regime

    def allows_long(self):            return self.detect() in (self.BULL,self.RANGE,self.UNKNOWN)
    def allows_short(self):           return self.detect() in (self.BEAR,self.RANGE)
    def allows_options_selling(self): return self.detect()==self.RANGE and self._vix<20
    def is_crash(self):               return self.detect()==self.CRASH
    def allows_intraday(self):        return not self.is_crash()
    @property
    def vix(self):    return self._vix
    @property
    def nifty(self):  return self._nifty
    @property
    def regime(self): return self._regime

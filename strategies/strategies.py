"""
All 10 trading strategies — AlgoEdge
pandas-ta 0.4.x compatible (Python 3.12)

Strategies:
  Intraday  : OpeningRangeBreakout, VWAPSupertrend, EMAMomentum
  Swing     : RSIDivergence, BollingerSqueeze, MACDHistogram
  Futures   : SupertrendFutures
  Options   : ShortStraddleExpiry, IronCondor
  Long-term : MomentumBreakout
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta, date
from logzero import logger

import config
from broker.angel_one import AngelOneBroker, BrokerOrderError, BrokerDataError
from risk.risk_manager import RiskManager
from position_manager import PositionManager, Position
from market_regime import MarketRegime


# ── Helpers ───────────────────────────────────────────────────────────────────

def _atr(df: pd.DataFrame, period: int = 14) -> float:
    try:
        a = df.ta.atr(length=period)
        if a is not None and not a.empty:
            v = float(a.iloc[-1])
            if v > 0: return v
    except Exception: pass
    return float(df["close"].iloc[-1]) * 0.01

def _vol_ok(df: pd.DataFrame, mult: float = 1.2) -> bool:
    if "volume" not in df.columns or len(df) < 5: return True
    avg = df["volume"].iloc[-21:-1].mean()
    return avg > 0 and float(df["volume"].iloc[-1]) >= avg * mult

def _vwap(df: pd.DataFrame) -> pd.Series:
    """Correct intraday VWAP — resets each day."""
    d = df.copy()
    d["_d"]   = d.index.date
    d["_tp"]  = (d["high"] + d["low"] + d["close"]) / 3
    d["_tpv"] = d["_tp"] * d["volume"]
    d["_cv"]  = d.groupby("_d")["volume"].cumsum()
    d["_ct"]  = d.groupby("_d")["_tpv"].cumsum()
    return d["_ct"] / d["_cv"].replace(0, np.nan)

def _size(price: float, atr: float) -> int:
    risk = config.MAX_CAPITAL_PER_TRADE * 0.005
    sl_d = atr * 1.5
    if sl_d <= 0 or price <= 0: return 1
    return max(1, min(int(risk / sl_d), int(config.MAX_CAPITAL_PER_TRADE / price)))

def _today_start(now: datetime) -> str:
    return now.strftime("%Y-%m-%d") + " 09:15"

def _now_str(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M")


# ── Base ──────────────────────────────────────────────────────────────────────

class BaseStrategy:
    name = "Base"; category = "intraday"

    def __init__(self, broker: AngelOneBroker, risk: RiskManager,
                 pm: PositionManager, regime: MarketRegime):
        self.broker=broker; self.risk=risk; self.pm=pm; self.regime=regime
        self.enabled=True; self._last_sig_time=None; self._last_sig_sym=""

    def run(self) -> dict: raise NotImplementedError

    def _cooldown(self, symbol: str, minutes: int = 30) -> bool:
        if (self._last_sig_sym == symbol and self._last_sig_time
                and (datetime.now()-self._last_sig_time).seconds < minutes*60):
            return False
        return True

    def _mark(self, symbol: str):
        self._last_sig_time = datetime.now(); self._last_sig_sym = symbol

    def _place(self, symbol, token, exchange, side, qty, price,
               sl, target, product, atr=0) -> dict:
        res = {"action":"ERROR","order_id":"","reason":""}
        try:
            oid = self.broker.place_order(symbol=symbol, token=token,
                exchange=exchange, side=side, qty=qty,
                order_type="MARKET", product=product)
            self.risk.on_order_placed(symbol, side, qty, price, self.name)
            self.pm.open_position(Position(
                symbol=symbol, token=token, exchange=exchange,
                side=side, qty=qty, entry_price=price,
                sl_price=sl, target_price=target, product=product,
                strategy=self.name, trailing=True, atr=atr, order_id=oid))
            self._mark(symbol)
            res.update({"action":side,"order_id":oid})
            logger.info("[%s] %s %s×%d @%.2f SL=%.2f T=%.2f",
                        self.name, side, symbol, qty, price, sl, target)
        except BrokerOrderError as exc:
            res["reason"] = str(exc)
            logger.error("[%s] Order failed %s: %s", self.name, symbol, exc)
        return res

    def _r(self, action="HOLD", reason="", signal=0, **kw):
        return {"strategy":self.name,"action":action,"reason":reason,"signal":signal,**kw}


# ── 1. Opening Range Breakout ─────────────────────────────────────────────────

class OpeningRangeBreakout(BaseStrategy):
    name="OpeningRangeBreakout"; category="intraday"

    def __init__(self, broker, risk, pm, regime,
                 symbol, token, exchange="NSE", qty=0):
        super().__init__(broker,risk,pm,regime)
        self.symbol=symbol; self.token=token; self.exchange=exchange; self._qty=qty
        self._orb_high=None; self._orb_low=None; self._orb_date=None; self._traded=False

    def _get_orb(self):
        today=date.today()
        if self._orb_date!=today:
            self._orb_high=self._orb_low=None; self._orb_date=today; self._traded=False
        now=datetime.now()
        if now.hour==9 and now.minute<31: return None
        if self._orb_high: return self._orb_high,self._orb_low
        try:
            df=self.broker.get_candles(self.symbol,self.token,self.exchange,"ONE_MINUTE",
                now.strftime("%Y-%m-%d")+" 09:15", now.strftime("%Y-%m-%d")+" 09:29")
            if df.empty: return None
            self._orb_high=float(df["high"].max()); self._orb_low=float(df["low"].min())
            logger.info("[ORB] %s H=%.2f L=%.2f", self.symbol, self._orb_high, self._orb_low)
            return self._orb_high,self._orb_low
        except BrokerDataError: return None

    def run(self):
        if not self.enabled: return self._r(reason="Disabled")
        now=datetime.now()
        t=now.hour*60+now.minute
        if not (9*60+30 <= t <= 13*60+30): return self._r(reason="Outside ORB window")
        if self._traded: return self._r(reason="Already traded today")
        if not self.regime.allows_intraday(): return self._r(reason=f"Regime={self.regime.regime}")
        orb=self._get_orb()
        if not orb: return self._r(reason="ORB window not ready")
        orb_h,orb_l=orb; orb_range=orb_h-orb_l
        if orb_range<=0: return self._r(reason="Invalid ORB range")
        if not self._cooldown(self.symbol,60): return self._r(reason="Cooldown")
        try:
            df=self.broker.get_candles(self.symbol,self.token,self.exchange,
                "FIVE_MINUTE",_today_start(now),_now_str(now))
            if len(df)<3: return self._r(reason="Not enough candles")
            atr=_atr(df); close=float(df["close"].iloc[-1])
            if not _vol_ok(df,1.5): return self._r(reason="Low volume")
            signal=0; side=""; sl=target=0.0
            if close > orb_h+atr*0.1:
                signal=1; side="BUY"; sl=orb_h-atr*0.5; target=close+orb_range*2
            elif close < orb_l-atr*0.1:
                signal=-1; side="SELL"; sl=orb_l+atr*0.5; target=close-orb_range*2
            if signal==0: return self._r(reason=f"No breakout close={close:.2f}")
            ok,msg=self.risk.can_trade(close*max(self._qty,1))
            if not ok: return self._r(action="BLOCKED",reason=msg)
            qty=self._qty or _size(close,atr)
            res=self._place(self.symbol,self.token,self.exchange,side,qty,close,
                            round(sl,2),round(target,2),"INTRADAY",atr)
            if res["action"]==side: self._traded=True
            res["signal"]=signal; return res
        except BrokerDataError as exc: return self._r(reason=str(exc))


# ── 2. VWAP + Supertrend ──────────────────────────────────────────────────────

class VWAPSupertrend(BaseStrategy):
    name="VWAPSupertrend"; category="intraday"

    def __init__(self,broker,risk,pm,regime,symbol,token,exchange="NSE",qty=0):
        super().__init__(broker,risk,pm,regime)
        self.symbol=symbol; self.token=token; self.exchange=exchange; self._qty=qty

    def run(self):
        if not self.enabled: return self._r(reason="Disabled")
        if not self.regime.allows_intraday(): return self._r(reason=f"Regime={self.regime.regime}")
        if not self._cooldown(self.symbol,30): return self._r(reason="Cooldown")
        now=datetime.now()
        try:
            df=self.broker.get_candles(self.symbol,self.token,self.exchange,
                "FIVE_MINUTE",_today_start(now),_now_str(now))
            if len(df)<20: return self._r(reason="Insufficient candles")
            atr=_atr(df); df.ta.rsi(length=14,append=True)
            df["vwap"]=_vwap(df)
            # pandas-ta 0.4.x uses length= not period=
            st=df.ta.supertrend(length=10,multiplier=3.0)
            if st is None or st.empty: return self._r(reason="Supertrend unavailable")
            df=pd.concat([df,st],axis=1)
            st_cols=[c for c in df.columns if "SUPERTd" in c]
            if not st_cols: return self._r(reason="Supertrend column missing")
            last=df.iloc[-1]
            close=float(last["close"]); vwap=float(last["vwap"])
            rsi=float(last.get("RSI_14",50)); st_d=int(last[st_cols[0]])
            vol_ok=_vol_ok(df,1.2)
            if   close>vwap and st_d==1  and 50<rsi<72 and vol_ok: signal=1;  side="BUY"
            elif close<vwap and st_d==-1 and 28<rsi<50 and vol_ok: signal=-1; side="SELL"
            else: return self._r(reason=f"No signal close={close:.2f} VWAP={vwap:.2f} ST={st_d} RSI={rsi:.1f}")
            sl     = close-atr*1.5 if side=="BUY" else close+atr*1.5
            target = close+atr*3.0 if side=="BUY" else close-atr*3.0
            ok,msg=self.risk.can_trade(close*max(self._qty,1))
            if not ok: return self._r(action="BLOCKED",reason=msg)
            qty=self._qty or _size(close,atr)
            res=self._place(self.symbol,self.token,self.exchange,side,qty,close,
                            round(sl,2),round(target,2),"INTRADAY",atr)
            res["signal"]=signal; return res
        except BrokerDataError as exc: return self._r(reason=str(exc))


# ── 3. EMA Momentum ───────────────────────────────────────────────────────────

class EMAMomentum(BaseStrategy):
    name="EMAMomentum"; category="intraday"

    def __init__(self,broker,risk,pm,regime,symbol,token,exchange="NSE",qty=0):
        super().__init__(broker,risk,pm,regime)
        self.symbol=symbol; self.token=token; self.exchange=exchange; self._qty=qty

    def run(self):
        if not self.enabled: return self._r(reason="Disabled")
        if not self.regime.allows_intraday(): return self._r(reason=f"Regime={self.regime.regime}")
        if not self._cooldown(self.symbol,30): return self._r(reason="Cooldown")
        now=datetime.now()
        try:
            df=self.broker.get_candles(self.symbol,self.token,self.exchange,
                "THREE_MINUTE",_today_start(now),_now_str(now))
            if len(df)<55: return self._r(reason=f"Need 55 candles, have {len(df)}")
            df.ta.ema(length=9,append=True); df.ta.ema(length=21,append=True)
            df.ta.ema(length=50,append=True); df.ta.rsi(length=14,append=True)
            atr=_atr(df); last=df.iloc[-1]; prev=df.iloc[-2]
            e9=float(last.get("EMA_9",last["close"])); e21=float(last.get("EMA_21",last["close"]))
            e50=float(last.get("EMA_50",last["close"])); rsi=float(last.get("RSI_14",50))
            pe9=float(prev.get("EMA_9",prev["close"])); pe21=float(prev.get("EMA_21",prev["close"]))
            close=float(last["close"]); vol_ok=_vol_ok(df,1.2)
            bull=(pe9<pe21)and(e9>e21)and(e9>e21>e50)and(55<rsi<72)and vol_ok
            bear=(pe9>pe21)and(e9<e21)and(e9<e21<e50)and(28<rsi<45)and vol_ok
            if not bull and not bear: return self._r(reason=f"No cross E9={e9:.2f} E21={e21:.2f}")
            signal=1 if bull else -1; side="BUY" if bull else "SELL"
            sl=close-atr*1.5 if side=="BUY" else close+atr*1.5
            target=close+atr*3.0 if side=="BUY" else close-atr*3.0
            ok,msg=self.risk.can_trade(close*max(self._qty,1))
            if not ok: return self._r(action="BLOCKED",reason=msg)
            qty=self._qty or _size(close,atr)
            res=self._place(self.symbol,self.token,self.exchange,side,qty,close,
                            round(sl,2),round(target,2),"INTRADAY",atr)
            res["signal"]=signal; return res
        except BrokerDataError as exc: return self._r(reason=str(exc))


# ── 4. RSI Divergence ─────────────────────────────────────────────────────────

class RSIDivergence(BaseStrategy):
    name="RSIDivergence"; category="swing"

    def __init__(self,broker,risk,pm,regime,symbol,token,exchange="NSE",qty=1):
        super().__init__(broker,risk,pm,regime)
        self.symbol=symbol; self.token=token; self.exchange=exchange; self.qty=qty

    def run(self):
        if not self.enabled: return self._r(reason="Disabled")
        if not self._cooldown(self.symbol,60*24): return self._r(reason="Cooldown")
        try:
            df=self.broker.get_candles_days(self.symbol,self.token,self.exchange,"ONE_DAY",60)
            if len(df)<30: return self._r(reason="Insufficient history")
            df.ta.rsi(length=14,append=True); df.ta.sma(length=50,append=True)
            atr=_atr(df); close=float(df["close"].iloc[-1])
            sma50_cols=[c for c in df.columns if "SMA_50" in c]
            sma50=float(df[sma50_cols[0]].iloc[-1]) if sma50_cols else close
            rsi_cols=[c for c in df.columns if "RSI_14" in c]
            if not rsi_cols: return self._r(reason="RSI unavailable")
            prices=df["close"].iloc[-10:].values; rsis=df[rsi_cols[0]].iloc[-10:].values
            bull_div=bear_div=False
            for i in range(2,len(prices)-1):
                if prices[i]<prices[i-2] and rsis[i]>rsis[i-2] and close>sma50:
                    bull_div=True; break
                if prices[i]>prices[i-2] and rsis[i]<rsis[i-2] and close<sma50:
                    bear_div=True; break
            if not bull_div and not bear_div: return self._r(reason="No RSI divergence")
            if not _vol_ok(df,1.1): return self._r(reason="Low volume")
            signal=1 if bull_div else -1; side="BUY" if signal==1 else "SELL"
            sl=close-atr*2 if side=="BUY" else close+atr*2
            target=close+atr*4 if side=="BUY" else close-atr*4
            if side=="BUY" and not self.regime.allows_long():
                return self._r(action="BLOCKED",reason=f"Regime={self.regime.regime}")
            ok,msg=self.risk.can_trade(close*self.qty)
            if not ok: return self._r(action="BLOCKED",reason=msg)
            res=self._place(self.symbol,self.token,self.exchange,side,self.qty,close,
                            round(sl,2),round(target,2),"DELIVERY",atr)
            res.update({"signal":signal,"divergence":"bullish" if bull_div else "bearish"})
            return res
        except BrokerDataError as exc: return self._r(reason=str(exc))


# ── 5. Bollinger Squeeze ──────────────────────────────────────────────────────

class BollingerSqueeze(BaseStrategy):
    name="BollingerSqueeze"; category="swing"

    def __init__(self,broker,risk,pm,regime,symbol,token,exchange="NSE",qty=1):
        super().__init__(broker,risk,pm,regime)
        self.symbol=symbol; self.token=token; self.exchange=exchange; self.qty=qty

    def run(self):
        if not self.enabled: return self._r(reason="Disabled")
        if not self._cooldown(self.symbol,60*24): return self._r(reason="Cooldown")
        try:
            df=self.broker.get_candles_days(self.symbol,self.token,self.exchange,"ONE_DAY",60)
            if len(df)<25: return self._r(reason="Insufficient history")
            bb=df.ta.bbands(length=20,std=2)
            if bb is None or bb.empty: return self._r(reason="BB unavailable")
            df=pd.concat([df,bb],axis=1)
            up=[c for c in df.columns if "BBU_" in c]
            lo=[c for c in df.columns if "BBL_" in c]
            mi=[c for c in df.columns if "BBM_" in c]
            if not up: return self._r(reason="BB columns not found")
            df["bbw"]=(df[up[0]]-df[lo[0]])/df[mi[0]]
            avg_w=float(df["bbw"].iloc[-21:-1].mean()); cur_w=float(df["bbw"].iloc[-1])
            if cur_w >= avg_w*0.80: return self._r(reason=f"No squeeze w={cur_w:.4f}")
            atr=_atr(df); close=float(df["close"].iloc[-1])
            if close>float(df[up[0]].iloc[-1]) and _vol_ok(df,1.5):
                signal=1; side="BUY"
            elif close<float(df[lo[0]].iloc[-1]) and _vol_ok(df,1.5):
                signal=-1; side="SELL"
            else: return self._r(reason="Squeeze but no breakout")
            if side=="BUY" and not self.regime.allows_long():
                return self._r(action="BLOCKED",reason=f"Regime={self.regime.regime}")
            sl=close-atr*2 if side=="BUY" else close+atr*2
            target=close+atr*4 if side=="BUY" else close-atr*4
            ok,msg=self.risk.can_trade(close*self.qty)
            if not ok: return self._r(action="BLOCKED",reason=msg)
            res=self._place(self.symbol,self.token,self.exchange,side,self.qty,close,
                            round(sl,2),round(target,2),"DELIVERY",atr)
            res["signal"]=signal; return res
        except BrokerDataError as exc: return self._r(reason=str(exc))


# ── 6. MACD Histogram ─────────────────────────────────────────────────────────

class MACDHistogram(BaseStrategy):
    name="MACDHistogram"; category="swing"

    def __init__(self,broker,risk,pm,regime,symbol,token,exchange="NSE",qty=1):
        super().__init__(broker,risk,pm,regime)
        self.symbol=symbol; self.token=token; self.exchange=exchange; self.qty=qty

    def run(self):
        if not self.enabled: return self._r(reason="Disabled")
        if not self._cooldown(self.symbol,60*24): return self._r(reason="Cooldown")
        try:
            df=self.broker.get_candles_days(self.symbol,self.token,self.exchange,"ONE_DAY",60)
            if len(df)<35: return self._r(reason="Insufficient history")
            df.ta.sma(length=50,append=True)
            macd=df.ta.macd(fast=12,slow=26,signal=9)
            if macd is None or macd.empty: return self._r(reason="MACD unavailable")
            df=pd.concat([df,macd],axis=1)
            hc=[c for c in df.columns if "MACDh_" in c]
            if not hc: return self._r(reason="MACD histogram column missing")
            atr=_atr(df); close=float(df["close"].iloc[-1])
            sma50_cols=[c for c in df.columns if "SMA_50" in c]
            sma50=float(df[sma50_cols[0]].iloc[-1]) if sma50_cols else close
            hist=df[hc[0]].iloc[-5:].values
            bull=(hist[-3]<0 and hist[-2]<0 and hist[-1]>hist[-2] and close>sma50)
            bear=(hist[-3]>0 and hist[-2]>0 and hist[-1]<hist[-2] and close<sma50)
            if not bull and not bear: return self._r(reason="No histogram reversal")
            if not _vol_ok(df,1.2): return self._r(reason="Low volume")
            signal=1 if bull else -1; side="BUY" if bull else "SELL"
            if side=="BUY" and not self.regime.allows_long():
                return self._r(action="BLOCKED",reason=f"Regime={self.regime.regime}")
            sl=close-atr*2 if side=="BUY" else close+atr*2
            target=close+atr*4 if side=="BUY" else close-atr*4
            ok,msg=self.risk.can_trade(close*self.qty)
            if not ok: return self._r(action="BLOCKED",reason=msg)
            res=self._place(self.symbol,self.token,self.exchange,side,self.qty,close,
                            round(sl,2),round(target,2),"DELIVERY",atr)
            res["signal"]=signal; return res
        except BrokerDataError as exc: return self._r(reason=str(exc))


# ── 7. Supertrend Futures ─────────────────────────────────────────────────────

class SupertrendFutures(BaseStrategy):
    name="SupertrendFutures"; category="futures"

    def __init__(self,broker,risk,pm,regime,symbol,token,lot_size=50,lots=1):
        super().__init__(broker,risk,pm,regime)
        self.symbol=symbol; self.token=token; self.exchange=config.NFO
        self.lot_size=lot_size; self.lots=lots

    def run(self):
        if not self.enabled: return self._r(reason="Disabled")
        if not self.regime.allows_intraday(): return self._r(reason=f"Regime={self.regime.regime}")
        if not self._cooldown(self.symbol,30): return self._r(reason="Cooldown")
        now=datetime.now()
        try:
            df=self.broker.get_candles(self.symbol,self.token,self.exchange,
                "FIFTEEN_MINUTE",_today_start(now),_now_str(now))
            if len(df)<20: return self._r(reason="Insufficient candles")
            # pandas-ta 0.4.x: use length= not period=
            st=df.ta.supertrend(length=7,multiplier=3)
            adx=df.ta.adx(length=14)
            if st is None or adx is None: return self._r(reason="Indicators unavailable")
            df=pd.concat([df,st,adx],axis=1)
            st_cols=[c for c in df.columns if "SUPERTd" in c]
            adx_cols=[c for c in df.columns if c.startswith("ADX_")]
            if not st_cols or not adx_cols: return self._r(reason="Indicator columns missing")
            atr=_atr(df); close=float(df["close"].iloc[-1])
            st_d=int(df[st_cols[0]].iloc[-1]); pd_d=int(df[st_cols[0]].iloc[-2])
            adxv=float(df[adx_cols[0]].iloc[-1])
            bull=(pd_d==-1)and(st_d==1)and(adxv>25)
            bear=(pd_d==1)and(st_d==-1)and(adxv>25)
            if not bull and not bear: return self._r(reason=f"No flip ST={st_d} ADX={adxv:.1f}")
            side="BUY" if bull else "SELL"; qty=self.lot_size*self.lots
            sl=close-atr*2 if side=="BUY" else close+atr*2
            target=close+atr*4 if side=="BUY" else close-atr*4
            ok,msg=self.risk.can_trade(close*qty*0.1)
            if not ok: return self._r(action="BLOCKED",reason=msg)
            res=self._place(self.symbol,self.token,self.exchange,side,qty,close,
                            round(sl,2),round(target,2),"CARRYFORWARD",atr)
            res["signal"]=1 if bull else -1; return res
        except BrokerDataError as exc: return self._r(reason=str(exc))


# ── 8. Short Straddle (Options — Thursday only) ───────────────────────────────

class ShortStraddleExpiry(BaseStrategy):
    name="ShortStraddleExpiry"; category="options"

    def __init__(self,broker,risk,pm,regime,underlying="NIFTY",
                 underlying_token="99926000",lot_size=50,lots=1):
        super().__init__(broker,risk,pm,regime)
        self.underlying=underlying; self.underlying_token=underlying_token
        self.lot_size=lot_size; self.lots=lots
        self._sold=False; self._date=None

    def run(self):
        if not self.enabled: return self._r(reason="Disabled")
        today=date.today()
        if self._date!=today: self._sold=False; self._date=today
        if today.weekday()!=3: return self._r(reason="Not Thursday")
        now=datetime.now(); t=now.hour*60+now.minute
        if not (9*60+20<=t<=10*60+0): return self._r(reason="Outside 09:20-10:00 window")
        if self._sold: return self._r(reason="Already sold today")
        if not self.regime.allows_options_selling(): return self._r(reason=f"Regime/VIX not suitable")
        vix=self.regime.vix
        if not(12<=vix<=22): return self._r(reason=f"VIX={vix:.1f} outside 12-22")
        try:
            from option_chain import OptionChainResolver, next_thursday, nearest_strike, format_expiry_for_symbol
            spot=self.broker.get_ltp(config.NSE,f"{self.underlying} 50",self.underlying_token)
            oc=OptionChainResolver(self.broker)
            result=oc.get_straddle_tokens(self.underlying,spot)
            ce_sym,ce_tok=result["CE"]; pe_sym,pe_tok=result["PE"]
            qty=self.lot_size*self.lots
            ok,msg=self.risk.can_trade(spot*0.02*qty)
            if not ok: return self._r(action="BLOCKED",reason=msg)
            legs=[]; any_fail=False
            for sym,tok,leg in [(ce_sym,ce_tok,"CE"),(pe_sym,pe_tok,"PE")]:
                try:
                    oid=self.broker.place_order(sym,tok,config.NFO,"SELL",qty,"MARKET","CARRYFORWARD")
                    self.risk.on_order_placed(sym,"SELL",qty,0,self.name)
                    legs.append({"leg":leg,"symbol":sym,"order_id":oid})
                except BrokerOrderError as exc:
                    logger.error("[Straddle] %s failed: %s",sym,exc); any_fail=True
            if legs:
                self._sold=True
                return self._r(action="SELL_STRADDLE",signal=-1,
                               reason=f"ATM={result['atm_strike']} VIX={vix:.1f}",legs=legs)
            return self._r(action="ERROR",reason="Both legs failed")
        except Exception as exc: return self._r(reason=str(exc))


# ── 9. Iron Condor (Options — Thursday only) ─────────────────────────────────

class IronCondor(BaseStrategy):
    name="IronCondor"; category="options"

    def __init__(self,broker,risk,pm,regime,underlying="NIFTY",
                 underlying_token="99926000",lot_size=50,lots=1):
        super().__init__(broker,risk,pm,regime)
        self.underlying=underlying; self.underlying_token=underlying_token
        self.lot_size=lot_size; self.lots=lots; self._sold=False; self._date=None

    def run(self):
        if not self.enabled: return self._r(reason="Disabled")
        today=date.today()
        if self._date!=today: self._sold=False; self._date=today
        if today.weekday()!=3: return self._r(reason="Not Thursday")
        now=datetime.now(); t=now.hour*60+now.minute
        if not (9*60+30<=t<=10*60+30): return self._r(reason="Outside 09:30-10:30 window")
        if self._sold: return self._r(reason="Already sold today")
        if not self.regime.allows_options_selling(): return self._r(reason="Regime not suitable")
        vix=self.regime.vix
        if not(12<=vix<=18): return self._r(reason=f"VIX={vix:.1f} not in 12-18")
        try:
            from option_chain import OptionChainResolver
            spot=self.broker.get_ltp(config.NSE,f"{self.underlying} 50",self.underlying_token)
            oc=OptionChainResolver(self.broker)
            result=oc.get_iron_condor_tokens(self.underlying,spot)
            qty=self.lot_size*self.lots
            ok,msg=self.risk.can_trade(spot*0.01*qty)
            if not ok: return self._r(action="BLOCKED",reason=msg)
            legs=[]; any_fail=False
            for leg_type,(sym,tok) in [(k,v) for k,v in result.items() if k.endswith("_CE") or k.endswith("_PE")]:
                side="SELL" if "SELL" in leg_type else "BUY"
                try:
                    oid=self.broker.place_order(sym,tok,config.NFO,side,qty,"MARKET","CARRYFORWARD")
                    self.risk.on_order_placed(sym,side,qty,0,self.name)
                    legs.append({"leg":leg_type,"symbol":sym,"order_id":oid})
                except BrokerOrderError as exc:
                    logger.error("[IC] %s failed: %s",sym,exc); any_fail=True
            if legs:
                self._sold=True
                return self._r(action="IRON_CONDOR",signal=-1,
                               reason=f"VIX={vix:.1f} spot={spot:.0f}",legs=legs)
            return self._r(action="ERROR",reason="All IC legs failed")
        except Exception as exc: return self._r(reason=str(exc))


# ── 10. Momentum Breakout (Long-term) ─────────────────────────────────────────

class MomentumBreakout(BaseStrategy):
    name="MomentumBreakout"; category="longterm"

    def __init__(self,broker,risk,pm,regime,symbol,token,exchange="NSE",qty=1):
        super().__init__(broker,risk,pm,regime)
        self.symbol=symbol; self.token=token; self.exchange=exchange; self.qty=qty

    def run(self):
        if not self.enabled: return self._r(reason="Disabled")
        if datetime.now().day>7: return self._r(reason="Long-term: only first week of month")
        if not self._cooldown(self.symbol,60*24*20): return self._r(reason="20-day cooldown")
        if not self.regime.allows_long(): return self._r(reason=f"Regime={self.regime.regime}")
        try:
            df=self.broker.get_candles_days(self.symbol,self.token,self.exchange,"ONE_DAY",260)
            if len(df)<220: return self._r(reason="Need 220 days history")
            df.ta.sma(length=200,append=True); df.ta.rsi(length=14,append=True)
            atr=_atr(df); close=float(df["close"].iloc[-1])
            sma200_cols=[c for c in df.columns if "SMA_200" in c]
            rsi_cols=[c for c in df.columns if "RSI_14" in c]
            sma200=float(df[sma200_cols[0]].iloc[-1]) if sma200_cols else close
            rsi=float(df[rsi_cols[0]].iloc[-1]) if rsi_cols else 50
            h52w=float(df["high"].iloc[-253:-1].max()) if len(df)>253 else float(df["high"].max())
            if not(close>h52w and close>sma200 and 55<rsi<75 and _vol_ok(df,2.0)):
                return self._r(reason=f"No breakout close={close:.2f} 52wH={h52w:.2f}")
            ok,msg=self.risk.can_trade(close*self.qty)
            if not ok: return self._r(action="BLOCKED",reason=msg)
            sl=close-atr*2; target=close+atr*5
            res=self._place(self.symbol,self.token,self.exchange,"BUY",self.qty,close,
                            round(sl,2),round(target,2),"DELIVERY",atr)
            res.update({"signal":1,"52w_high":round(h52w,2),"rsi":round(rsi,1)})
            return res
        except BrokerDataError as exc: return self._r(reason=str(exc))

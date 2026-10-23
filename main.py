"""AlgoEdge — main engine. Run: python main.py --paper"""
from __future__ import annotations
import argparse, sys, time, threading, schedule
from datetime import datetime, date
import logzero
from logzero import logger
import config
from broker.angel_one import AngelOneBroker, BrokerLoginError
from risk.risk_manager import RiskManager
from position_manager import PositionManager
from market_regime import MarketRegime
from notifications import notify
from dashboard.app import run_dashboard
from strategies.strategies import (
    OpeningRangeBreakout, VWAPSupertrend, EMAMomentum,
    RSIDivergence, BollingerSqueeze, MACDHistogram,
    SupertrendFutures, ShortStraddleExpiry, IronCondor, MomentumBreakout)

logzero.logfile(str(config.LOG_DIR/"algoedge.log"),maxBytes=5_000_000,backupCount=3)
logzero.loglevel(logzero.DEBUG)

class PaperBroker(AngelOneBroker):
    def login(self):
        from datetime import timedelta
        self._logged_in=True; self._feed_token="paper"; self._jwt="paper"
        self._refresh_token="paper"; self._session_expiry=datetime.now()+timedelta(hours=8)
        logger.info("PAPER MODE — simulated login OK")
    def ensure_session(self): pass
    def place_order(self,symbol,token,exchange,side,qty,order_type="MARKET",product="INTRADAY",price=0,stoploss=0):
        import random; oid=f"PAPER-{random.randint(100000,999999)}"
        logger.info("[PAPER] %s %s×%d [%s] → %s",side,symbol,qty,product,oid); return oid
    def get_ltp(self,exchange,symbol,token):
        import random
        base={"RELIANCE-EQ":2900,"HDFCBANK-EQ":1640,"ICICIBANK-EQ":1265,"INFY-EQ":1840,"TCS-EQ":4200,"NIFTY 50":25900}.get(symbol,1000)
        return round(base*(1+random.uniform(-0.005,0.005)),2)
    def get_positions(self): return []
    def get_holdings(self):  return []
    def get_funds(self):     return {"availablecash":str(config.CAPITAL)}
    def square_off_all(self): logger.info("[PAPER] Square-off: no real positions."); return 0

class AlgoEngine:
    def __init__(self, paper=False):
        self.paper=paper
        self.broker=PaperBroker() if paper else AngelOneBroker()
        self.risk=RiskManager(); self.pm=PositionManager(self.broker)
        self.regime=MarketRegime(self.broker); self.strategies=[]; self._running=False
        if paper: logger.warning("━"*50+"\n  PAPER TRADING — no real orders\n"+"━"*50)

    def _load_strategies(self):
        b,r,p,rg=self.broker,self.risk,self.pm,self.regime
        self.strategies=[
            # ── INTRADAY ──────────────────────────────────────────────────────
            OpeningRangeBreakout(b,r,p,rg,symbol="RELIANCE-EQ",token="2885",exchange="NSE",qty=0),
            OpeningRangeBreakout(b,r,p,rg,symbol="HDFCBANK-EQ",token="1333",exchange="NSE",qty=0),
            VWAPSupertrend(b,r,p,rg,symbol="ICICIBANK-EQ",token="4963",exchange="NSE",qty=0),
            VWAPSupertrend(b,r,p,rg,symbol="INFY-EQ",token="1594",exchange="NSE",qty=0),
            EMAMomentum(b,r,p,rg,symbol="TCS-EQ",token="11536",exchange="NSE",qty=0),
            # ── SWING ─────────────────────────────────────────────────────────
            RSIDivergence(b,r,p,rg,symbol="RELIANCE-EQ",token="2885",exchange="NSE",qty=1),
            BollingerSqueeze(b,r,p,rg,symbol="HDFCBANK-EQ",token="1333",exchange="NSE",qty=1),
            MACDHistogram(b,r,p,rg,symbol="AXISBANK-EQ",token="5900",exchange="NSE",qty=1),
            # ── OPTIONS (Thursday only) ───────────────────────────────────────
            ShortStraddleExpiry(b,r,p,rg,underlying="NIFTY",underlying_token="99926000",lot_size=50,lots=1),
            # ── LONG TERM (first week of month) ──────────────────────────────
            MomentumBreakout(b,r,p,rg,symbol="TCS-EQ",token="11536",exchange="NSE",qty=1),
            MomentumBreakout(b,r,p,rg,symbol="BHARTIARTL-EQ",token="10604",exchange="NSE",qty=1),
        ]
        # ── AUTO-LOAD FUTURES ─────────────────────────────────────────────────
        try:
            from futures_token import FuturesResolver
            fr=FuturesResolver(self.broker)
            for ul in ["NIFTY","BANKNIFTY"]:
                try:
                    info=fr.get(ul)
                    self.strategies.append(SupertrendFutures(b,r,p,rg,symbol=info["symbol"],token=info["token"],lot_size=info["lot_size"],lots=1))
                    logger.info("[Futures] Loaded %s token=%s",info["symbol"],info["token"])
                except Exception as exc: logger.warning("[Futures] %s: %s",ul,exc)
        except Exception as exc: logger.warning("[Futures] Resolver error: %s",exc)
        logger.info("Loaded %d strategies.",len(self.strategies))

    def _mkt(self):
        now=datetime.now()
        if now.weekday()>=5: return False
        t=now.hour*60+now.minute
        return 9*60+15<=t<=15*60+30

    def _within(self,h1,m1,h2,m2):
        t=datetime.now().hour*60+datetime.now().minute
        return h1*60+m1<=t<=h2*60+m2

    def _run_cat(self,types,label):
        for s in self.strategies:
            if not isinstance(s,types) or not s.enabled: continue
            try:
                r=s.run()
                if r["action"] not in ("HOLD","BLOCKED","ERROR","Disabled","SIGNAL_ONLY"):
                    logger.info("[%s] %s → %s %s",label,s.name,r["action"],r.get("reason",""))
                    notify(f"{r['action']}: {r.get('symbol',s.name)}",f"Strategy:{r['strategy']}\n{r.get('reason','')}","INFO")
            except Exception as exc: logger.error("[%s] %s crashed: %s",label,s.name,exc)

    def _pre_market(self):
        logger.info("━"*60+"\n  Pre-market %s\n"+"━"*60,datetime.now().strftime("%d %b %Y %H:%M"))
        try:
            self.broker.login(); self._load_strategies()
            self.regime.detect(force=True)
            logger.info("Regime: %s  VIX=%.1f  Nifty=%.0f",self.regime.regime,self.regime.vix,self.regime.nifty)
            funds=self.broker.get_funds(); cash=funds.get("availablecash","N/A")
            logger.info("Available margin: ₹%s",cash)
            notify("AlgoEdge Started",f"Regime:{self.regime.regime}\nVIX:{self.regime.vix:.1f}\nStrategies:{len(self.strategies)}\nMargin:₹{cash}","INFO")
        except BrokerLoginError as exc:
            logger.critical("Login FAILED: %s",exc); notify("LOGIN FAILED",str(exc),"CRITICAL"); sys.exit(1)

    def _check_pos(self):
        if not self._mkt() or self.risk.is_killed: return
        for ev in self.pm.check_exits(self.risk):
            level="INFO" if ev["pnl"]>=0 else "WARNING"
            notify(f"{ev['reason']}: {ev['symbol']}",f"Strategy:{ev['strategy']}\nP&L:₹{ev['pnl']:+.2f}\nLTP:{ev['ltp']:.2f}",level)

    def _run_intraday(self):
        if not self._mkt() or self.risk.is_killed: return
        if not self._within(9,15,15,10): return
        self._run_cat((OpeningRangeBreakout,VWAPSupertrend,EMAMomentum),"INTRADAY")

    def _run_futures(self):
        if not self._mkt() or self.risk.is_killed: return
        if not self._within(9,30,15,10): return
        self._run_cat((SupertrendFutures,),"FUTURES")

    def _run_options(self):
        if not self._mkt() or self.risk.is_killed: return
        if datetime.now().weekday()!=3: return
        self._run_cat((ShortStraddleExpiry,IronCondor),"OPTIONS")

    def _run_swing(self):
        if self.risk.is_killed: return
        self._run_cat((RSIDivergence,BollingerSqueeze,MACDHistogram),"SWING")

    def _run_longterm(self):
        if self.risk.is_killed: return
        self._run_cat((MomentumBreakout,),"LONGTERM")

    def _refresh_regime(self):
        self.regime.detect(force=True)
        if self.regime.is_crash():
            logger.critical("CRASH regime — arming kill switch")
            self.risk.kill_switch("CRASH regime"); self.broker.square_off_all()
            notify("CRASH DETECTED","All positions squared off. Kill switch armed.","CRITICAL")

    def _squareoff(self):
        if not self._mkt(): return
        logger.warning("15:10 → Auto square-off all intraday positions...")
        count=self.broker.square_off_all(); notify("EOD Square-Off",f"{count} position(s) closed.","WARNING")

    def _eod(self):
        st=self.risk.status()
        msg=(f"AlgoEdge EOD — {date.today()}\n"
             f"Daily P&L  : ₹{st['daily_pnl']:,.2f}\n"
             f"Trades     : {st['trades_today']}\n"
             f"Drawdown   : {st['drawdown_pct']:.2f}%")
        logger.info(msg); notify("AlgoEdge EOD",msg,"INFO")
        try: self.broker.logout()
        except Exception: pass

    def start(self):
        self._running=True
        schedule.every().day.at("09:14").do(self._pre_market)
        schedule.every(1).minutes.do(self._check_pos)
        schedule.every(5).minutes.do(self._run_intraday)
        schedule.every(15).minutes.do(self._run_futures)
        schedule.every(30).minutes.do(self._refresh_regime)
        schedule.every(1).hours.do(self._run_swing)
        schedule.every(1).hours.do(self._run_options)
        schedule.every().day.at("10:00").do(self._run_longterm)
        schedule.every().day.at("15:10").do(self._squareoff)
        schedule.every().day.at("15:35").do(self._eod)
        now=datetime.now(); t=now.hour*60+now.minute
        if 9*60+14<=t<=15*60+30 and now.weekday()<5:
            logger.info("Market open — running pre-market immediately...")
            self._pre_market(); self._run_intraday()
        logger.info("Engine running. Press Ctrl+C to stop.")
        while self._running:
            schedule.run_pending(); time.sleep(15)

def main():
    p=argparse.ArgumentParser(description="AlgoEdge — Angel One Algo Trading",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  python main.py --paper\n  python main.py\n  python main.py --regime")
    p.add_argument("--paper",action="store_true"); p.add_argument("--regime",action="store_true")
    p.add_argument("--dashboard-only",action="store_true"); p.add_argument("--no-dashboard",action="store_true")
    args=p.parse_args()
    if not args.dashboard_only:
        try: config.validate()
        except EnvironmentError as exc: print(exc); sys.exit(1)
    if not args.no_dashboard:
        threading.Thread(target=run_dashboard,daemon=True).start()
        logger.info("Dashboard at http://localhost:%d",config.DASHBOARD_PORT)
    if args.dashboard_only:
        try:
            while True: time.sleep(60)
        except KeyboardInterrupt: pass
        return
    if args.regime:
        b=PaperBroker(); b.login(); rg=MarketRegime(b); r=rg.detect(force=True)
        print(f"\nRegime : {r}\nNifty  : {rg.nifty:.0f}\nVIX    : {rg.vix:.1f}\nLong OK: {rg.allows_long()}\nShort OK:{rg.allows_short()}\n")
        b.logout(); return
    engine=AlgoEngine(paper=args.paper)
    try: engine.start()
    except KeyboardInterrupt:
        logger.info("Stopped.")
        try: engine.broker.logout()
        except Exception: pass

if __name__=="__main__": main()

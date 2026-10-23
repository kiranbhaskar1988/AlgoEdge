"""Backtester — AlgoEdge. Usage: python backtest.py --strategy ORB --symbol RELIANCE --days 60"""
from __future__ import annotations
import argparse, math, sys
import pandas as pd, pandas_ta as ta, numpy as np
from datetime import datetime, timedelta
from tabulate import tabulate
import config
from broker.angel_one import AngelOneBroker, BrokerLoginError
from watchlist import get_token

def _atr(df, p=14):
    try:
        a = df.ta.atr(length=p)
        if a is not None and not a.empty:
            v = float(a.iloc[-1])
            if v > 0: return v
    except: pass
    return float(df["close"].iloc[-1]) * 0.01

def _vol(df, m=1.2):
    if "volume" not in df.columns or len(df) < 5: return True
    avg = df["volume"].iloc[-21:-1].mean()
    return avg > 0 and float(df["volume"].iloc[-1]) >= avg * m

class Trade:
    def __init__(self, e_dt, x_dt, side, ep, xp, qty, sym, strat):
        self.e_dt=e_dt; self.x_dt=x_dt; self.side=side; self.ep=ep; self.xp=xp
        self.qty=qty; self.sym=sym; self.strat=strat
        self.pnl=((xp-ep) if side=="BUY" else (ep-xp))*qty
        self.pct=self.pnl/(ep*qty)*100 if ep*qty else 0
    def row(self):
        dt=lambda d: str(d)[:10]
        return [dt(self.e_dt),dt(self.x_dt),self.side,f"{self.ep:,.0f}",f"{self.xp:,.0f}",f"₹{self.pnl:+.0f}",f"{self.pct:+.1f}%"]

def metrics(trades, capital):
    if not trades: return {}
    tp=sum(t.pnl for t in trades); wins=[t for t in trades if t.pnl>0]; losses=[t for t in trades if t.pnl<=0]
    aw=sum(t.pnl for t in wins)/len(wins) if wins else 0; al=sum(t.pnl for t in losses)/len(losses) if losses else 0
    eq=capital; peak=capital; mdd=0
    for t in trades:
        eq+=t.pnl
        if eq>peak: peak=eq
        dd=(peak-eq)/peak*100
        if dd>mdd: mdd=dd
    mu=tp/len(trades); std=math.sqrt(sum((t.pnl-mu)**2 for t in trades)/max(1,len(trades)-1))
    sh=(mu/std)*math.sqrt(252) if std else 0
    return {"Total Trades":len(trades),"Wins":len(wins),"Losses":len(losses),
            "Win Rate":f"{len(wins)/len(trades)*100:.1f}%","Total P&L":f"₹{tp:,.2f}",
            "Avg Win":f"₹{aw:,.2f}","Avg Loss":f"₹{al:,.2f}",
            "Risk/Reward":f"{abs(aw/al):.2f}" if al else "∞",
            "Max Drawdown":f"{mdd:.1f}%","Sharpe":f"{sh:.2f}","Return":f"{tp/capital*100:.2f}%"}

def bt_orb(df, sym, qty=1):
    trades=[]; df["vwap_d"]=df.index.date
    dates=df.index.normalize().unique()
    for day in dates:
        dd=df[df.index.normalize()==day]
        if len(dd)<5: continue
        orb_h=float(dd["high"].iloc[:3].max()); orb_l=float(dd["low"].iloc[:3].min())
        r=orb_h-orb_l;
        if r<=0: continue
        atr=_atr(dd,5); in_t=False; ep=sl=tgt=0.0; side=""; ei=None
        for i in range(3,len(dd)):
            row=dd.iloc[i]; close=float(row["close"]); vol=_vol(dd.iloc[:i+1],1.5)
            if not in_t:
                if close>orb_h+atr*0.1 and vol: in_t=True;side="BUY";ep=close;sl=orb_h-atr*0.5;tgt=close+r*2;ei=i
                elif close<orb_l-atr*0.1 and vol: in_t=True;side="SELL";ep=close;sl=orb_l+atr*0.5;tgt=close-r*2;ei=i
            else:
                hit_sl=(close<=sl) if side=="BUY" else (close>=sl)
                hit_tgt=(close>=tgt) if side=="BUY" else (close<=tgt)
                if hit_sl or hit_tgt or i==len(dd)-1:
                    xp=sl if hit_sl else (tgt if hit_tgt else close)
                    trades.append(Trade(dd.index[ei],dd.index[i],side,ep,xp,qty,sym,"ORB")); in_t=False; break
    return trades

def bt_vwap(df, sym, qty=1):
    trades=[]; df.ta.rsi(length=14,append=True)
    df["_d"]=df.index.date; df["_tp"]=(df["high"]+df["low"]+df["close"])/3; df["_tpv"]=df["_tp"]*df["volume"]
    df["vwap"]=df.groupby("_d")["_tpv"].cumsum()/df.groupby("_d")["volume"].cumsum().replace(0,np.nan)
    st=df.ta.supertrend(length=10,multiplier=3)
    if st is None: return trades
    df=pd.concat([df,st],axis=1); stc=[c for c in df.columns if "SUPERTd" in c]
    if not stc: return trades
    atr=_atr(df); in_t=False; ep=sl=tgt=0.0; side=""; ei=None
    for i in range(20,len(df)):
        row=df.iloc[i]; close=float(row["close"]); vwap=float(row["vwap"]) if not pd.isna(row["vwap"]) else close
        rsi=float(row.get("RSI_14",50)); st_d=int(row[stc[0]]); vol=_vol(df.iloc[:i+1],1.2)
        if not in_t:
            if close>vwap and st_d==1 and 50<rsi<72 and vol: in_t=True;side="BUY";ep=close;sl=close-atr*1.5;tgt=close+atr*3;ei=i
            elif close<vwap and st_d==-1 and 28<rsi<50 and vol: in_t=True;side="SELL";ep=close;sl=close+atr*1.5;tgt=close-atr*3;ei=i
        else:
            if side=="BUY": ns=close-atr*1.5; sl=max(sl,ns)
            else: ns=close+atr*1.5; sl=min(sl,ns)
            hit_sl=(close<=sl) if side=="BUY" else (close>=sl)
            hit_tgt=(close>=tgt) if side=="BUY" else (close<=tgt)
            if hit_sl or hit_tgt or i==len(df)-1:
                trades.append(Trade(df.index[ei],df.index[i],side,ep,sl if hit_sl else (tgt if hit_tgt else close),qty,sym,"VWAP")); in_t=False
    return trades

def bt_rsi(df, sym, qty=1):
    trades=[]; df.ta.rsi(length=14,append=True); df.ta.sma(length=50,append=True)
    atr=_atr(df); in_t=False; ep=sl=tgt=0.0; side=""; ei=None; hold=0
    for i in range(20,len(df)):
        close=float(df["close"].iloc[i])
        rsi_c=[c for c in df.columns if "RSI_14" in c]; sma_c=[c for c in df.columns if "SMA_50" in c]
        rsi=float(df[rsi_c[0]].iloc[i]) if rsi_c else 50; sma=float(df[sma_c[0]].iloc[i]) if sma_c else close
        if not in_t:
            prv=df["close"].iloc[i-1]; bull=df["close"].iloc[i-1]>df["open"].iloc[i-1]
            if rsi<30 and bull and close>sma: in_t=True;side="BUY";ep=close;sl=close-atr*2;tgt=close+atr*4;ei=i;hold=0
            elif rsi>70 and not bull and close<sma: in_t=True;side="SELL";ep=close;sl=close+atr*2;tgt=close-atr*4;ei=i;hold=0
        else:
            hold+=1; hit_sl=(close<=sl) if side=="BUY" else (close>=sl); hit_tgt=(close>=tgt) if side=="BUY" else (close<=tgt)
            if hit_sl or hit_tgt or hold>=15:
                trades.append(Trade(df.index[ei],df.index[i],side,ep,sl if hit_sl else (tgt if hit_tgt else close),qty,sym,"RSIDivergence")); in_t=False
    return trades

def bt_bb(df, sym, qty=1):
    trades=[]; bb=df.ta.bbands(length=20,std=2)
    if bb is None: return trades
    df=pd.concat([df,bb],axis=1); up=[c for c in df.columns if "BBU_" in c]; lo=[c for c in df.columns if "BBL_" in c]; mi=[c for c in df.columns if "BBM_" in c]
    if not up: return trades
    df["bbw"]=(df[up[0]]-df[lo[0]])/df[mi[0]]; atr=_atr(df); in_t=False; ep=sl=tgt=0.0; side=""; ei=None
    for i in range(22,len(df)):
        avg=float(df["bbw"].iloc[i-20:i].mean()); cur=float(df["bbw"].iloc[i]); close=float(df["close"].iloc[i])
        if not in_t and cur<avg*0.80:
            vol=_vol(df.iloc[:i+1],1.5)
            if close>float(df[up[0]].iloc[i]) and vol: in_t=True;side="BUY";ep=close;sl=close-atr*2;tgt=close+atr*4;ei=i
            elif close<float(df[lo[0]].iloc[i]) and vol: in_t=True;side="SELL";ep=close;sl=close+atr*2;tgt=close-atr*4;ei=i
        elif in_t:
            hit_sl=(close<=sl) if side=="BUY" else (close>=sl); hit_tgt=(close>=tgt) if side=="BUY" else (close<=tgt)
            if hit_sl or hit_tgt or (i-ei)>=12:
                trades.append(Trade(df.index[ei],df.index[i],side,ep,sl if hit_sl else (tgt if hit_tgt else close),qty,sym,"BollingerSqueeze")); in_t=False
    return trades

STRATS={"ORB":("FIVE_MINUTE",30,bt_orb),"VWAP":("FIVE_MINUTE",30,bt_vwap),
        "RSIDivergence":("ONE_DAY",90,bt_rsi),"BollingerSqueeze":("ONE_DAY",90,bt_bb)}
ALL_SYMS={"ORB":["RELIANCE","HDFCBANK"],"VWAP":["ICICIBANK","INFY"],
          "RSIDivergence":["TCS","HDFCBANK"],"BollingerSqueeze":["RELIANCE","AXISBANK"]}

def run(strat, sym, days, qty, broker):
    interval,ddays,fn=STRATS[strat]; days=days or ddays
    tok=get_token(sym) or get_token(sym.replace("-EQ",""))
    if not tok: print(f"Token not found for {sym}. Check watchlist.py"); return []
    print(f"  Fetching {sym} ({interval},{days}d)...",end=" ",flush=True)
    try:
        df=broker.get_candles_days(sym,tok,"NSE",interval,days); print(f"{len(df)} candles")
    except Exception as exc: print(f"FAILED: {exc}"); return []
    return fn(df,sym,qty)

def show(strat,sym,trades):
    m=metrics(trades,config.CAPITAL)
    if not m: print(f"  No trades for {strat} on {sym}\n"); return
    print(f"\n  {'─'*50}\n  {strat} on {sym}\n  {'─'*50}")
    print(tabulate([[k,v] for k,v in m.items()],headers=["Metric","Value"],tablefmt="rounded_outline"))
    if trades:
        print("\n  Last 10 trades:")
        print(tabulate([t.row() for t in trades[-10:]],headers=["Entry","Exit","Side","Entry₹","Exit₹","P&L","P&L%"],tablefmt="simple"))
    out=config.DATA_DIR/f"bt_{strat}_{sym}.csv"
    import csv
    with open(out,"w",newline="") as f:
        w=csv.writer(f); w.writerow(["strategy","symbol","side","entry_dt","exit_dt","entry","exit","pnl","pct"])
        for t in trades: w.writerow([t.strat,t.sym,t.side,t.e_dt,t.x_dt,t.ep,t.xp,round(t.pnl,2),round(t.pct,2)])
    print(f"  Saved: {out}")

def main():
    p=argparse.ArgumentParser(description="AlgoEdge Backtester")
    p.add_argument("--strategy",choices=list(STRATS)); p.add_argument("--symbol",default="RELIANCE")
    p.add_argument("--days",default=0,type=int); p.add_argument("--qty",default=1,type=int)
    p.add_argument("--all",action="store_true"); args=p.parse_args()
    print("\n"+"━"*55+"\n  AlgoEdge Backtester\n"+"━"*55)
    try: config.validate()
    except EnvironmentError as exc: print(exc); sys.exit(1)
    from main import PaperBroker
    b=PaperBroker(); b.login()
    try:
        if args.all:
            all_t=[]
            for s,syms in ALL_SYMS.items():
                for sym in syms:
                    t=run(s,sym,0,args.qty,b); all_t.extend(t); show(s,sym,t)
            if all_t:
                print("\n"+"━"*55+"\n  OVERALL SUMMARY\n"+"━"*55)
                print(tabulate([[k,v] for k,v in metrics(all_t,config.CAPITAL).items()],headers=["Metric","Value"],tablefmt="rounded_outline"))
        else:
            if not args.strategy: p.error("--strategy required")
            show(args.strategy,args.symbol,run(args.strategy,args.symbol,args.days,args.qty,b))
    finally: b.logout()
    print()

if __name__=="__main__": main()

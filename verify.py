"""Verify installation — AlgoEdge. Run: python verify.py"""
import sys, subprocess, argparse
G="\033[92m"; R="\033[91m"; Y="\033[93m"; B="\033[94m"; N="\033[0m"; W="\033[1m"
ok_n=fail_n=warn_n=0
def ok(m,d=""): global ok_n; ok_n+=1; print(f"  {G}✔{N}  {m}"+(f"  {Y}({d}){N}" if d else ""))
def fail(m,f=""): global fail_n; fail_n+=1; print(f"  {R}✗{N}  {m}"); f and print(f"     {Y}Fix: {f}{N}")
def warn(m): global warn_n; warn_n+=1; print(f"  {Y}⚠{N}  {m}")
def sec(t): print(f"\n{W}{B}── {t} ──{N}")

def check_python():
    sec("Python Version")
    v=sys.version_info; vs=f"{v.major}.{v.minor}.{v.micro}"
    if v.major==3 and 10<=v.minor<=12: ok(f"Python {vs}","compatible ✓")
    elif v.major==3 and v.minor==13: warn(f"Python {vs} — most packages work but some may have issues")
    elif v.major==3 and v.minor>=14: fail(f"Python {vs}","Install Python 3.12 from https://www.python.org/downloads/")
    else: fail(f"Python {vs}","Need Python 3.10, 3.11 or 3.12")

def check_pkg(mod, name=None, pip_name=None):
    name=name or mod; pip_name=pip_name or mod
    try:
        m=__import__(mod); ver=getattr(m,"__version__","?"); ok(name,f"v{ver}")
        return m
    except ImportError: fail(name,f"pip install {pip_name}"); return None

def check_packages():
    sec("Core Packages")
    check_pkg("numpy"); pd=check_pkg("pandas")
    if pd:
        v=tuple(int(x) for x in pd.__version__.split(".")[:2])
        ok("pandas version",">=2.2 ✓") if v>=(2,2) else warn(f"pandas {pd.__version__} — recommend >=2.2.0")
    sec("Indicators")
    ta=check_pkg("pandas_ta","pandas-ta","pandas-ta>=0.4.67b0")
    if ta:
        try:
            import pandas as p, numpy as n
            df=p.DataFrame({"open":n.random.rand(30)*100+100,"high":n.random.rand(30)*100+105,
                "low":n.random.rand(30)*100+95,"close":n.random.rand(30)*100+100,"volume":n.random.rand(30)*1e6})
            df.ta.ema(length=9,append=True); df.ta.rsi(length=14,append=True)
            df.ta.supertrend(length=7,multiplier=3)
            ok("pandas-ta functional test","EMA/RSI/Supertrend work ✓")
        except Exception as e: fail(f"pandas-ta functional test: {e}")
    sec("Angel One API")
    check_pkg("SmartApi","smartapi-python","smartapi-python>=1.3.9"); check_pkg("pyotp"); check_pkg("websocket","websocket-client","websocket-client>=1.7.0")
    sec("Web Dashboard")
    check_pkg("flask"); check_pkg("flask_socketio","flask-socketio","flask-socketio>=5.3.0")
    sec("Utilities")
    for m,n,p in [("dotenv","python-dotenv","python-dotenv>=1.0.0"),("schedule",None,None),
                  ("requests",None,None),("logzero",None,None),("colorama",None,None),
                  ("tabulate",None,None),("dateutil","python-dateutil","python-dateutil>=2.9.0"),("pytz",None,None)]:
        check_pkg(m,n,p)

def check_files():
    sec("Project Files")
    from pathlib import Path
    for f in ["main.py","config.py","broker/angel_one.py","strategies/strategies.py",
              "risk/risk_manager.py","position_manager.py","market_regime.py",
              "option_chain.py","futures_token.py","dashboard/app.py",
              "notifications.py","watchlist.py","backtest.py",".env.example"]:
        if Path(f).exists(): ok(f)
        else: fail(f,"Re-extract algoedge.zip")

def check_env():
    sec(".env Configuration")
    from pathlib import Path
    ep=Path(".env")
    if not ep.exists(): fail(".env file","Copy .env.example to .env and fill in credentials"); return
    ok(".env file exists")
    c=ep.read_text()
    for k in ["ANGEL_API_KEY","ANGEL_CLIENT_ID","ANGEL_PASSWORD","ANGEL_TOTP_SECRET"]:
        if k not in c: fail(f"{k}",f"Add {k}=your_value to .env"); continue
        for line in c.splitlines():
            if line.strip().startswith(k):
                val=line.split("=",1)[1].strip().replace(" ","")
                if val in ("","your_api_key_here","your_totp_secret_here","A123456","1234"):
                    warn(f"{k} has placeholder — fill in real value")
                else: ok(f"{k} set")
    try:
        import os; from dotenv import load_dotenv; load_dotenv()
        import pyotp; s=os.getenv("ANGEL_TOTP_SECRET","")
        if s and "your_" not in s:
            code=pyotp.TOTP(s).now()
            ok("TOTP generates valid code",f"current={code}") if len(code)==6 and code.isdigit() else fail("TOTP invalid","Check ANGEL_TOTP_SECRET")
    except Exception as e: warn(f"TOTP check skipped: {e}")

def check_imports():
    sec("AlgoEdge Modules")
    for mod,cls in [("broker.angel_one","AngelOneBroker"),("risk.risk_manager","RiskManager"),
                    ("position_manager","PositionManager"),("market_regime","MarketRegime"),
                    ("option_chain","OptionChainResolver"),("futures_token","FuturesResolver"),
                    ("strategies.strategies","OpeningRangeBreakout"),
                    ("strategies.strategies","VWAPSupertrend"),
                    ("strategies.strategies","EMAMomentum"),
                    ("strategies.strategies","RSIDivergence"),
                    ("strategies.strategies","BollingerSqueeze"),
                    ("strategies.strategies","MACDHistogram"),
                    ("strategies.strategies","SupertrendFutures"),
                    ("strategies.strategies","ShortStraddleExpiry"),
                    ("strategies.strategies","IronCondor"),
                    ("strategies.strategies","MomentumBreakout"),
                    ("dashboard.app","run_dashboard"),("watchlist","get_token")]:
        try:
            m=__import__(mod,fromlist=[cls]); assert hasattr(m,cls); ok(f"{mod}.{cls}")
        except Exception as e: fail(f"{mod}.{cls}",str(e)[:80])

def auto_fix():
    print(f"\n{W}Auto-fixing...{N}")
    for pkg in ["numpy>=1.26.0","pandas>=2.2.0","pandas-ta>=0.4.67b0","smartapi-python>=1.3.9",
                "pyotp>=2.9.0","websocket-client>=1.7.0","flask>=3.0.0","flask-socketio>=5.3.0",
                "python-dotenv>=1.0.0","schedule>=1.2.0","requests>=2.31.0","logzero>=1.7.0",
                "colorama>=0.4.6","tabulate>=0.9.0","python-dateutil>=2.9.0","pytz>=2024.1"]:
        name=pkg.split(">=")[0]; print(f"  {name}...",end=" ",flush=True)
        r=subprocess.run([sys.executable,"-m","pip","install",pkg,"--prefer-binary","--quiet"],capture_output=True)
        print(f"{G}✔{N}" if r.returncode==0 else f"{R}✗{N}")

def summary(t0):
    import time; el=time.time()-t0; tot=ok_n+fail_n+warn_n
    print(f"\n{'━'*50}\n  {tot} checks  {G}{ok_n} passed{N}  {R}{fail_n} failed{N}  {Y}{warn_n} warnings{N}  ({el:.1f}s)\n{'━'*50}")
    if fail_n==0: print(f"\n  {G}{W}All checks passed — ready to trade!{N}\n  Next: python main.py --paper\n")
    else: print(f"\n  {R}Fix {fail_n} failed check(s) above, then run: python verify.py --fix\n")

def main():
    import time; t0=time.time()
    p=argparse.ArgumentParser(); p.add_argument("--fix",action="store_true"); args=p.parse_args()
    print(f"\n{W}{'━'*50}\n  AlgoEdge — Installation Verifier\n{'━'*50}{N}")
    if args.fix: auto_fix()
    check_python(); check_packages(); check_files(); check_env(); check_imports(); summary(t0)

if __name__=="__main__": main()

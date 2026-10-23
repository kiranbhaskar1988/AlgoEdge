"""Dashboard — AlgoEdge"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template_string, jsonify, redirect
import config

app = Flask(__name__)
app.secret_key = config.DASHBOARD_SECRET_KEY
STATE = config.DATA_DIR / "risk_state.json"
POS   = config.DATA_DIR / "positions.json"
LOG   = config.LOG_DIR  / "algoedge.log"

def _s():
    try: return json.loads(STATE.read_text()) if STATE.exists() else {}
    except: return {}
def _p():
    try: raw=json.loads(POS.read_text()) if POS.exists() else []; return [x for x in raw if x.get("status")=="OPEN"]
    except: return []
def _l(n=60):
    try: return (LOG.read_text(encoding="utf-8",errors="replace").splitlines())[-n:] if LOG.exists() else ["Log not found — start main.py"]
    except: return []

HTML="""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15">
<title>AlgoEdge</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0D1117;--sf:#161B22;--sf2:#1C2128;--bd:#30363D;--bl:#1F6FEB;--gr:#3FB950;--rd:#F85149;--yw:#D29922;--tx:#E6EDF3;--tx2:#8B949E;--tx3:#6E7681;--mono:'JetBrains Mono',monospace}
body{background:var(--bg);color:var(--tx);font-family:Inter,sans-serif;font-size:13px}
.top{background:var(--sf);border-bottom:1px solid var(--bd);height:48px;display:flex;align-items:center;padding:0 20px;gap:12px;position:sticky;top:0;z-index:99}
.logo{font-family:var(--mono);font-weight:700;font-size:16px}.logo span{color:var(--bl)}
.ml{margin-left:auto;display:flex;gap:8px;align-items:center}
.ts{font-family:var(--mono);font-size:11px;color:var(--tx3)}
.rp{padding:3px 10px;border-radius:4px;font-size:11px;font-family:var(--mono);border:1px solid}
.rb{background:rgba(63,185,80,.12);color:var(--gr);border-color:rgba(63,185,80,.4)}
.rr{background:rgba(248,81,73,.12);color:var(--rd);border-color:rgba(248,81,73,.4)}
.ry{background:rgba(210,153,34,.12);color:var(--yw);border-color:rgba(210,153,34,.4)}
.kb{background:rgba(248,81,73,.15);border:1px solid var(--rd);color:var(--rd);padding:5px 14px;border-radius:5px;cursor:pointer;font-family:var(--mono);font-weight:700;font-size:11px}
.kb:hover{background:rgba(248,81,73,.3)}
.rstb{background:rgba(63,185,80,.1);border:1px solid rgba(63,185,80,.4);color:var(--gr);padding:5px 14px;border-radius:5px;cursor:pointer;font-family:var(--mono);font-size:11px}
.w{max-width:1400px;margin:0 auto;padding:20px;display:grid;gap:16px}
.sr{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
.c{background:var(--sf);border:1px solid var(--bd);border-radius:8px;padding:14px}
.ct{font-size:10px;color:var(--tx3);text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px}
.cv{font-family:var(--mono);font-size:24px;font-weight:700;line-height:1}
.cs{font-size:10px;color:var(--tx3);margin-top:4px;font-family:var(--mono)}
.pos{color:var(--gr)}.neg{color:var(--rd)}.warn{color:var(--yw)}.blue{color:var(--bl)}
.tc{display:grid;grid-template-columns:1fr 340px;gap:16px}
table{width:100%;border-collapse:collapse}
th{font-size:10px;color:var(--tx3);font-weight:500;text-transform:uppercase;letter-spacing:.4px;padding:7px 10px;text-align:left;background:var(--sf2);border-bottom:1px solid var(--bd)}
td{padding:7px 10px;border-bottom:1px solid #21262D;font-family:var(--mono);font-size:11px}
tr:last-child td{border-bottom:none}tr:hover td{background:rgba(255,255,255,.02)}
.sb{padding:2px 7px;border-radius:3px;font-size:10px;font-weight:600}
.sb-b{background:rgba(63,185,80,.15);color:var(--gr)}.sb-s{background:rgba(248,81,73,.15);color:var(--rd)}
.lb{background:var(--sf2);border-radius:6px;padding:10px;max-height:320px;overflow-y:auto;font-family:var(--mono);font-size:10px;line-height:1.9}
.ll{border-bottom:1px solid #21262D;color:var(--tx3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ll:last-child{border:none}.ok{color:var(--gr)}.er{color:var(--rd)}.inf{color:var(--bl)}
.bw{background:var(--bd);border-radius:3px;height:4px;margin-top:6px}
.b{height:4px;border-radius:3px}.bg{background:var(--gr)}.by{background:var(--yw)}.br{background:var(--rd)}
.sr2{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid #21262D;font-size:12px}
.sr2:last-child{border:none}
@media(max-width:900px){.sr{grid-template-columns:repeat(2,1fr)}.tc{grid-template-columns:1fr}}
</style></head><body>
<div class="top">
  <div class="logo">Algo<span>Edge</span></div>
  <span class="rp {{rcls}}">{{regime}}</span>
  <span style="font-family:var(--mono);font-size:11px;color:var(--tx3)">VIX {{vix}} · Nifty {{nifty}}</span>
  <div class="ml">
    <span class="ts">{{now}}</span>
    {% if kill %}
    <form method="POST" action="/reset_kill"><button class="rstb">✔ Reset Kill</button></form>
    {% else %}
    <form method="POST" action="/kill" onsubmit="return confirm('Arm kill switch?')"><button class="kb">⬛ KILL ALL</button></form>
    {% endif %}
  </div>
</div>
<div class="w">
  <div class="sr">
    <div class="c"><div class="ct">Daily P&L</div><div class="cv {{pcls}}">{{psign}}₹{{pnl}}</div><div class="cs">{{trades}} trades today</div></div>
    <div class="c"><div class="ct">Open Positions</div><div class="cv blue">{{open}} / {{maxp}}</div><div class="bw"><div class="b bg" style="width:{{opct}}%"></div></div></div>
    <div class="c"><div class="ct">Drawdown</div><div class="cv {{ddcls}}">{{dd}}%</div><div class="cs">peak ₹{{peak}}</div></div>
    <div class="c"><div class="ct">Deployed</div><div class="cv warn">{{dep}}%</div><div class="bw"><div class="b by" style="width:{{dep}}%"></div></div></div>
    <div class="c"><div class="ct">Kill Switch</div><div class="cv {{kcls}}">{{kstr}}</div><div class="cs">Limit ₹{{lim}}</div></div>
  </div>
  <div class="tc">
    <div style="display:flex;flex-direction:column;gap:16px">
      <div class="c">
        <div class="ct" style="margin-bottom:10px">Open Positions</div>
        {% if positions %}
        <table><thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>SL</th><th>Target</th><th>Strategy</th></tr></thead>
        <tbody>{% for p in positions %}<tr>
          <td style="font-weight:600">{{p.symbol}}</td>
          <td><span class="sb {{'sb-b' if p.side=='BUY' else 'sb-s'}}">{{p.side}}</span></td>
          <td>{{p.qty}}</td><td>{{p.entry_price}}</td>
          <td class="neg">{{p.sl_price}}</td><td class="pos">{{p.target_price}}</td>
          <td>{{p.strategy}}</td></tr>{% endfor %}
        </tbody></table>
        {% else %}<div style="color:var(--tx3);padding:10px 0">No open positions.</div>{% endif %}
      </div>
      <div class="c"><div class="ct" style="margin-bottom:8px">Live Log</div>
        <div class="lb">{% for l in logs %}<div class="ll {{'ok' if '✔' in l or 'OK' in l.upper() else 'er' if 'ERROR' in l.upper() or 'FAIL' in l.upper() else 'inf' if 'SIGNAL' in l.upper() else ''}}">{{l}}</div>{% endfor %}</div>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;gap:16px">
      <div class="c"><div class="ct" style="margin-bottom:8px">Strategy P&L</div>
        {% for n,v in spnl.items() %}<div class="sr2"><span>{{n}}</span><span class="cv {{'pos' if v>=0 else 'neg'}}" style="font-size:13px">{{'+'if v>=0 else ''}}₹{{"{:.0f}".format(v)}}</span></div>{% endfor %}
        {% if not spnl %}<div style="color:var(--tx3);font-size:12px">No trades yet.</div>{% endif %}
      </div>
      <div class="c"><div class="ct" style="margin-bottom:10px">Risk Limits</div>
        <div class="sr2"><span style="color:var(--tx3)">Loss used</span><span style="font-family:var(--mono)">₹{{lused}} / ₹{{lim}}</span></div>
        <div class="bw"><div class="b {{lbcls}}" style="width:{{lpct}}%"></div></div>
        <div class="sr2" style="margin-top:8px"><span style="color:var(--tx3)">Capital</span><span style="font-family:var(--mono)">₹{{cap}}</span></div>
        <div class="sr2"><span style="color:var(--tx3)">Per-trade limit</span><span style="font-family:var(--mono)">₹{{ptl}}</span></div>
      </div>
    </div>
  </div>
</div></body></html>"""

def _fmt(v):
    try: return f"{abs(float(v)):,.0f}"
    except: return str(v)

@app.route("/")
def index():
    s=_s(); p=_p(); pnl=float(s.get("daily_pnl",0)); op=int(s.get("open_count",0))
    kill=bool(s.get("kill",False)); peak=float(s.get("peak_equity",config.CAPITAL))
    dd=round((peak-(config.CAPITAL+pnl))/peak*100,1) if peak else 0
    lused=abs(min(pnl,0)); lpct=min(100,round(lused/config.MAX_DAILY_LOSS*100,0))
    regime=s.get("regime","UNKNOWN")
    rcls={"BULL":"rb","BEAR":"rr","RANGE":"ry","CRASH":"rr"}.get(regime,"ry")
    return render_template_string(HTML,
        now=datetime.now().strftime("%d %b %Y  %H:%M:%S"),
        pnl=_fmt(pnl),psign="+" if pnl>=0 else "−",pcls="pos" if pnl>=0 else "neg",
        trades=len(s.get("trades",[])),open=op,maxp=config.MAX_OPEN_POSITIONS,
        opct=min(100,int(op/config.MAX_OPEN_POSITIONS*100)),
        dep=min(100,round(op*config.MAX_CAPITAL_PER_TRADE/config.CAPITAL*100,1)),
        dd=dd,ddcls="neg" if dd>5 else ("warn" if dd>2 else "pos"),peak=_fmt(peak),
        kill=kill,kstr="ARMED" if kill else "SAFE",kcls="neg" if kill else "pos",
        lim=_fmt(config.MAX_DAILY_LOSS),lused=_fmt(lused),lpct=int(lpct),
        lbcls="br" if lpct>70 else ("by" if lpct>40 else "bg"),
        cap=_fmt(config.CAPITAL),ptl=_fmt(config.MAX_CAPITAL_PER_TRADE),
        positions=p,spnl=s.get("strategy_pnl",{}),
        regime=regime,rcls=rcls,vix=s.get("vix","—"),nifty=s.get("nifty","—"),
        logs=_l(60))

@app.route("/api/status")
def api_status():
    return jsonify(_s())

@app.route("/kill",methods=["POST"])
def kill():
    s=_s(); s["kill"]=True; STATE.write_text(json.dumps(s,indent=2)); return redirect("/")

@app.route("/reset_kill",methods=["POST"])
def reset_kill():
    s=_s(); s["kill"]=False; s["consec_losses"]={}; STATE.write_text(json.dumps(s,indent=2)); return redirect("/")

def run_dashboard():
    app.run(host="0.0.0.0",port=config.DASHBOARD_PORT,debug=False,use_reloader=False)

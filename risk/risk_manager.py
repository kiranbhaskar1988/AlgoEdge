"""Risk Manager — AlgoEdge"""
from __future__ import annotations
import json
from collections import defaultdict
from datetime import date, datetime
from logzero import logger
import config

class RiskManager:
    STATE_FILE = config.DATA_DIR / "risk_state.json"

    def __init__(self):
        self._pnl = 0.0; self._peak = config.CAPITAL
        self._open = 0; self._trades = []; self._kill = False
        self._consec = defaultdict(int); self._spnl = defaultdict(float)
        self._load()

    def _load(self):
        if not self.STATE_FILE.exists(): return
        try:
            s = json.loads(self.STATE_FILE.read_text())
            if s.get("date") == str(date.today()):
                self._pnl    = float(s.get("daily_pnl",  0))
                self._open   = int(  s.get("open_count", 0))
                self._trades = s.get("trades", [])
                self._kill   = bool( s.get("kill", False))
                self._peak   = float(s.get("peak_equity", config.CAPITAL))
                self._consec = defaultdict(int,   s.get("consec_losses", {}))
                self._spnl   = defaultdict(float, s.get("strategy_pnl",  {}))
        except Exception as exc: logger.warning("Risk load: %s", exc)

    def _save(self):
        try:
            self.STATE_FILE.write_text(json.dumps({
                "date": str(date.today()), "daily_pnl": self._pnl,
                "open_count": self._open, "trades": self._trades[-500:],
                "kill": self._kill, "peak_equity": self._peak,
                "consec_losses": dict(self._consec),
                "strategy_pnl":  dict(self._spnl)}, indent=2))
        except Exception as exc: logger.warning("Risk save: %s", exc)

    def can_trade(self, capital=0, strategy=""):
        if self._kill: return False, "KILL SWITCH ACTIVE"
        if self._pnl <= -config.MAX_DAILY_LOSS:
            self._arm("Daily loss limit"); return False, "Daily loss limit reached"
        dd = (self._peak - (config.CAPITAL + self._pnl)) / self._peak * 100
        if dd > 10: self._arm(f"Drawdown {dd:.1f}%"); return False, f"Drawdown {dd:.1f}% exceeded"
        if self._open >= config.MAX_OPEN_POSITIONS: return False, "Max positions reached"
        if 0 < capital > config.MAX_CAPITAL_PER_TRADE: return False, "Trade size exceeds limit"
        if strategy and self._consec[strategy] >= 3: return False, f"{strategy} paused (3 losses)"
        return True, ""

    def on_order_placed(self, symbol, side, qty, price, strategy):
        if side == "BUY": self._open += 1
        self._trades.append({"time": datetime.now().isoformat(),
            "symbol": symbol, "side": side, "qty": qty, "price": price, "strategy": strategy})
        self._save()

    def on_position_closed(self, symbol, pnl, strategy=""):
        self._pnl += pnl; self._open = max(0, self._open - 1)
        if strategy:
            self._spnl[strategy] += pnl
            self._consec[strategy] = self._consec[strategy] + 1 if pnl < 0 else 0
        cur = config.CAPITAL + self._pnl
        if cur > self._peak: self._peak = cur
        self._save()
        logger.info("[Risk] Closed %s P&L=₹%.2f Daily=₹%.2f", symbol, pnl, self._pnl)
        if self._pnl <= -config.MAX_DAILY_LOSS: self._arm("Daily loss post-close")

    def kill_switch(self, reason="Manual"): self._arm(reason)
    def reset_kill(self):
        self._kill = False; self._consec.clear(); self._save()
        logger.warning("[Risk] Kill switch RESET")

    def _arm(self, reason):
        if not self._kill:
            self._kill = True; self._save()
            logger.critical("⬛ KILL SWITCH: %s", reason)

    @property
    def daily_pnl(self):  return self._pnl
    @property
    def open_count(self): return self._open
    @property
    def is_killed(self):  return self._kill

    def status(self):
        cur = config.CAPITAL + self._pnl
        dd  = (self._peak - cur) / self._peak * 100 if self._peak else 0
        return {"daily_pnl": round(self._pnl,2), "open_positions": self._open,
                "max_positions": config.MAX_OPEN_POSITIONS,
                "daily_loss_limit": config.MAX_DAILY_LOSS, "kill_active": self._kill,
                "trades_today": len(self._trades), "capital": config.CAPITAL,
                "current_equity": round(cur,2), "peak_equity": round(self._peak,2),
                "drawdown_pct": round(dd,2),
                "deployed_pct": round(self._open * config.MAX_CAPITAL_PER_TRADE / config.CAPITAL * 100, 1),
                "strategy_pnl": {k: round(v,2) for k,v in self._spnl.items()},
                "consec_losses": dict(self._consec)}

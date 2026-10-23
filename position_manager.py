"""Position Manager — trailing stops, exit detection — AlgoEdge"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from logzero import logger
import config
from broker.angel_one import AngelOneBroker, BrokerOrderError

POSITIONS_FILE = config.DATA_DIR / "positions.json"

@dataclass
class Position:
    symbol:str; token:str; exchange:str; side:str; qty:int
    entry_price:float; sl_price:float; target_price:float
    product:str; strategy:str; entry_time:str=""; trailing:bool=True
    atr:float=0.0; order_id:str=""; status:str="OPEN"
    def to_dict(self): return asdict(self)
    @classmethod
    def from_dict(cls, d):
        return cls(**{k:v for k,v in d.items() if k in cls.__dataclass_fields__})

class PositionManager:
    def __init__(self, broker: AngelOneBroker):
        self.broker = broker; self.positions = []; self._load()

    def _load(self):
        if POSITIONS_FILE.exists():
            try:
                raw = json.loads(POSITIONS_FILE.read_text())
                self.positions = [Position.from_dict(p) for p in raw if p.get("status")=="OPEN"]
                if self.positions: logger.info("PM: %d open position(s) loaded.", len(self.positions))
            except Exception as exc: logger.warning("Position load: %s", exc)

    def _save(self):
        try: POSITIONS_FILE.write_text(json.dumps([p.to_dict() for p in self.positions], indent=2))
        except Exception as exc: logger.warning("Position save: %s", exc)

    def open_position(self, pos: Position):
        pos.entry_time = datetime.now().isoformat(); pos.status = "OPEN"
        self.positions.append(pos); self._save()
        logger.info("[PM] Opened %s %s×%d @%.2f SL=%.2f T=%.2f",
                    pos.side, pos.symbol, pos.qty, pos.entry_price, pos.sl_price, pos.target_price)

    def close_position(self, symbol: str, reason: str = "") -> float:
        for pos in self.positions:
            if pos.symbol == symbol and pos.status == "OPEN":
                try:
                    ltp = self.broker.get_ltp(pos.exchange, pos.symbol, pos.token)
                    self.broker.place_order(symbol=pos.symbol, token=pos.token,
                        exchange=pos.exchange, side="SELL" if pos.side=="BUY" else "BUY",
                        qty=pos.qty, order_type="MARKET", product=pos.product)
                    pnl = ((ltp - pos.entry_price) if pos.side=="BUY" else (pos.entry_price - ltp)) * pos.qty
                    pos.status = reason or "CLOSED"; self._save()
                    logger.info("[PM] Closed %s P&L=₹%.2f reason=%s", symbol, pnl, reason)
                    return pnl
                except BrokerOrderError as exc:
                    logger.error("[PM] Exit failed %s: %s", symbol, exc)
                    pos.status = "CLOSE_FAILED"; self._save(); return 0.0
        return 0.0

    def check_exits(self, risk_manager) -> list:
        events = []; still_open = []
        for pos in self.positions:
            if pos.status != "OPEN": continue
            try: ltp = self.broker.get_ltp(pos.exchange, pos.symbol, pos.token)
            except Exception: still_open.append(pos); continue
            if pos.side == "BUY":
                if pos.trailing and pos.atr > 0:
                    ns = round(ltp - pos.atr * 1.5, 2)
                    if ns > pos.sl_price: pos.sl_price = ns
                hit_sl = ltp <= pos.sl_price; hit_tgt = ltp >= pos.target_price
            else:
                if pos.trailing and pos.atr > 0:
                    ns = round(ltp + pos.atr * 1.5, 2)
                    if ns < pos.sl_price: pos.sl_price = ns
                hit_sl = ltp >= pos.sl_price; hit_tgt = ltp <= pos.target_price
            if hit_sl or hit_tgt:
                reason = "TARGET_HIT" if hit_tgt else "SL_HIT"
                pnl = self.close_position(pos.symbol, reason)
                risk_manager.on_position_closed(pos.symbol, pnl, pos.strategy)
                events.append({"symbol":pos.symbol,"strategy":pos.strategy,"reason":reason,"pnl":pnl,"ltp":ltp})
            else: still_open.append(pos)
        self.positions = still_open; self._save()
        return events

    def open_positions(self): return [p for p in self.positions if p.status=="OPEN"]
    def count(self):          return len(self.open_positions())

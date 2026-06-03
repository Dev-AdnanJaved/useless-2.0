"""
Paper / Live position manager — rebuilt using proven pattern from working bot.

Uses two simple JSON files (no complex in-memory state):
  data/paper_trades.json   — list of all trades (open + closed)
  data/paper_account.json  — running balance and stats

Config block (config.json → "strategy"):
  enabled                — master switch
  paper_mode             — true = paper only, false = live
  starting_balance       — paper starting balance in USDT
  leverage               — leverage (e.g. 5)
  margin_pct_per_trade   — fraction of balance per trade (e.g. 0.02 = 2%)
  max_open_trades        — max concurrent open positions
  initial_sl_pct         — stop-loss % from entry (e.g. -20)
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class PaperTrader:

    def __init__(self, config: dict, notifier, binance=None) -> None:
        sc = config.get("strategy", {})

        self.enabled        = sc.get("enabled", False)
        self.paper_mode     = sc.get("paper_mode", True)
        self.leverage       = int(sc.get("leverage", 5))
        self.margin_pct     = float(sc.get("margin_pct_per_trade", 0.02))
        self.max_open       = int(sc.get("max_open_trades", 40))
        self.initial_sl_pct = float(sc.get("initial_sl_pct", -20.0))
        self._starting_bal  = float(sc.get("starting_balance", 100.0))
        self._fee_rate      = float(sc.get("fee_rate", 0.0004))
        self._slip_rate     = float(sc.get("slippage_rate", 0.001))

        self._notifier = notifier
        self._binance  = binance
        self._lock     = threading.Lock()

        data_dir = Path(config.get("tracker", {}).get("data_dir", "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        self._trades_file  = data_dir / "paper_trades.json"
        self._account_file = data_dir / "paper_account.json"

        mode = "PAPER" if self.paper_mode else "LIVE"
        logger.info(
            "PaperTrader [%s] balance=$%.2f lev=%dx margin=%.1f%% max=%d sl=%.0f%%",
            mode, self._starting_bal, self.leverage,
            self.margin_pct * 100, self.max_open, self.initial_sl_pct,
        )

    # ── file I/O ──────────────────────────────────────────────────────

    def _load_trades(self) -> list:
        if not self._trades_file.exists():
            return []
        try:
            with open(self._trades_file, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_trades(self, trades: list) -> None:
        tmp = self._trades_file.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(trades, f, indent=2)
        tmp.replace(self._trades_file)

    def _load_account(self) -> dict:
        if not self._account_file.exists():
            return {
                "starting_balance":   self._starting_bal,
                "current_balance":    self._starting_bal,
                "total_realized_pnl": 0.0,
                "trades_opened":      0,
                "trades_closed":      0,
                "wins": 0, "losses": 0, "breakevens": 0, "liquidations": 0,
            }
        try:
            with open(self._account_file, "r") as f:
                d = json.load(f)
            d.setdefault("starting_balance",   self._starting_bal)
            d.setdefault("current_balance",    self._starting_bal)
            d.setdefault("total_realized_pnl", 0.0)
            d.setdefault("trades_opened",      0)
            d.setdefault("trades_closed",      0)
            d.setdefault("wins",          0)
            d.setdefault("losses",        0)
            d.setdefault("breakevens",    0)
            d.setdefault("liquidations",  0)
            return d
        except Exception:
            return {
                "starting_balance":   self._starting_bal,
                "current_balance":    self._starting_bal,
                "total_realized_pnl": 0.0,
                "trades_opened": 0, "trades_closed": 0,
                "wins": 0, "losses": 0, "breakevens": 0, "liquidations": 0,
            }

    def _save_account(self, acc: dict) -> None:
        acc["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        tmp = self._account_file.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(acc, f, indent=2)
        tmp.replace(self._account_file)

    # ── helpers ───────────────────────────────────────────────────────

    def _open_count(self, trades: list) -> int:
        return sum(1 for t in trades if t.get("status") == "open")

    def _already_open(self, symbol: str, trades: list) -> bool:
        return any(t.get("symbol") == symbol and t.get("status") == "open"
                   for t in trades)

    # ── open position ─────────────────────────────────────────────────

    def open_position(self, alert: dict, btc_3d: float, btc_7d: float) -> bool:
        if not self.enabled:
            return False

        symbol      = alert["symbol"]
        entry_price = float(alert.get("entry_price") or alert.get("price", 0))

        if entry_price <= 0:
            logger.warning("PaperTrader: %s — entry price missing", symbol)
            return False

        with self._lock:
            trades = self._load_trades()

            if self._already_open(symbol, trades):
                logger.info("PaperTrader: %s already open — skip", symbol)
                return False

            open_n = self._open_count(trades)
            if open_n >= self.max_open:
                logger.info("PaperTrader: max open %d reached — skip %s", self.max_open, symbol)
                self._notifier.send(
                    f"⚠️ <b>SKIPPED — {symbol}</b>\n"
                    f"Max open trades reached ({open_n}/{self.max_open})"
                )
                return False

            acc    = self._load_account()
            bal    = acc["current_balance"]
            margin = round(bal * self.margin_pct, 4)

            if margin <= 0:
                logger.warning("PaperTrader: margin is 0 for %s", symbol)
                return False

            if margin > bal:
                self._notifier.send(
                    f"⚠️ <b>SKIPPED — {symbol}</b>\n"
                    f"Insufficient balance.\n"
                    f"Need: ${margin:.2f}  Have: ${bal:.2f}"
                )
                return False

            sl_price = round(entry_price * (1 + self.initial_sl_pct / 100.0), 8)
            now      = datetime.now(timezone.utc)

            trade = {
                "trade_id":    f"paper_{symbol}_{int(now.timestamp())}",
                "symbol":      symbol,
                "entry_price": entry_price,
                "sl_price":    sl_price,
                "sl_pct":      self.initial_sl_pct,
                "current_sl_price": sl_price,
                "current_sl_pct":   self.initial_sl_pct,
                "margin_used": margin,
                "leverage":    self.leverage,
                "opened_at":   now.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "opened_ts":   now.timestamp(),
                "status":      "open",
                "highest_tp":  0,
                "tp_history":  [],
                "close_reason": None,
                "close_price":  None,
                "closed_at":    None,
                "pnl_pct":      None,
                "pnl_usdt":     None,
                "btc_3d":       btc_3d,
                "btc_7d":       btc_7d,
                "filter_reason": alert.get("strategy_filter_reason", ""),
                "skip_score":    alert.get("strategy_skip_score", 0),
            }

            trades.append(trade)
            self._save_trades(trades)

            acc["current_balance"] = round(bal - margin, 4)
            acc["trades_opened"]   = acc.get("trades_opened", 0) + 1
            self._save_account(acc)

            logger.info(
                "PaperTrader: 📝 OPENED %s  entry=$%.6g  sl=$%.6g  margin=$%.2f  [%d/%d]",
                symbol, entry_price, sl_price, margin, open_n + 1, self.max_open,
            )
            self._notifier.send_paper_trade_opened(trade, acc["current_balance"], open_n + 1, self.max_open)
            return True

    # ── TP hit ────────────────────────────────────────────────────────

    def on_tp_hit(self, symbol: str, tp_level: int, score: int,
                  score_parts: list, action: str, new_sl: Optional[float],
                  snapshot: dict, current_price: float) -> None:
        if not self.enabled:
            return

        with self._lock:
            trades = self._load_trades()
            trade  = next((t for t in trades if t["symbol"] == symbol
                           and t["status"] == "open"), None)
            if trade is None:
                return

            trade["tp_history"].append({
                "tp": tp_level, "score": score, "action": action, "new_sl": new_sl,
            })
            if tp_level > trade.get("highest_tp", 0):
                trade["highest_tp"] = tp_level

            if action == "EXIT" or tp_level >= 100:
                self._close_trade(trade, trades, current_price, f"exit_tp{tp_level}")
                self._save_trades(trades)
                self._notifier.send_paper_tp_exit(trade, tp_level, score, score_parts, self._load_account()["current_balance"])
            else:
                trade["current_sl_pct"]   = new_sl
                trade["current_sl_price"] = round(trade["entry_price"] * (1 + new_sl / 100.0), 8)
                self._save_trades(trades)
                self._notifier.send_paper_tp_hold(trade, tp_level, score, score_parts, new_sl, self._load_account()["current_balance"])

    # ── SL monitoring ─────────────────────────────────────────────────

    def check_sl_hits(self, prices: dict) -> None:
        if not self.enabled:
            return

        with self._lock:
            trades  = self._load_trades()
            changed = False
            for trade in trades:
                if trade.get("status") != "open":
                    continue
                symbol = trade["symbol"]
                price  = prices.get(symbol)
                if price is None:
                    continue
                sl_price = trade.get("current_sl_price") or trade.get("sl_price", 0)
                if price <= sl_price:
                    self._close_trade(trade, trades, sl_price, "sl_hit")
                    changed = True
                    acc = self._load_account()
                    self._notifier.send_paper_sl_hit(trade, acc["current_balance"])

            if changed:
                self._save_trades(trades)

    def _close_trade(self, trade: dict, trades: list, close_price: float, reason: str) -> None:
        entry  = trade["entry_price"]
        margin = trade["margin_used"]
        lev    = trade["leverage"]

        price_pct  = ((close_price - entry) / entry) * 100
        fee_drag   = (self._fee_rate + self._slip_rate) * lev * 2 * 100
        margin_ret = max(price_pct * lev - fee_drag, -100.0)
        pnl_usdt   = round(margin * margin_ret / 100.0, 4)

        now = datetime.now(timezone.utc)
        trade["status"]       = "closed"
        trade["close_reason"] = reason
        trade["close_price"]  = close_price
        trade["closed_at"]    = now.strftime("%Y-%m-%d %H:%M:%S UTC")
        trade["pnl_pct"]      = round(margin_ret, 2)
        trade["pnl_usdt"]     = pnl_usdt

        acc = self._load_account()
        acc["current_balance"]    = round(acc["current_balance"] + margin + pnl_usdt, 4)
        acc["total_realized_pnl"] = round(acc.get("total_realized_pnl", 0) + pnl_usdt, 4)
        acc["trades_closed"]      = acc.get("trades_closed", 0) + 1

        if pnl_usdt > 0.01:
            acc["wins"] = acc.get("wins", 0) + 1
        elif pnl_usdt < -0.01:
            if margin_ret <= -95:
                acc["liquidations"] = acc.get("liquidations", 0) + 1
            else:
                acc["losses"] = acc.get("losses", 0) + 1
        else:
            acc["breakevens"] = acc.get("breakevens", 0) + 1

        self._save_account(acc)
        logger.info("PaperTrader: CLOSED %s  reason=%s  pnl=$%.4f", trade["symbol"], reason, pnl_usdt)

    # ── 7-day expiry ──────────────────────────────────────────────────

    def force_close_expired(self, symbol: str, exit_price: float) -> None:
        with self._lock:
            trades = self._load_trades()
            trade  = next((t for t in trades if t["symbol"] == symbol
                           and t["status"] == "open"), None)
            if trade is None:
                return
            self._close_trade(trade, trades, exit_price, "7day_timeout")
            self._save_trades(trades)
            acc = self._load_account()
            self._notifier.send_paper_timeout_close(trade, acc["current_balance"])

    # ── position status for BTC dump ─────────────────────────────────

    def get_positions_during_dump(self, prices: dict) -> str:
        trades = [t for t in self._load_trades() if t.get("status") == "open"]
        if not trades:
            return ""
        lines = ["<b>📊 OPEN POSITIONS (running independently of BTC)</b>", ""]
        for t in trades:
            sym   = t["symbol"]
            price = prices.get(sym)
            entry = t["entry_price"]
            sl    = t.get("current_sl_pct", t.get("sl_pct", -20))
            best  = t.get("highest_tp", 0)
            if price and entry:
                pct = ((price - entry) / entry) * 100
                icon = "🟢" if pct > 0 else ("🟡" if pct > sl else "🔴")
                lines.append(f"{icon} <b>{sym}</b>  {pct:+.1f}%  (SL {sl:+.0f}%  best +{best}%)")
            else:
                lines.append(f"⚠️ <b>{sym}</b>  price unavailable  (SL {sl:+.0f}%  best +{best}%)")
        return "\n".join(lines)

    # ── /balance and /current data ────────────────────────────────────

    def get_stats_summary(self) -> str:
        acc    = self._load_account()
        trades = self._load_trades()
        open_t = [t for t in trades if t.get("status") == "open"]
        bal    = acc["current_balance"]
        start  = acc["starting_balance"]
        locked = sum(t["margin_used"] for t in open_t)
        equity = bal + locked
        total  = acc.get("trades_closed", 0)
        wins   = acc.get("wins", 0)
        wr     = wins / total * 100 if total > 0 else 0
        pnl    = acc.get("total_realized_pnl", 0)
        mode   = "📋 PAPER" if self.paper_mode else "🔴 LIVE"

        lines = [
            f"<b>{mode} TRADING — ACCOUNT STATUS</b>",
            "━" * 28,
            f"💰 Balance:    ${bal:.2f} (free)",
            f"📊 Equity:     ${equity:.2f} (incl. open margin)",
            f"📈 Total P&L:  {'+' if pnl >= 0 else ''}${pnl:.2f}",
            f"🏔 Start:      ${start:.2f}",
            "",
            f"<b>TRADE STATS ({total} closed trades)</b>",
            f"✅ Wins:       {wins} ({wr:.1f}%)",
            f"🛑 Losses:     {acc.get('losses', 0)}",
            f"⚖️  Breakevens: {acc.get('breakevens', 0)}",
            f"💥 Liquidated: {acc.get('liquidations', 0)}",
            "",
            f"<b>OPEN POSITIONS: {len(open_t)}/{self.max_open}</b>",
        ]
        for t in open_t:
            sl  = t.get("current_sl_pct", t.get("sl_pct", -20))
            best = t.get("highest_tp", 0)
            lines.append(f"  • {t['symbol']}  SL {sl:+.0f}%  best +{best}%  margin ${t['margin_used']:.2f}")
        return "\n".join(lines)

    def get_current_positions(self, prices: dict) -> str:
        trades = [t for t in self._load_trades() if t.get("status") == "open"]
        if not trades:
            acc = self._load_account()
            return (
                f"📭 <b>NO OPEN POSITIONS</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"💰 Free balance: ${acc['current_balance']:.2f}"
            )

        lines = [f"📊 <b>OPEN POSITIONS — {len(trades)}</b>", "━" * 28, ""]
        total_margin = 0.0
        total_upnl   = 0.0

        for t in trades:
            sym    = t["symbol"]
            price  = prices.get(sym)
            entry  = t["entry_price"]
            margin = t["margin_used"]
            lev    = t["leverage"]
            sl_pct = t.get("current_sl_pct", t.get("sl_pct", -20))
            best   = t.get("highest_tp", 0)
            total_margin += margin

            if price and entry:
                price_pct  = ((price - entry) / entry) * 100
                fee_drag   = (self._fee_rate + self._slip_rate) * lev * 2 * 100
                margin_ret = price_pct * lev - fee_drag
                upnl       = margin * margin_ret / 100
                total_upnl += upnl
                icon = "🟢" if price_pct > 0 else ("🟡" if price_pct > sl_pct else "🔴")
                lines += [
                    f"<b>{sym}</b>",
                    f"  {icon} Price:  ${price:.6g}  ({price_pct:+.2f}%)",
                    f"  💵 Entry:  ${entry:.6g}",
                    f"  📦 Margin: ${margin:.2f} × {lev}x",
                    f"  📈 uPnL:   {'+' if upnl >= 0 else ''}${upnl:.3f}  ({margin_ret:+.1f}%)",
                    f"  🛑 SL:     {sl_pct:+.0f}%  |  Best TP: +{best}%",
                    "",
                ]
            else:
                lines += [
                    f"<b>{sym}</b>",
                    f"  ⚠️ Price unavailable",
                    f"  💵 Entry:  ${entry:.6g}",
                    f"  📦 Margin: ${margin:.2f} × {lev}x",
                    f"  🛑 SL:     {sl_pct:+.0f}%  |  Best TP: +{best}%",
                    "",
                ]

        acc = self._load_account()
        lines += [
            "━" * 28,
            f"📦 Total margin: ${total_margin:.2f}",
            f"📈 Total uPnL:   {'+' if total_upnl >= 0 else ''}${total_upnl:.2f}",
            f"💰 Free balance: ${acc['current_balance']:.2f}",
            f"📊 Equity:       ${acc['current_balance'] + total_margin:.2f}",
        ]
        return "\n".join(lines)

    # ── properties ────────────────────────────────────────────────────

    @property
    def balance(self) -> float:
        return self._load_account()["current_balance"]

    @property
    def equity(self) -> float:
        acc    = self._load_account()
        trades = self._load_trades()
        locked = sum(t["margin_used"] for t in trades if t.get("status") == "open")
        return acc["current_balance"] + locked

    @property
    def open_count(self) -> int:
        return self._open_count(self._load_trades())

    def get_open_positions(self) -> list:
        return [t for t in self._load_trades() if t.get("status") == "open"]

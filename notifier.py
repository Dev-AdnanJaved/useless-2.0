"""
Telegram Bot API helper.

Sends:
  - Breakout alerts (signal entry)
  - Take-profit target hit alerts
  - Reversal warning alerts
  - Startup summary
"""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)


class TelegramNotifier:
    API = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, bot_token: str, chat_id: str):
        self._token = bot_token
        self._chat_id = chat_id
        self._session = requests.Session()
        self._ok = False

    def _url(self, method: str) -> str:
        return self.API.format(token=self._token, method=method)

    def validate(self) -> bool:
        try:
            r = self._session.get(self._url("getMe"), timeout=10).json()
            if r.get("ok"):
                logger.info("Telegram bot validated: @%s", r["result"].get("username"))
                self._ok = True
                return True
            logger.error("Telegram validation failed: %s", r)
        except Exception as exc:
            logger.error("Telegram validation error: %s", exc)
        return False

    def send(self, text: str, parse_mode: str = "HTML") -> bool:
        for attempt in range(3):
            try:
                r = self._session.post(
                    self._url("sendMessage"),
                    json={
                        "chat_id": self._chat_id,
                        "text": text,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    },
                    timeout=15,
                ).json()
                if r.get("ok"):
                    return True
                if r.get("error_code") == 429:
                    wait = r.get("parameters", {}).get("retry_after", 30)
                    logger.warning("Telegram 429 — waiting %ds", wait)
                    time.sleep(wait)
                    continue
                logger.error("Telegram error: %s", r)
                return False
            except Exception as exc:
                logger.error("Telegram send failed (attempt %d): %s", attempt + 1, exc)
                time.sleep(2)
        return False

    def send_document(self, file_path: str, caption: str = "") -> bool:
        """Send a file as a Telegram document."""
        for attempt in range(3):
            try:
                with open(file_path, "rb") as f:
                    r = self._session.post(
                        self._url("sendDocument"),
                        data={"chat_id": self._chat_id, "caption": caption},
                        files={"document": f},
                        timeout=30,
                    ).json()
                if r.get("ok"):
                    return True
                if r.get("error_code") == 429:
                    wait = r.get("parameters", {}).get("retry_after", 30)
                    time.sleep(wait)
                    continue
                logger.error("Telegram send_document error: %s", r)
                return False
            except Exception as exc:
                logger.error("Telegram send_document failed (attempt %d): %s", attempt + 1, exc)
                time.sleep(2)
        return False

    # ── alert types ──────────────────────────────────────────────────

    def send_alert(self, data: dict) -> bool:
        return self.send(self._fmt_alert(data))

    def send_startup(self, summary: str) -> bool:
        return self.send(
            f"🤖 <b>Volume Scanner Started</b>\n\n{summary}\n\nScanner is now running …"
        )

    def send_take_profit(self, data: dict) -> bool:
        return self.send(self._fmt_take_profit(data))

    def send_reversal_warning(self, data: dict) -> bool:
        return self.send(self._fmt_reversal(data))

    # ── strategy alert types ──────────────────────────────────────────

    @staticmethod
    def _he(text: str) -> str:
        """Escape HTML special characters for Telegram HTML parse mode."""
        return (str(text)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))

    def send_paper_trade_opened(self, trade: dict, balance: float, open_count: int, max_open: int) -> bool:
        """Sent after a paper position is successfully opened."""
        sym    = trade["symbol"]
        lev    = trade.get("leverage", 5)
        price  = trade.get("entry_price", 0)
        sl     = trade.get("sl_price", 0)
        sl_pct = abs(trade.get("sl_pct", 20))
        margin = trade.get("margin_used", 0)
        b3     = trade.get("btc_3d")
        b7     = trade.get("btc_7d")
        b3s    = f"{b3:+.2f}%" if b3 is not None else "N/A"
        b7s    = f"{b7:+.2f}%" if b7 is not None else "N/A"
        skip   = trade.get("skip_score", 0)
        text = (
            f"\u2705 <b>PAPER TRADE OPENED</b>\n"
            f"{'\u2501' * 28}\n\n"
            f"\U0001f4cc <b>{sym}</b>  \u00b7  {lev}x LONG\n"
            f"\U0001f4b5 Entry:          {self._fp(price)}\n"
            f"\U0001f6d1 SL set at:      {self._fp(sl)}  (-{sl_pct:.1f}%)\n"
            f"\U0001f4e6 Margin:         ${margin:.2f}\n\n"
            f"\u20bf BTC 3d: {b3s}  \u00b7  BTC 7d: {b7s}\n"
            f"\U0001f9fe Skip score: {skip}/6\n\n"
            f"\U0001f4ca Position {open_count}/{max_open}\n"
            f"\U0001f4b0 Paper balance:  ${balance:.2f}\n"
            f"\U0001f550 {trade.get('opened_at', '')}"
        )
        return self.send(text)

    def send_paper_tp_hold(self, trade: dict, tp_level: int, score: int,
                           score_parts: list, new_sl: float, balance: float) -> bool:
        """Sent when a TP hits and strategy says HOLD."""
        sym       = trade["symbol"]
        entry     = trade["entry_price"]
        sl_price  = round(entry * (1 + new_sl / 100.0), 8)
        score_txt = "\n".join(f"  {self._he(p)}" for p in score_parts)
        icons     = {5: "\U0001f3af", 10: "\U0001f680", 20: "\U0001f680\U0001f680",
                     30: "\U0001f680\U0001f680\U0001f680"}
        icon      = icons.get(tp_level, "\U0001f4aa")
        text = (
            f"{icon} <b>TP{tp_level}% HIT \u2014 HOLDING \u2014 {sym}</b>\n"
            f"{'\u2501' * 28}\n\n"
            f"<b>Score: {score}/3</b>\n"
            f"{score_txt}\n\n"
            f"\U0001f512 <b>ACTION: HOLD</b>\n"
            f"   SL moved to: {new_sl:+.0f}% (${self._fp(sl_price)})\n\n"
            f"\U0001f4b0 Balance: ${balance:.2f}"
        )
        return self.send(text)

    def send_paper_tp_exit(self, trade: dict, tp_level: int, score: int,
                           score_parts: list, balance: float) -> bool:
        """Sent when a TP hits and strategy says EXIT."""
        sym       = trade["symbol"]
        margin    = trade["margin_used"]
        pnl_usdt  = trade.get("pnl_usdt", 0) or 0
        pnl_pct   = trade.get("pnl_pct", 0) or 0
        score_txt = "\n".join(f"  {self._he(p)}" for p in score_parts)
        best_tp   = trade.get("highest_tp", tp_level)
        text = (
            f"\u2705 <b>CLOSED at TP{tp_level}% \u2014 {sym}</b>\n"
            f"{'\u2501' * 28}\n\n"
            f"<b>Score: {score}/3 \u2192 EXIT</b>\n"
            f"{score_txt}\n\n"
            f"\U0001f4b5 Margin:   ${margin:.2f}\n"
            f"\U0001f4c8 Return:   {pnl_pct:+.1f}% on margin\n"
            f"\U0001f4b0 P&L:      {'+' if pnl_usdt >= 0 else ''}${pnl_usdt:.2f}\n"
            f"\U0001f3c6 Best TP:  +{best_tp}%\n\n"
            f"\U0001f4b0 Balance: ${balance:.2f}"
        )
        return self.send(text)

    def send_paper_sl_hit(self, trade: dict, balance: float) -> bool:
        """Sent when a trailed SL is hit."""
        sym     = trade["symbol"]
        entry   = trade.get("entry_price", 0)
        sl_p    = trade.get("close_price", trade.get("current_sl_price", 0))
        sl_pct  = trade.get("current_sl_pct", trade.get("sl_pct", -20))
        pnl_pct = trade.get("pnl_pct", 0) or 0
        pnl_usd = trade.get("pnl_usdt", 0) or 0
        best    = trade.get("highest_tp", 0)
        icon    = "\U0001f6e1\ufe0f" if sl_pct >= 0 else "\U0001f534"
        text = (
            f"{icon} <b>SL HIT \u2014 {sym}</b>\n"
            f"{'\u2501' * 28}\n\n"
            f"\U0001f4b5 Entry:    {self._fp(entry)}\n"
            f"\U0001f6d1 SL hit:   {self._fp(sl_p)}  ({sl_pct:+.0f}%)\n"
            f"\U0001f4c8 P&L:      {pnl_pct:+.1f}%  (${pnl_usd:+.2f})\n"
            f"\U0001f3c6 Best TP:  +{best}%\n\n"
            f"\U0001f4b0 Balance: ${balance:.2f}"
        )
        return self.send(text)

    def send_paper_timeout_close(self, trade: dict, balance: float) -> bool:
        """Sent when a position closes due to 7-day expiry."""
        sym     = trade["symbol"]
        pnl_pct = trade.get("pnl_pct", 0) or 0
        pnl_usd = trade.get("pnl_usdt", 0) or 0
        best    = trade.get("highest_tp", 0)
        text = (
            f"\u23f0 <b>7-DAY TIMEOUT \u2014 {sym}</b>\n"
            f"{'\u2501' * 28}\n\n"
            f"\U0001f4c8 P&L:      {pnl_pct:+.1f}%  (${pnl_usd:+.2f})\n"
            f"\U0001f3c6 Best TP:  +{best}%\n\n"
            f"\U0001f4b0 Balance: ${balance:.2f}"
        )
        return self.send(text)

    def send_no_signals_status(self, reason: str, btc_3d, btc_7d,
                                btc_detail: dict = None, positions_status: str = "") -> bool:
        b3s  = f"{btc_3d:+.2f}%" if btc_3d is not None else "N/A"
        b7s  = f"{btc_7d:+.2f}%" if btc_7d is not None else "N/A"
        b4h  = btc_detail.get("btc_chg_4h", 0) if btc_detail else 0
        b24  = btc_detail.get("btc_chg_24h", 0) if btc_detail else 0
        text = (
            f"\U0001f4f5 <b>NO NEW ENTRIES \u2014 FILTER BLOCKING</b>\n"
            f"{'\u2501' * 28}\n\n"
            f"<b>Reason:</b> {reason}\n\n"
            f"\u20bf BTC 4h:  {b4h:+.2f}%\n"
            f"\u20bf BTC 24h: {b24:+.2f}%\n"
            f"\u20bf BTC 3d:  {b3s}\n"
            f"\u20bf BTC 7d:  {b7s}\n\n"
            f"<i>New entries blocked. Open positions running normally.</i>"
        )
        if positions_status:
            text += f"\n\n{positions_status}"
        return self.send(text)

    # ── price formatting ─────────────────────────────────────────────
    # ── price formatting ─────────────────────────────────────────────

    @staticmethod
    def _fp(price: float) -> str:
        if price <= 0:
            return "N/A"
        if price >= 1000:
            return f"${price:,.2f}"
        if price >= 1:
            return f"${price:.4f}"
        if price >= 0.001:
            return f"${price:.6f}"
        return f"${price:.8f}"

    # ── signal alert format ──────────────────────────────────────────

    @staticmethod
    def _fmt_alert(d: dict) -> str:
        symbol = d["symbol"]
        tf = d.get("timeframe", "1h")
        price = d.get("price", "N/A")
        brk_margin = d.get("breakout_margin_pct", 0)
        price_chg = d.get("price_change_24h", 0)
        v1 = d.get("vol_candle_1_fmt", "?")
        v2 = d.get("vol_candle_2_fmt", "?")
        v3 = d.get("vol_candle_3_fmt", "?")
        bv1 = d.get("vol_candle_1_base_fmt", "?")
        bv2 = d.get("vol_candle_2_base_fmt", "?")
        bv3 = d.get("vol_candle_3_base_fmt", "?")
        rvol = d.get("rvol", 0)
        alert_time = d.get("alert_time", "N/A")
        cooldown = d.get("cooldown_hours", 12)

        chg_icon = "🟢" if price_chg >= 0 else "🔴"
        high_brk = d.get("high_breakout_warning", False)

        btc_trend = d.get("btc_trend", "unknown")
        btc_detail = d.get("btc_trend_detail", {})
        btc_icons = {"ranging": "🟢", "pumping": "🟡", "dumping": "🔴", "unknown": "❓"}
        btc_labels = {"ranging": "RANGING ✓", "pumping": "PUMPING", "dumping": "DUMPING", "unknown": "UNKNOWN"}
        btc_icon = btc_icons.get(btc_trend, "❓")
        btc_label = btc_labels.get(btc_trend, "UNKNOWN")

        header = "⚠️ <b>BREAKOUT SIGNAL — HIGH BREAKOUT</b>" if high_brk else "🚨 <b>BREAKOUT SIGNAL</b>"

        base_coin = symbol.replace("USDT", "").replace("BUSD", "")

        lines = [
            header,
            f"{'━' * 28}",
            "",
            f"📌 <b>{symbol}</b>  |  {tf}",
            f"💵 <b>Price:</b>  ${price}",
            "",
            f"1️⃣ <b>Breakout:</b>  +{brk_margin:.2f}% above 24h high",
            f"2️⃣ <b>Vol USDT:</b>  {v1} → {v2} → {v3}  ({rvol:.1f}x avg)",
            f"    <b>Vol {base_coin}:</b>  {bv1} → {bv2} → {bv3}",
            f"3️⃣ <b>24h Change:</b>  {chg_icon} {price_chg:+.1f}%",
            "",
        ]

        btc_chg_4h = btc_detail.get("btc_chg_4h")
        btc_chg_24h = btc_detail.get("btc_chg_24h")
        if btc_chg_4h is not None:
            lines.append(f"₿ <b>BTC Trend:</b>  {btc_icon} {btc_label}  (4h: {btc_chg_4h:+.2f}%  24h: {btc_chg_24h:+.2f}%)")
            lines.append("")

        if high_brk:
            lines.append(f"⚠️ <b>Warning:</b> Breakout margin {brk_margin:.2f}% > 5% — enter with caution")
            lines.append("")

        q_score = d.get("quality_score", "?")
        s_flags = d.get("soft_flags", 0)
        sf_details = d.get("soft_flag_details", [])
        q_details = d.get("quality_details", [])

        if q_score >= 7:
            grade = "🟢 EXCELLENT"
        elif q_score >= 5:
            grade = "🟢 STRONG"
        elif q_score >= 4:
            grade = "🟡 GOOD"
        elif q_score >= 2:
            grade = "🟠 FAIR"
        else:
            grade = "🔴 WEAK"

        lines.append(f"⭐ <b>Quality:</b>  {q_score}/8  {grade}")
        if s_flags > 0:
            lines.append(f"🚩 <b>Warnings:</b>  {s_flags}/8  ({', '.join(sf_details)})")
        else:
            lines.append(f"🚩 <b>Warnings:</b>  0/8")
        lines.append("")

        lines.extend([
            f"🕐 <b>Time:</b>  {alert_time}",
            f"⏱ <b>Cooldown:</b>  {cooldown}h",
        ])

        # ── STRATEGY DECISION — always shown at bottom of signal ──────
        should_trade = d.get("strategy_should_trade")
        if should_trade is True:
            b3   = d.get("strategy_btc_3d")
            b7   = d.get("strategy_btc_7d")
            skip = d.get("strategy_skip_score", 0)
            b3s  = f"{b3:+.2f}%" if b3 is not None else "N/A"
            b7s  = f"{b7:+.2f}%" if b7 is not None else "N/A"
            lines += [
                "",
                "━" * 28,
                "🟢 <b>STRATEGY: FILTER PASSED — opening position…</b>",
                f"   BTC 3d: {b3s} ✅   BTC 7d: {b7s} ✅",
                f"   Skip score: {skip}/6 ✅",
            ]
        elif should_trade is False:
            reason = d.get("strategy_filter_reason", "")
            lines += [
                "",
                "━" * 28,
                "⛔ <b>STRATEGY: NOT TRADED</b>",
            ]
            for line in reason.split("\n"):
                if line.strip():
                    lines.append(f"   {TelegramNotifier._he(line.strip())}")
        elif should_trade is None:
            pass  # strategy disabled — show nothing

        return "\n".join(lines)

    # ── take-profit alert format ─────────────────────────────────────

    def _fmt_take_profit(self, d: dict) -> str:
        target = d["target"]
        if target >= 75:
            icon = "💎🚀🚀"
        elif target >= 50:
            icon = "🚀🚀🚀"
        elif target >= 30:
            icon = "🚀🚀"
        elif target >= 10:
            icon = "🚀"
        elif target >= 5:
            icon = "🎯"
        else:
            icon = "✅"

        cur_pct = d.get("cur_pct", 0)
        high_pct = d.get("high_pct", 0)
        age = d.get("age_str", "")

        return (
            f"{icon} <b>TARGET HIT  +{target}%</b>\n"
            f"{'━' * 28}\n\n"
            f"📌 <b>{d['symbol']}</b>\n"
            f"💵 Entry:    {self._fp(d['entry_price'])}\n"
            f"🏔  Peak:     {self._fp(d['highest_price'])}  (+{high_pct:.2f}%)\n"
            f"💵 Now:      {self._fp(d['current_price'])}  ({cur_pct:+.2f}%)\n"
            f"⏱  Age:      {age}\n\n"
            f"{'🟢 Still above target' if cur_pct >= target else '⚠️ Price pulled back from target'}"
        )

    # ── reversal warning format ──────────────────────────────────────

    def _fmt_reversal(self, d: dict) -> str:
        return (
            f"⚠️ <b>REVERSAL WARNING</b>\n"
            f"{'━' * 28}\n\n"
            f"📌 <b>{d['symbol']}</b>\n"
            f"💵 Entry:    {self._fp(d['entry_price'])}\n"
            f"🏔  Peak:     {self._fp(d['highest_price'])}  (+{d['high_pct']:.2f}%)\n"
            f"💵 Now:      {self._fp(d['current_price'])}  ({d['cur_pct']:+.2f}%)\n"
            f"📉 Drop:     {d['drop_pct']:.2f}% from peak\n"
            f"⏱  Age:      {d.get('age_str', '')}\n\n"
            f"Price has dropped significantly from its peak.\n"
            f"Consider taking remaining profits."
        )

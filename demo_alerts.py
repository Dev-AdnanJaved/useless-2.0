"""
demo_alerts.py — Test ALL Telegram alerts end-to-end.

Run this BEFORE starting the real bot to verify every alert
type works correctly in your Telegram chat.

Usage:
    python3 demo_alerts.py

What it does:
    1. Loads your real config (Telegram token + chat ID)
    2. Fires every alert type in sequence with realistic fake data
    3. You see exactly what each message looks like in Telegram
    4. Any HTML errors or missing fields show up immediately

If all messages arrive correctly → bot alerts will work fine.
If any message fails → you see the error before going live.
"""

import json
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from notifier import TelegramNotifier

# ── Load real config ──────────────────────────────────────────────────
config = json.load(open("config.json"))
tg = TelegramNotifier(
    bot_token=config["telegram"]["bot_token"],
    chat_id=config["telegram"]["chat_id"],
)

OK   = "✅"
FAIL = "❌"
results = []

def test(name, fn):
    print(f"  Sending: {name}...", end=" ", flush=True)
    try:
        ok = fn()
        status = OK if ok else FAIL
        results.append((name, ok))
        print(status)
    except Exception as e:
        results.append((name, False))
        print(f"{FAIL} ERROR: {e}")
    time.sleep(1.2)  # avoid Telegram rate limit

# ── Fake data ─────────────────────────────────────────────────────────
import time as _time

TRADE = {
    "trade_id":         "paper_DEMOTOKEN_1234567890",
    "symbol":           "DEMOTOKEN USDT",
    "entry_price":      0.04271,
    "sl_price":         0.03417,
    "sl_pct":          -20.0,
    "current_sl_price": 0.04271,   # will be updated per test
    "current_sl_pct":   0.0,
    "margin_used":      2.00,
    "leverage":         5,
    "opened_at":        "2026-06-01 12:00:00 UTC",
    "opened_ts":        _time.time() - 3600,
    "status":           "open",
    "highest_tp":       10,
    "tp_history":       [{"tp":5,"score":3,"action":"HOLD","new_sl":0.0}],
    "close_reason":     None,
    "close_price":      None,
    "closed_at":        None,
    "pnl_pct":          None,
    "pnl_usdt":         None,
    "btc_3d":          -0.75,
    "btc_7d":          -3.73,
    "filter_reason":    "✅ Skip score: 0/6\n🟡 MODE B — V13 Recovery:\n   ✅ BTC 7d: -3.73% &gt; -10%\n   ✅ BTC 4h: +0.34% ≥ 0%\n   ✅ BTC 24h: +0.84% &gt; 0%\n   ✅ trend: ranging",
    "skip_score":       0,
}

TRADE_CLOSED_WIN = {**TRADE,
    "status":      "closed",
    "close_reason":"exit_tp10",
    "close_price": 0.04698,
    "closed_at":   "2026-06-01 18:30:00 UTC",
    "pnl_pct":     48.6,
    "pnl_usdt":    0.972,
    "highest_tp":  10,
}

TRADE_CLOSED_LOSS = {**TRADE,
    "status":      "closed",
    "close_reason":"sl_0pct",
    "close_price": 0.04271,
    "closed_at":   "2026-06-01 20:00:00 UTC",
    "pnl_pct":    -0.8,
    "pnl_usdt":   -0.016,
    "highest_tp":  5,
    "current_sl_pct": 0.0,
    "current_sl_price": 0.04271,
}

TRADE_SL_HIT = {**TRADE,
    "status":      "closed",
    "close_reason":"sl_0pct",
    "close_price": 0.04271,
    "closed_at":   "2026-06-01 22:00:00 UTC",
    "pnl_pct":    -0.8,
    "pnl_usdt":   -0.016,
    "highest_tp":  5,
    "current_sl_pct": 0.0,
    "current_sl_price": 0.04271,
}

SCORE_PARTS_STRONG = [
    "✅ Fast: 5.2h &lt; 12h",
    "✅ Volatile: 3.8% &gt; 2.5%",
    "✅ Small cap: $47M &lt; $100M",
]
SCORE_PARTS_WEAK = [
    "❌ Slow: 28.4h ≥ 24h",
    "❌ Quiet: 1.1% ≤ 2.5%",
    "❌ Large cap: $312M ≥ $100M",
]

ALERT_DICT = {
    "symbol":               "DEMOTOKEN USDT",
    "price":                "0.04271",
    "alert_time_ts":        _time.time(),
    "alert_time":           "2026-06-01 12:00:00 UTC",
    "price_change_24h":     11.7,
    "breakout_margin_pct":  1.84,
    "high_breakout_warning": False,
    "vol_candle_1_fmt":     "$307K",
    "vol_candle_2_fmt":     "$371K",
    "vol_candle_3_fmt":     "$826K",
    "vol_candle_1_base_fmt": "11.74M",
    "vol_candle_2_base_fmt": "14.07M",
    "vol_candle_3_base_fmt": "30.68M",
    "vol_ratio":            4.1,
    "quality_score":        5,
    "soft_flags":           0,
    "btc_trend_at_entry":   "ranging",
    "btc_chg_4h_entry":     0.34,
    "btc_chg_24h_entry":    0.84,
    "add_market_cap_fmt":   "$47.2M",
    "add_oi_change_pct":    8.3,
    "add_funding_rate":     0.012,
    "add_vol_24h_usdt":     9_500_000,
    "add_ema50_distance_pct": 6.2,
    "add_volatility_recent_10_pct": 3.8,
    "strategy_should_trade":  True,
    "strategy_btc_3d":        -0.75,
    "strategy_btc_7d":        -3.73,
    "strategy_skip_score":    0,
    "strategy_filter_reason": (
        "✅ Skip score: 0/6\n"
        "🟡 MODE B — V13 Recovery (BTC stopped dumping):\n"
        "   ✅ BTC 7d floor: -3.73% &gt; -10.0%\n"
        "   ✅ BTC 4h: +0.34% ≥ 0%\n"
        "   ✅ BTC 24h: +0.84% &gt; 0%\n"
        "   ✅ BTC trend: ranging (not dumping)"
    ),
    "timeframe": "1h",
    "cooldown_hours": 72,
}

ALERT_BLOCKED = {**ALERT_DICT,
    "strategy_should_trade":  False,
    "strategy_filter_reason": (
        "✅ Skip score: 0/6\n"
        "❌ MODE A: BTC 3d -3.26% ≤ 0%\n"
        "❌ MODE B: BTC 24h -0.5% ≤ 0%"
    ),
}

# ── Run all tests ─────────────────────────────────────────────────────
print()
print("=" * 60)
print("DEMO ALERT TEST — Volume Scanner V2 Strategy")
print("=" * 60)
print("Sending all alert types to your Telegram chat...")
print("Check Telegram as each message arrives.")
print()

# 1. Intro message
test("0. Intro banner", lambda: tg.send(
    "🧪 <b>DEMO ALERT TEST STARTING</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "This script sends every alert type your bot can produce.\n"
    "Check each message looks correct.\n\n"
    "If all arrive → bot alerts are working ✅\n"
    "If any fail → check the error above ❌\n\n"
    "<i>Starting in 2 seconds…</i>"
))
time.sleep(2)

# 2. Signal alert — FILTER PASSED
test("1. Signal alert (FILTER PASSED — Mode B V13)", lambda: tg.send_alert(ALERT_DICT))

# 3. Paper trade opened
test("2. Paper trade opened", lambda: tg.send_paper_trade_opened(
    TRADE, balance=98.00, open_count=1, max_open=40
))

# 4. Signal alert — BLOCKED
test("3. Signal alert (NOT TRADED — blocked)", lambda: tg.send_alert(ALERT_BLOCKED))

# 5. TP5 hit — HOLD (score 3/3)
test("4. TP5% hit → HOLD (score 3/3, SL → BE)", lambda: tg.send_paper_tp_hold(
    TRADE, tp_level=5, score=3, score_parts=SCORE_PARTS_STRONG,
    new_sl=0.0, balance=98.00
))

# 6. TP10 hit — HOLD (score 2/3)
TRADE_AFTER_TP10 = {**TRADE, "highest_tp": 10, "current_sl_pct": 5.0,
                    "current_sl_price": round(0.04271*1.05,6)}
test("5. TP10% hit → HOLD (score 2/3, SL → +5%)", lambda: tg.send_paper_tp_hold(
    TRADE_AFTER_TP10, tp_level=10, score=2,
    score_parts=["✅ Fast: 18.1h &lt; 24h", "✅ Volatile: 3.1% &gt; 2.5%", "❌ Large cap: $220M ≥ $100M"],
    new_sl=5.0, balance=98.00
))

# 7. TP20 hit — EXIT (score 1/3)
TRADE_TP20_EXIT = {**TRADE_CLOSED_WIN, "highest_tp":20, "pnl_pct":98.2, "pnl_usdt":1.964}
test("6. TP20% hit → EXIT (score 1/3)", lambda: tg.send_paper_tp_exit(
    TRADE_TP20_EXIT, tp_level=20, score=1, score_parts=SCORE_PARTS_WEAK,
    balance=99.96
))

# 8. SL hit — breakeven stop
test("7. SL hit at BE (0%) — coin reversed after TP5", lambda: tg.send_paper_sl_hit(
    TRADE_SL_HIT, balance=98.00
))

# 9. SL hit — trailing stop at +5%
TRADE_SL_PLUS5 = {**TRADE_SL_HIT,
    "current_sl_pct": 5.0,
    "current_sl_price": round(0.04271*1.05, 6),
    "pnl_pct": 23.6,
    "pnl_usdt": 0.472,
    "highest_tp": 10,
}
test("8. SL hit at +5% — locked profit", lambda: tg.send_paper_sl_hit(
    TRADE_SL_PLUS5, balance=100.47
))

# 10. 7-day timeout
TRADE_TIMEOUT = {**TRADE_CLOSED_WIN,
    "close_reason": "7day_timeout",
    "pnl_pct": 12.4,
    "pnl_usdt": 0.248,
    "highest_tp": 5,
}
test("9. 7-day timeout close", lambda: tg.send_paper_timeout_close(
    TRADE_TIMEOUT, balance=100.25
))

# 11. Skipped — max open
test("10. Skipped — max open trades reached", lambda: tg.send(
    "⚠️ <b>SKIPPED — DEMOTOKEN USDT</b>\n"
    "Max open trades reached (40/40)\n"
    "Signal passed filter but no slot available."
))

# 12. Skipped — insufficient balance
test("11. Skipped — insufficient balance", lambda: tg.send(
    "⚠️ <b>SKIPPED — DEMOTOKEN USDT</b>\n"
    "Insufficient balance.\n"
    "Need: $2.00  Have: $0.84"
))

# 13. BTC dump — no new entries
test("12. BTC dump — no new entries", lambda: tg.send_no_signals_status(
    reason="BTC 4h and 24h both negative",
    btc_3d=-8.2, btc_7d=-12.1,
    btc_detail={"btc_chg_4h": -1.2, "btc_chg_24h": -3.4},
    positions_status=(
        "<b>📊 OPEN POSITIONS (running independently of BTC)</b>\n\n"
        "🟢 <b>DEMOTOKEN USDT</b>  +8.3%  (SL 0%  best +5%)\n"
        "🟡 <b>ANOTHERTOKEN USDT</b>  +1.2%  (SL -20%  best +0%)"
    )
))

# 14. /balance output
test("13. /balance command output", lambda: tg.send(
    "<b>📋 PAPER TRADING — ACCOUNT STATUS</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "💰 Balance:    $98.00 (free)\n"
    "📊 Equity:     $102.24 (incl. open margin)\n"
    "📈 Total P&L:  +$2.24\n"
    "🏔 Start:      $100.00\n\n"
    "<b>TRADE STATS (4 closed trades)</b>\n"
    "✅ Wins:       3 (75.0%)\n"
    "🛑 Losses:     1\n"
    "⚖️  Breakevens: 0\n"
    "💥 Liquidated: 0\n\n"
    "<b>OPEN POSITIONS: 2/40</b>\n"
    "  • DEMOTOKEN USDT  SL 0%  best +5%  margin $2.00\n"
    "  • ANOTHERTOKEN USDT  SL -20%  best +0%  margin $2.04"
))

# 15. /current output
test("14. /current command output", lambda: tg.send(
    "📊 <b>OPEN POSITIONS — 2</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "<b>DEMOTOKEN USDT</b>\n"
    "  🟢 Price:  $0.04500  (+5.37%)\n"
    "  💵 Entry:  $0.04271\n"
    "  📦 Margin: $2.00 × 5x\n"
    "  📈 uPnL:   +$0.521  (+26.1%)\n"
    "  🛑 SL:     0%  |  Best TP: +5%\n\n"
    "<b>ANOTHERTOKEN USDT</b>\n"
    "  🟡 Price:  $0.08850  (+1.2%)\n"
    "  💵 Entry:  $0.08745\n"
    "  📦 Margin: $2.04 × 5x\n"
    "  📈 uPnL:   +$0.041  (+2.0%)\n"
    "  🛑 SL:     -20%  |  Best TP: +0%\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "📦 Total margin: $4.04\n"
    "📈 Total uPnL:   +$0.562\n"
    "💰 Free balance: $98.00\n"
    "📊 Equity:       $102.04"
))

# 16. Final summary
time.sleep(1)
test("15. DONE banner", lambda: tg.send(
    "🏁 <b>DEMO COMPLETE</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    f"Sent {len(results)} alert types.\n\n"
    + "\n".join(f"{'✅' if ok else '❌'} {name}" for name,ok in results) +
    "\n\n<i>If all ✅ → start your bot. All alerts will work correctly.</i>"
))

# ── Print summary ─────────────────────────────────────────────────────
print()
print("=" * 60)
print("RESULTS")
print("=" * 60)
passed = sum(1 for _,ok in results if ok)
failed = sum(1 for _,ok in results if not ok)
for name, ok in results:
    print(f"  {'✅' if ok else '❌'} {name}")
print()
print(f"  {passed}/{len(results)} passed")
if failed == 0:
    print()
    print("  ALL ALERTS WORKING ✅")
    print("  Your bot is ready. Start it with: python3 main.py")
else:
    print()
    print(f"  {failed} ALERT(S) FAILED ❌")
    print("  Fix the errors above before running the bot.")

"""Phase 1: Force-close P&L materiality assessment."""
import sys
sys.path.insert(0, "src")
import warnings
warnings.filterwarnings("ignore")

from straddle.params import PARAMS, apply_market_preset
from straddle.data import load_market_data
from straddle.engines import make_engine
from straddle.portfolio import run_portfolio_backtest
from collections import Counter

params = dict(PARAMS)
params = apply_market_preset(params, "bova11")
params.update({
    "mode": "market",
    "start_date": "2023-01-02",
    "end_date": "2025-11-30",
    "target_delta": 0.25,
    "dte_max": 21,
    "dte_min": 15,  # DTE_MIN_BY_DTE_MAX[21] from grid_search.py
    "profit_target_pct": 0.50,
    "manage_at_dte": 14,
    "vix_filter": "OFF",
    "stop_loss_pct": 2.0,
    "execution_mode": "mid",
    "portfolio_mode": "laddering",
})

print("Loading market data...", flush=True)
data = load_market_data("2023-01-02", "2025-11-30", market="bova11")
print(f"Data loaded: {len(data)} rows", flush=True)

print("Creating engine...", flush=True)
engine = make_engine(params)

print("Running backtest...", flush=True)
result = run_portfolio_backtest(data, params, engine, progress=False)
trades = result[0]

total = len(trades)
force_closed = [t for t in trades if t.exit_type == "FORCE_CLOSE"]
n_force = len(force_closed)
pct_force = n_force / total * 100 if total > 0 else 0
total_pnl = sum(t.pnl for t in trades)
force_pnl = sum(t.pnl for t in force_closed)
pct_pnl = abs(force_pnl / total_pnl * 100) if total_pnl != 0 else 0

print(f"\n=== Force-Close Materiality ===")
print(f"Total trades:          {total}")
print(f"Force-closed trades:   {n_force} ({pct_force:.1f}%)")
print(f"Total P&L:             R${total_pnl:.2f}")
print(f"Force-close P&L:       R${force_pnl:.2f} ({pct_pnl:.1f}% of total |P&L|)")

print(f"\nForce-close details:")
for t in force_closed:
    print(f"  entry={t.entry_date}, exit={t.exit_date}, pnl=R${t.pnl:.2f}, net_credit=R${t.net_credit:.2f}")

print(f"\nExit type distribution:")
for k, v in sorted(Counter(t.exit_type for t in trades).items()):
    print(f"  {k}: {v} ({v/total*100:.1f}%)")

# Decision gate
print(f"\n=== Decision Gate ===")
if pct_force < 5 and pct_pnl < 2:
    print(f"PASS: Force-close trades {pct_force:.1f}% < 5% threshold AND P&L contribution {pct_pnl:.1f}% < 2% threshold")
    print("No re-run of v7 grid needed.")
else:
    print(f"FAIL: Force-close trades {pct_force:.1f}% or P&L contribution {pct_pnl:.1f}% exceeds threshold")
    print("Re-run v7 grid required!")

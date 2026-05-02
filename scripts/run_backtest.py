"""Minimal CLI script — run a full backtest from the command line.

Usage:
    python scripts/run_backtest.py
    python scripts/run_backtest.py --market bova11 --mode market --start 2015-01-01 --end 2025-12-31
    python scripts/run_backtest.py --market spy --mode synthetic --start 2024-01-01 --end 2024-12-31
    python scripts/run_backtest.py --no-plot
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from straddle import (
    PARAMS,
    compute_metrics,
    load_market_data,
    make_engine,
    plot_backtest,
    run_backtest,
)
from straddle.params import apply_market_preset, MARKET_PRESETS


def main() -> None:
    parser = argparse.ArgumentParser(description="Short Strangle Backtest")
    parser.add_argument("--market", choices=list(MARKET_PRESETS), default=None,
                        help="Underlying market (default: spy). Applies market preset.")
    parser.add_argument("--start", default=None, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--end",   default=None, help="End date (YYYY-MM-DD).")
    parser.add_argument("--mode", choices=["synthetic", "market"], default=None,
                        help="Pricing mode. Overrides PARAMS['mode'].")
    parser.add_argument("--no-plot", action="store_true", help="Skip generating the plot.")
    args = parser.parse_args()

    params = dict(PARAMS)

    # Apply market preset first (sets calendar, db path, vix multiplier, etc.)
    # then let explicit CLI flags override.
    market = args.market or params.get("market", "spy")
    params = apply_market_preset(params, market)

    if args.start:
        params["start_date"] = args.start
    if args.end:
        params["end_date"] = args.end
    if args.mode:
        params["mode"] = args.mode

    currency = params.get("currency", "USD")
    sym = params.get("currency_symbol", "$" if currency == "USD" else "R$")

    print(f"Market       : {market.upper()}  ({currency})")
    print(f"Pricing mode : {params['mode']}")
    print(f"Period       : {params['start_date']} → {params['end_date']}")
    print(
        f"Strategy     : {params['target_delta']:.0%}Δ strangle, "
        f"DTE {params['dte_min']}–{params['dte_max']}, "
        f"profit {params['profit_target_pct']:.0%} / stop {params['stop_loss_pct']:.0%}"
    )
    print()

    print("Loading market data...")
    data = load_market_data(
        start_date=params["start_date"],
        end_date=params["end_date"],
        market=market,
    )
    print(f"Trading days loaded : {len(data)}")
    print(f"Range               : {data.index[0].date()}  ->  {data.index[-1].date()}")
    print()

    print("Running backtest...")
    engine = make_engine(params)
    try:
        trades, equity_curve, skipped_entries, skipped_vix = run_backtest(
            data, params, engine
        )
    finally:
        if hasattr(engine, "close"):
            engine.close()

    metrics = compute_metrics(trades, equity_curve, params, data)

    final_balance = params["initial_balance"] + sum(t.pnl for t in trades if t.pnl)
    total_return = (final_balance - params["initial_balance"]) / params["initial_balance"]

    print(f"Trades executed : {len(trades)}")
    print(f"Skipped entries (single-position): {skipped_entries}")
    if params.get("vix_entry_filter_enabled", False):
        print(f"Skipped entries (VIX > {params['vix_entry_max']}): {skipped_vix}")
    print(f"Initial balance : {sym}{params['initial_balance']:,.2f}")
    print(f"Final balance   : {sym}{final_balance:,.2f}")
    print(f"Total P&L       : {sym}{final_balance - params['initial_balance']:+,.2f}")
    print(f"Total return    : {total_return*100:.1f}%")
    print(f"Sharpe ratio    : {metrics.get('sharpe', 'N/A'):.2f}")
    print(f"Max drawdown    : {metrics.get('mdd', 0)*100:.1f}%")
    print(f"Win rate (chain): {metrics.get('wr_chain', 0)*100:.1f}%")
    print(
        f"{market.upper()} total return: "
        f"{metrics.get('underlying_total_return', 0)*100:.1f}%"
    )
    print(f"{market.upper()} Sharpe      : {metrics.get('underlying_sharpe', 'N/A'):.2f}")

    if not args.no_plot:
        print()
        plot_backtest(trades, equity_curve, data, params)


if __name__ == "__main__":
    main()

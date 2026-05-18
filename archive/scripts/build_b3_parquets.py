"""Build B3 backtest parquets from COTAHIST files.

Produces two outputs in data/B3/:
  bova11_backtest.parquet  — OHLC + ATM IV + CDI for BOVA11 (all years)
  petr4_backtest.parquet   — OHLC + ATM IV + CDI for PETR4  (all years)

These are the files consumed by the M4 data layer
(data.py _load_b3_from_parquet).

Usage:
    python scripts/build_b3_parquets.py
    python scripts/build_b3_parquets.py --data-dir data/B3 --cdi-start 2010-01-01
"""

import argparse
import sys
from pathlib import Path

# Allow running from repo root or scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from b3_parser import build_backtest_df, fetch_cdi_rates


def main():
    parser = argparse.ArgumentParser(description="Build B3 backtest parquets from COTAHIST files")
    parser.add_argument("--data-dir",          default="data/B3",    help="Directory with COTAHIST_A*.TXT files")
    parser.add_argument("--out-dir",           default="data/B3",    help="Output directory for parquet files")
    parser.add_argument("--cdi-start",         default="2010-01-01", help="CDI history start date")
    parser.add_argument("--cdi-end",           default=None,         help="CDI history end date (default: today)")
    parser.add_argument("--bova11-min-year",   default=2015, type=int,
                        help="Skip BOVA11 COTAHIST files before this year (default: 2015 — thin liquidity prior)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir  = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Fetch CDI rates ───────────────────────────────────────────────────────
    print(f"Fetching CDI rates from {args.cdi_start} ...")
    cdi = fetch_cdi_rates(args.cdi_start, args.cdi_end)
    print(f"  {len(cdi)} days  |  range {cdi['risk_free_rate'].min():.2%} → {cdi['risk_free_rate'].max():.2%}")

    # ── BOVA11 ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Building BOVA11 backtest data")
    print("=" * 60)
    bova = build_backtest_df(
        data_dir,
        equity_ticker="BOVA11",
        underlying_name_filter=["BOVA", "ISHARES"],
        cdi_rates=cdi,
        min_trades=5,
        dte_min=20,
        dte_max=45,
        atm_moneyness=0.05,
        min_year=args.bova11_min_year,
        verbose=True,
    )
    out_bova = out_dir / "bova11_backtest.parquet"
    bova.to_parquet(out_bova)
    print(f"\nSaved → {out_bova}  ({len(bova)} rows)")

    # ── PETR4 ─────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Building PETR4 backtest data")
    print("=" * 60)
    petr = build_backtest_df(
        data_dir,
        equity_ticker="PETR4",
        underlying_name_filter=["PETR"],
        cdi_rates=cdi,
        min_trades=5,
        dte_min=20,
        dte_max=45,
        atm_moneyness=0.05,
        verbose=True,
    )
    out_petr = out_dir / "petr4_backtest.parquet"
    petr.to_parquet(out_petr)
    print(f"\nSaved → {out_petr}  ({len(petr)} rows)")

    print("\n✓  Both parquets built successfully.")


if __name__ == "__main__":
    main()

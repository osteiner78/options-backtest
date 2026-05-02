"""Build data/B3/b3_options.db from COTAHIST files.

Parses the full options chain (all DTE, not just ATM) for BOVA11 and PETR4
and loads it into a SQLite database with the same schema as the SPY options
DB so MarketEngine can query it without changes (just db_path + underlying filter).

Schema:
    options_data(date, expiration, type, strike, underlying,
                 mark, bid, ask, volume, delta, implied_volatility)

Underlying values stored: 'bova11' | 'petr4'  (lowercase, matching params["market"])

Guardrails applied:
  - BOVA11: skip years < BOVA11_MIN_YEAR (default 2015 — thin liquidity earlier)
  - min_trades=1, min_volume=500, max_moneyness=0.30, min_dte=1, max_dte=90

Usage:
    python scripts/build_b3_options_db.py
    python scripts/build_b3_options_db.py --data-dir data/B3 --out data/B3/b3_options.db
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from b3_parser import (
    extract_equity_prices,
    fetch_cdi_rates,
    parse_cotahist,
)

BOVA11_MIN_YEAR = 2015  # skip thin BOVA11 data before this year

# Map parse_cotahist's underlying label → DB identifier matching params["market"]
UNDERLYING_MAP = {
    "ISHARES BOVA": "bova11",
    "PETROBRAS":    "petr4",
}

DDL = """
CREATE TABLE IF NOT EXISTS options_data (
    date                TEXT NOT NULL,
    expiration          TEXT NOT NULL,
    type                TEXT NOT NULL,
    strike              REAL NOT NULL,
    underlying          TEXT NOT NULL,
    mark                REAL,
    bid                 REAL,
    ask                 REAL,
    volume              INTEGER,
    delta               REAL,
    implied_volatility  REAL,
    PRIMARY KEY (date, expiration, type, strike, underlying)
);
CREATE INDEX IF NOT EXISTS idx_lookup
    ON options_data (date, expiration, type, underlying);
CREATE INDEX IF NOT EXISTS idx_date_underlying
    ON options_data (date, underlying);
"""

INSERT_SQL = """
INSERT OR REPLACE INTO options_data
    (date, expiration, type, strike, underlying,
     mark, bid, ask, volume, delta, implied_volatility)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _rows_from_df(df: pd.DataFrame, underlying_id: str) -> list[tuple]:
    rows = []
    for _, r in df.iterrows():
        rows.append((
            r["date"].strftime("%Y-%m-%d"),
            r["expiry"].strftime("%Y-%m-%d"),
            r["option_type"],           # 'call' | 'put'
            float(r["strike"]),
            underlying_id,
            float(r["mid_price"]) if pd.notna(r.get("mid_price")) else None,
            float(r["bid"])       if pd.notna(r.get("bid"))       else None,
            float(r["ask"])       if pd.notna(r.get("ask"))       else None,
            int(r["qty"])         if pd.notna(r.get("qty"))        else None,
            float(r["delta"])     if pd.notna(r.get("delta"))      else None,
            float(r["iv"])        if pd.notna(r.get("iv"))         else None,
        ))
    return rows


def build(data_dir: Path, db_path: Path, cdi: pd.DataFrame, verbose: bool = True) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(DDL)
    con.commit()

    files = sorted(data_dir.glob("COTAHIST_A*.TXT"))
    total_inserted = 0

    configs = [
        dict(
            equity_ticker="BOVA11",
            underlying_name_filter=["BOVA", "ISHARES"],
            underlying_id="bova11",
            min_year=BOVA11_MIN_YEAR,
        ),
        dict(
            equity_ticker="PETR4",
            underlying_name_filter=["PETR"],
            underlying_id="petr4",
            min_year=0,
        ),
    ]

    for cfg in configs:
        label = cfg["underlying_id"].upper()
        eligible = [
            f for f in files
            if int(f.stem.replace("COTAHIST_A", "")) >= cfg["min_year"]
        ]
        if not eligible:
            print(f"  {label}: no files found (min_year={cfg['min_year']})")
            continue

        print(f"\n{'='*60}")
        print(f"Loading {label}  ({len(eligible)} files, "
              f"year >= {cfg['min_year'] or 'any'})")
        print(f"{'='*60}")

        for fp in eligible:
            year = int(fp.stem.replace("COTAHIST_A", ""))
            print(f"  {fp.name} ...", end=" ", flush=True)

            eq = extract_equity_prices(fp, [cfg["equity_ticker"]])
            opts = parse_cotahist(
                fp,
                underlying_names=cfg["underlying_name_filter"],
                min_trades=1,
                min_volume=500,
                min_price=0.01,
                max_moneyness=0.30,
                min_dte=1,
                max_dte=90,
                compute_greeks_flag=True,
                risk_free_rates=cdi,
                underlying_prices=eq,
                verbose=False,
            )
            if opts.empty:
                print("0 records")
                continue

            rows = _rows_from_df(opts, cfg["underlying_id"])
            con.executemany(INSERT_SQL, rows)
            con.commit()
            total_inserted += len(rows)
            print(f"{len(rows):,} rows  (IV ok: {opts['iv'].notna().sum():,})")

    con.close()

    if verbose:
        print(f"\n{'='*60}")
        print(f"Done.  Total rows inserted: {total_inserted:,}")
        print(f"DB: {db_path}  ({db_path.stat().st_size / 1e6:.1f} MB)")
        # Quick spot-check
        con = sqlite3.connect(str(db_path))
        for uid in ("bova11", "petr4"):
            row = con.execute(
                "SELECT COUNT(*), MIN(date), MAX(date) FROM options_data WHERE underlying=?",
                (uid,),
            ).fetchone()
            print(f"  {uid.upper():8s}: {row[0]:>10,} rows  {row[1]} → {row[2]}")
        con.close()
        print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Build B3 options SQLite from COTAHIST files")
    parser.add_argument("--data-dir", default="data/B3",             help="COTAHIST directory")
    parser.add_argument("--out",      default="data/B3/b3_options.db", help="Output SQLite path")
    parser.add_argument("--cdi-start", default="2010-01-01")
    parser.add_argument("--cdi-end",   default=None)
    args = parser.parse_args()

    print(f"Fetching CDI rates from {args.cdi_start} ...")
    cdi = fetch_cdi_rates(args.cdi_start, args.cdi_end)
    print(f"  {len(cdi)} days  |  {cdi['risk_free_rate'].min():.2%} → {cdi['risk_free_rate'].max():.2%}")

    build(
        data_dir=Path(args.data_dir),
        db_path=Path(args.out),
        cdi=cdi,
        verbose=True,
    )


if __name__ == "__main__":
    main()

import sqlite3
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RB3_DIR = ROOT / "data" / "B3" / "rb3_export"
DB_PATH = ROOT / "data" / "B3" / "b3_options_rb3.db"

COLUMN_MAP = {
    "refdate": "date",
    "maturity_date": "expiration",
    "option_type": "type",
    "strike_price": "strike",
    "close": "mark",
    "best_bid": "bid",
    "best_ask": "ask",
    "traded_contracts": "volume",
    "delta": "delta",
    "impvol": "implied_volatility",
}

SCHEMA_COLS = list(COLUMN_MAP.values()) + ["underlying"]


DEDUP_KEYS = ["refdate", "strike_price", "maturity_date", "option_type"]


def load_and_clean(path: Path, underlying: str) -> pd.DataFrame:
    raw = pd.read_parquet(path)

    before = len(raw)
    # Drop rows with zero pricing utility (engine filters mark > 0 everywhere).
    raw = raw[raw["close"].notna() & (raw["close"] > 0)]
    dropped_price = before - len(raw)

    # Deduplicate: keep the row with highest volume per option-day.
    # B3/COTAHIST may have multiple trade records for the same option; the
    # highest-volume row has the tightest bid/ask and most reliable close.
    dupes_before = raw.duplicated(subset=DEDUP_KEYS).sum()
    raw = raw.sort_values("traded_contracts", ascending=False)
    raw = raw.drop_duplicates(subset=DEDUP_KEYS, keep="first")
    dropped_dupes = dupes_before

    total_dropped = before - len(raw)
    print(
        f"  {underlying}: loaded {before:,} rows, kept {len(raw):,} "
        f"(dropped {dropped_price:,} mark≤0, {dropped_dupes:,} duplicates → {total_dropped:,} total)"
    )

    # Map to target schema
    df = raw[list(COLUMN_MAP)].rename(columns=COLUMN_MAP)
    df["underlying"] = underlying
    df["date"] = df["date"].astype(str)
    df["expiration"] = df["expiration"].astype(str)
    df["volume"] = df["volume"].fillna(0).astype(int)

    return df[SCHEMA_COLS]


def main():
    DB_PATH.unlink(missing_ok=True)
    conn = sqlite3.connect(str(DB_PATH))

    conn.execute("""
        CREATE TABLE options_data (
            date TEXT,
            expiration TEXT,
            type TEXT,
            strike REAL,
            underlying TEXT,
            mark REAL,
            bid REAL,
            ask REAL,
            volume INTEGER,
            delta REAL,
            implied_volatility REAL
        )
    """)
    conn.execute(
        "CREATE INDEX idx_lookup ON options_data(underlying, date, expiration, type)"
    )
    conn.execute(
        "CREATE INDEX idx_strike ON options_data(underlying, date, strike)"
    )

    for name, path in [
        ("bova11", RB3_DIR / "bova11_options_rb3.parquet"),
        ("petr4", RB3_DIR / "petr4_options_rb3.parquet"),
    ]:
        print(f"Processing {name}...")
        df = load_and_clean(path, name)
        df.to_sql("options_data", conn, if_exists="append", index=False)
        print(f"  Inserted {len(df):,} rows.")

    total = conn.execute("SELECT COUNT(*) FROM options_data").fetchone()[0]
    for und in ("bova11", "petr4"):
        cnt = conn.execute(
            "SELECT COUNT(*) FROM options_data WHERE underlying=?", (und,)
        ).fetchone()[0]
        print(f"  {und}: {cnt:,}")

    conn.commit()
    conn.close()
    print(f"\nCreated: {DB_PATH} ({total:,} total rows)")


if __name__ == "__main__":
    main()

# B3 Options Backtest — Data Pipeline Migration & Validation

## Context

I'm building a systematic short strangle backtest for B3 (Brazilian) options on BOVA11 and
PETR4. I just completed a data quality investigation that revealed corruption in my existing
options database. I'm migrating to a new data source (the rb3 R package) which has been
validated as more reliable.

## What I Discovered

### Existing data sources

1. **`data/B3/b3_options.db`** (236 MB SQLite) — My original options database, built from
   COTAHIST files. Schema: `options_data` table with columns
   `date, expiration, type, strike, underlying, mark, bid, ask, volume, delta, implied_volatility`.
   Underlyings stored lowercase (`bova11`, `petr4`). Contains 357k BOVA11 + 742k PETR4 rows
   (2010/2015 to 2026).

2. **`data/B3/{bova11,petr4}_backtest.parquet`** — Daily aggregated metadata (underlying OHLC +
   VIX + CDI rate). Loaded by `_load_b3_from_parquet()` in `data.py:128`. NOT options data.

3. **`data/B3/rb3_export/{bova11,petr4}_options_rb3.parquet`** — NEW data from rb3 R package.
   Contains 454k BOVA11 + 971k PETR4 rows with full Greeks computed at flat r=12%. Columns:
   `refdate, symbol, strike_price, maturity_date, option_type, close, best_bid, best_ask, 
traded_contracts, close_underlying, impvol, delta` (+ several others).

### Validation findings

After joining rb3 vs my DB on `(date, strike, expiration, type)`:

- **85% match rate** (304k of 357k BOVA11 rows matched)
- **Median price diff: R$0.005** (excellent for matched rows)
- **Mean price diff: R$8.41** (terrible due to outliers)
- **Max price diff: R$499,997** (clearly corrupted)
- **55% of rows match within R$0.01** (should be >95%)
- **47% of IVs within 2 vol points** (should be >80%)

### The corruption pattern

Top 10 mismatches show my DB has impossible prices like R$500,001 for options worth R$3.95.
Pattern suggests either:

1. Corrupted records in original COTAHIST files from B3 (not parser bug — only 5 records have
   the R$500k value)
2. Some bid/ask vs close confusion
3. Decimal encoding issues in specific records

The well-matched 168k rows show prices match exactly (R$2.30 vs R$2.30) and IVs differ only
by 1-5 vol points (acceptable given different `r` assumptions). When my DB has correct prices,
everything else is correct.

### Decision: Use rb3 as new source of truth

- rb3 data is comprehensive (96% join rate with underlyings) and validated
- Using flat r=12% for now (yield curve adds <1% precision, not worth fighting B3's flaky
  server to download daily PRE curves)
- My existing backtest engine (`engines.py`) queries `b3_options.db` via `MarketEngine` for
  strike selection and pricing — just need to swap the database file

## Backtest Architecture (already validated)

- `MarketEngine` queries `b3_options.db` for real chain data (strikes, prices, Greeks)
- Falls back to `SyntheticEngine` (BSM + parametric skew) when DB row missing
- `mode="market"` uses real DB, `mode="synthetic"` uses flat parquet only
- Strike selection: `ORDER BY ABS(delta - target) ASC LIMIT 1` (e.g., 16-delta)
- Daily MTM uses `_strike_ask()` for exact (date, expiration, strike) lookup

## Tasks for This Session

### Task 1: Migrate rb3 data to my DB schema

Run this conversion script to create a new `b3_options_rb3.db` from the rb3 parquets:

```python
import pandas as pd
import sqlite3
from pathlib import Path

# Load rb3 data
rb3_dir = Path.home() / "options-backtest/data/B3/rb3_export"
bova_rb3 = pd.read_parquet(rb3_dir / "bova11_options_rb3.parquet")
petr_rb3 = pd.read_parquet(rb3_dir / "petr4_options_rb3.parquet")

# Create new database matching existing schema
new_db = "data/B3/b3_options_rb3.db"
conn = sqlite3.connect(new_db)

conn.execute("""
    CREATE TABLE IF NOT EXISTS options_data (
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

# Add indexes for fast lookups (matching existing engine queries)
conn.execute("CREATE INDEX IF NOT EXISTS idx_lookup ON options_data(underlying, date, expiration, type)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_strike ON options_data(underlying, date, strike)")

def insert_data(df, underlying_name, conn):
    print(f"Preparing {underlying_name}...")

    # Vectorized insertion (much faster than row-by-row)
    records = [
        (
            str(row['refdate']),
            str(row['maturity_date']),
            row['option_type'],
            float(row['strike_price']),
            underlying_name,
            float(row['close']) if pd.notna(row['close']) else None,
            float(row['best_bid']) if pd.notna(row['best_bid']) else None,
            float(row['best_ask']) if pd.notna(row['best_ask']) else None,
            int(row['traded_contracts']) if pd.notna(row['traded_contracts']) else None,
            float(row['delta']) if pd.notna(row['delta']) else None,
            float(row['impvol']) if pd.notna(row['impvol']) else None,
        )
        for _, row in df.iterrows()
    ]

    print(f"Inserting {len(records):,} {underlying_name} rows...")
    conn.executemany(
        "INSERT INTO options_data VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        records
    )

insert_data(bova_rb3, 'bova11', conn)
insert_data(petr_rb3, 'petr4', conn)

conn.commit()

# Verify
total = conn.execute("SELECT COUNT(*) FROM options_data").fetchone()[0]
bova_count = conn.execute("SELECT COUNT(*) FROM options_data WHERE underlying='bova11'").fetchone()[0]
petr_count = conn.execute("SELECT COUNT(*) FROM options_data WHERE underlying='petr4'").fetchone()[0]
print(f"\nTotal: {total:,}")
print(f"BOVA11: {bova_count:,}")
print(f"PETR4: {petr_count:,}")

conn.close()
print(f"\n✓ Created: {new_db}")
```

After running, update the engine to point at `b3_options_rb3.db` (or rename and replace).

### Task 2: Additional rb3 data quality tests

Beyond the migration, run these validation checks to gain confidence and catch future similar
errors. We had ZERO of these checks before, which is why corrupted prices slipped through.

#### Test A: Sanity bounds on prices

```python
# No option should be worth more than the underlying
# No call should be worth less than max(0, S - K)
# No put should be worth less than max(0, K - S)
def test_price_bounds(df):
    violations = df[
        (df['close'] > df['close_underlying']) |  # Option > underlying
        (df['close'] < 0) |                        # Negative price
        (df['close'] > 10 * df['strike_price'])    # Price > 10x strike (sanity)
    ]
    return violations
```

#### Test B: Greeks sanity

```python
# Calls must have delta > 0, puts must have delta < 0
# All deltas must be in [-1, 1]
# IVs should be in [0.01, 5.0] (1% to 500%)
def test_greeks_sanity(df):
    violations = df[
        ((df['option_type'] == 'call') & (df['delta'] < 0)) |
        ((df['option_type'] == 'put') & (df['delta'] > 0)) |
        (df['delta'].abs() > 1.0) |
        (df['impvol'] < 0.01) |
        (df['impvol'] > 5.0)
    ]
    return violations
```

#### Test C: Bid/Ask consistency

```python
# Bid should be <= Ask, both should be positive
# Close should be between bid and ask (when available)
def test_bid_ask(df):
    has_both = df['best_bid'].notna() & df['best_ask'].notna() & (df['best_ask'] > 0)
    valid = df[has_both]
    violations = valid[
        (valid['best_bid'] > valid['best_ask']) |
        (valid['close'] < valid['best_bid'] * 0.5) |  # Allow 50% slippage
        (valid['close'] > valid['best_ask'] * 1.5)
    ]
    return violations
```

#### Test D: Time consistency

```python
# Expiration must be in the future relative to date
# DTE should be reasonable (1 to 730 days)
def test_dates(df):
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df['expiration'] = pd.to_datetime(df['expiration'])
    df['dte'] = (df['expiration'] - df['date']).dt.days

    violations = df[
        (df['dte'] < 0) |        # Expiration before date
        (df['dte'] > 730)        # More than 2 years to expiry
    ]
    return violations
```

#### Test E: Coverage by date

```python
# Each trading day should have a reasonable number of options
# Sudden drops in coverage suggest data issues
def test_coverage(df):
    daily_count = df.groupby('date').size()
    median_count = daily_count.median()

    # Flag days with <10% of median coverage
    sparse_days = daily_count[daily_count < median_count * 0.1]
    return sparse_days
```

#### Test F: Underlying price consistency

```python
# Same date should have same underlying price across all options
def test_underlying_consistency(df):
    grouped = df.groupby('date')['close_underlying'].nunique()
    inconsistent = grouped[grouped > 1]
    return inconsistent
```

Run all six tests, report violations as percentage of total rows. **Target: <0.1% violations
in any single test.** If any test exceeds 1%, investigate before using the data.

#### Test G: Spot-check known options

```python
# Pick 5-10 known liquid contracts and manually verify against historical data
# (e.g., check ATM PETR4 puts/calls during major events: COVID crash March 2020,
# Brazilian election October 2022, etc.)
test_dates_events = [
    '2020-03-23',  # COVID bottom
    '2022-10-31',  # Brazilian election
    '2023-01-09',  # Brasília attack
    '2024-03-15',  # Random date
]
# For each date, query ATM puts/calls and verify IV spiked appropriately
```

### Task 3: Run a sanity backtest

After migration, run a short backtest (e.g., 6 months) on the new database and verify:

- Trades enter at reasonable prices
- DB hits vs synthetic fallbacks ratio (should be >90% DB hits)
- No errors in MarketEngine queries
- Position management works correctly

Use the existing backtest framework, just point at the new DB.

## TODO List for Future Work

### High priority (blocks production trading)

1. **Replace flat r=12% with actual PRE yield curve** — Currently using flat rate because
   B3's daily curve scraping was unreliable. Options to revisit:
   - Quarterly snapshots from rb3 (36 requests vs 2200)
   - BACEN API for Selic (more reliable than B3 scraping)
   - Use existing CDI rates from `bova11_backtest.parquet` (already have daily!)
   - This adds ~0.5 vol point precision to IV calculations

2. **Fix Sharpe ratio inflation bug** — Current P&L spreading methodology smears realized
   losses over holding days, producing inflated Sharpe. Need true daily mark-to-market.

3. **Implement defensive leg roll** — When tested side delta breaches 0.30, roll the untested
   side. This is the largest missing piece of the tastytrade strategy and primary reason
   current model is pessimistic on directional moves.

4. **Enforce single-position-at-a-time** — Currently rolled trades can extend past next
   monthly entry, causing unintended position overlap.

### Medium priority

5. **Update sensitivity analysis** — Still uses hardcoded SyntheticEngine, needs updating to
   use MarketEngine with new DB.

6. **Add data quality monitoring** — Run Tests A-G as part of CI/CD whenever DB is rebuilt.
   Block deploys if violations >0.1%.

### Low priority (nice to have)

7. **Upgrade from EOD to intraday data** — CBOE DataShop at 5-minute intervals for SPY,
   equivalent B3 source TBD. Materially improves modeled edge.

8. **Add more underlyings** — Currently only BOVA11 and PETR4. Could add VALE3, ITUB4,
   BBDC4 for portfolio testing.

## Files I'll be working with

- `/Users/oliversteiner/Documents/code/options-backtest/data/B3/` — Data directory
- `engines.py` — MarketEngine and SyntheticEngine
- `data.py:128` — `_load_b3_from_parquet()`
- `params.py:208,229-230` — Synthetic engine slope parameters
- `scripts/build_b3_db.py` (or similar) — Original COTAHIST parser (now deprecated)

Start with Task 1 (migration), then Task 2 (validation tests). After we confirm data quality,
move to Task 3 (sanity backtest). Don't proceed to TODOs until data layer is solid.

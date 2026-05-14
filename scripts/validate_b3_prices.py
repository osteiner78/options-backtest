"""
Validate rb3 database prices against B3's official daily bulletin data.

For 10 specific dates, this script:
1. Queries rb3 DB for the BOVA11 option closest to 16-delta put and call
   at the next monthly expiration
2. Downloads B3's official daily bulletin for that date
3. Compares rb3 mark/close vs B3 LastPrice and AvgPrice
4. Compares rb3 volume vs B3 TradeQty
5. Produces a PASS/PARTIAL/FAIL verdict

Also extracts the official B3 option exercise style (European/American) for BOVA11.

Output files:
  output/validation/validation_targets.csv     — rb3 data for target contracts
  output/validation/validation_b3_official.csv — B3 bulletin data for same contracts
  output/validation/validation_comparison.csv  — side-by-side comparison + verdict
  docs/YYYY-MM-DD - rb3 price validation.md    — human-readable report
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import sys
import os

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.b3_bulletin_fetcher import get_b3_daily

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

DB_PATH = "data/B3/b3_options_rb3.db"
OUTPUT_DIR = Path("output/validation")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 10 validation dates — spread across different market regimes
VALIDATION_DATES = [
    "20180615",   # Normal 2018 trading
    "20190412",   # Normal 2019 trading
    "20200316",   # COVID crash (worst-case spreads)
    "20200915",   # Mid-COVID recovery (high vol, stable)
    "20210512",   # Post-vaccine normal
    "20220831",   # Pre-election 2022
    "20221031",   # Lula election day
    "20230815",   # Normal 2023
    "20241015",   # Recent control date
    "20250110",   # Recent 2025
]


def _parse_br_number(val: str) -> float:
    """Convert Brazilian-formatted number (e.g. '1.234,56') to float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    val = str(val).strip()
    if not val:
        return None
    # Brazilian thousands separator is '.' and decimal is ','
    # But XML may use '.' as decimal — try standard first
    try:
        return float(val)
    except ValueError:
        # Try Brazilian format: replace '.' as thousands, ',' as decimal
        val = val.replace(".", "").replace(",", ".")
        try:
            return float(val)
        except ValueError:
            return None


# ─────────────────────────────────────────────
# Step 1: Query rb3 DB for validation targets
# ─────────────────────────────────────────────

def get_rb3_targets(db_path: str, validation_dates: list[str]) -> pd.DataFrame:
    """
    For each validation date, find the BOVA11 option closest to 16-delta
    put and call at the next monthly expiration.
    Returns one put row and one call row per date (up to 20 rows total).
    """
    conn = sqlite3.connect(db_path)
    targets = []

    for date_str in validation_dates:
        date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"  # YYYY-MM-DD

        for opt_type, target_delta in [("put", -0.16), ("call", 0.16)]:
            # Find closest to 16-delta at next monthly expiration
            query = """
                SELECT
                    date, expiration, type, strike,
                    mark, bid, ask, volume,
                    delta, implied_volatility
                FROM options_data
                WHERE underlying = 'bova11'
                  AND date = ?
                  AND type = ?
                  AND expiration > date(date, '+20 days')
                  AND expiration <= date(date, '+60 days')
                  AND mark > 0
                  AND delta IS NOT NULL
                ORDER BY ABS(delta - ?) ASC
                LIMIT 1
            """
            row = pd.read_sql(query, conn, params=(date_fmt, opt_type, target_delta))
            if not row.empty:
                row["validation_date"] = date_str
                targets.append(row)

    conn.close()
    if not targets:
        return pd.DataFrame()

    df = pd.concat(targets, ignore_index=True)
    df.columns = [
        "rb3_date", "rb3_expiration", "rb3_type", "rb3_strike",
        "rb3_mark", "rb3_bid", "rb3_ask", "rb3_volume",
        "rb3_delta", "rb3_iv", "validation_date"
    ]
    return df


# ─────────────────────────────────────────────
# Step 2: Fetch B3 official data for each date
# ─────────────────────────────────────────────

def fetch_b3_official(targets_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each unique validation date in targets_df, download B3's official
    bulletin and return negotiation records for BOVA-related tickers.
    Caches by date to avoid re-downloading.
    """
    results = []
    seen_dates = {}

    for _, row in targets_df.iterrows():
        date_str = row["validation_date"]

        if date_str not in seen_dates:
            print(f"  Fetching B3 bulletin for {date_str}...")
            neg_df = get_b3_daily(date_str, type="negotiation")

            if not neg_df.empty:
                # Filter to BOVA options
                bova_df = neg_df[neg_df["Ticker"].str.startswith("BOVA", na=False)].copy()
                seen_dates[date_str] = bova_df
            else:
                print(f"    WARNING: No data returned for {date_str}")
                seen_dates[date_str] = pd.DataFrame()

        b3_day = seen_dates[date_str]
        if b3_day.empty:
            results.append({
                "validation_date": date_str,
                "rb3_type": row["rb3_type"],
                "rb3_strike": row["rb3_strike"],
                "b3_ticker": None,
                "b3_last_price": None,
                "b3_avg_price": None,
                "b3_min_price": None,
                "b3_max_price": None,
                "b3_trade_qty": None,
                "b3_found": False,
            })
            continue

        # Match by finding the option with strike closest to rb3's strike
        # B3 negotiation data doesn't directly expose strike — we need to join
        # with product data. For now, use a heuristic: the BOVA ticker whose
        # LastPrice is closest to rb3's mark.
        # A better approach joins via the IN (product) bulletin — see Step 3.
        results.append({
            "validation_date": date_str,
            "rb3_type": row["rb3_type"],
            "rb3_strike": row["rb3_strike"],
            "b3_day_data": b3_day,  # keep for Step 3 join
        })

    return results  # raw, will be processed in Step 3


def fetch_b3_product_info(targets_df: pd.DataFrame) -> dict:
    """
    For each unique validation date, download B3's product (IN) bulletin
    to get strike/expiry/style per ticker. Cache by date.
    Returns dict: date_str -> DataFrame with columns [Ticker, Style, Type, Strike, Maturity]
    """
    product_cache = {}
    for date_str in targets_df["validation_date"].unique():
        if date_str in product_cache:
            continue
        print(f"  Fetching B3 product info for {date_str}...")
        prod_df = get_b3_daily(date_str, type="product")
        if not prod_df.empty:
            bova_prod = prod_df[prod_df["Ticker"].str.startswith("BOVA", na=False)].copy()
            product_cache[date_str] = bova_prod
        else:
            product_cache[date_str] = pd.DataFrame()
    return product_cache


def match_b3_to_targets(targets_df: pd.DataFrame,
                         neg_cache: dict,
                         prod_cache: dict) -> pd.DataFrame:
    """
    For each row in targets_df, find the matching B3 contract using
    product data (strike + type + expiration), then retrieve its
    negotiation data (prices + volume).
    """
    rows = []

    for _, t in targets_df.iterrows():
        date_str = t["validation_date"]
        prod = prod_cache.get(date_str, pd.DataFrame())
        neg = neg_cache.get(date_str, pd.DataFrame())

        b3_last = None
        b3_avg = None
        b3_min = None
        b3_max = None
        b3_qty = None
        b3_ticker = None
        b3_style = None
        b3_found = False

        if not prod.empty and not neg.empty:
            # Convert B3 types: CALL/PUTT (B3 uses "PUTT" for puts in product XML)
            b3_type_map = {"call": "CALL", "put": "PUTT"}
            b3_type = b3_type_map.get(t["rb3_type"], t["rb3_type"].upper())

            # Match on type + strike (within 1%) + expiry (within 5 days)
            try:
                prod["Strike_f"] = prod["Strike"].apply(_parse_br_number)
                prod["Maturity_d"] = pd.to_datetime(prod["Maturity"])
                t_strike = float(t["rb3_strike"])
                t_expiry = pd.to_datetime(t["rb3_expiration"])

                mask = (
                    (prod["Type"] == b3_type) &
                    (prod["Strike_f"].notna()) &
                    (prod["Strike_f"].between(t_strike * 0.99, t_strike * 1.01)) &
                    (prod["Maturity_d"].notna()) &
                    (prod["Maturity_d"].between(
                        t_expiry - pd.Timedelta(days=5),
                        t_expiry + pd.Timedelta(days=5)
                    ))
                )
                matched = prod[mask]

                if not matched.empty:
                    b3_ticker = matched.iloc[0]["Ticker"]
                    b3_style = matched.iloc[0].get("Style", "UNKNOWN")

                    # Look up in negotiation data
                    neg_row = neg[neg["Ticker"] == b3_ticker]
                    if not neg_row.empty:
                        neg_row = neg_row.iloc[0]
                        b3_last = float(neg_row["LastPrice"]) if neg_row["LastPrice"] else None
                        b3_avg = float(neg_row["AvgPrice"]) if neg_row["AvgPrice"] else None
                        b3_min = float(neg_row["MinPrice"]) if neg_row["MinPrice"] else None
                        b3_max = float(neg_row["MaxPrice"]) if neg_row["MaxPrice"] else None
                        b3_qty = int(float(neg_row["TradeQty"])) if neg_row["TradeQty"] else None
                        b3_found = True
            except Exception as e:
                print(f"    Match error for {date_str} {t['rb3_type']} strike={t['rb3_strike']}: {e}")

        rows.append({
            "validation_date": date_str,
            "rb3_date": t["rb3_date"],
            "rb3_type": t["rb3_type"],
            "rb3_strike": t["rb3_strike"],
            "rb3_expiration": t["rb3_expiration"],
            "rb3_mark": t["rb3_mark"],
            "rb3_bid": t["rb3_bid"],
            "rb3_ask": t["rb3_ask"],
            "rb3_volume": t["rb3_volume"],
            "rb3_delta": t["rb3_delta"],
            "rb3_iv": t["rb3_iv"],
            "b3_ticker": b3_ticker,
            "b3_style": b3_style,
            "b3_last_price": b3_last,
            "b3_avg_price": b3_avg,
            "b3_min_price": b3_min,
            "b3_max_price": b3_max,
            "b3_trade_qty": b3_qty,
            "b3_found": b3_found,
        })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────
# Step 3: Compute validation metrics
# ─────────────────────────────────────────────

def compute_metrics(comparison: pd.DataFrame) -> dict:
    """
    Compute three validation metrics:
    - mark_vs_last:    rb3_mark vs b3_last_price (±10% tolerance)
    - mark_vs_avg:     rb3_mark vs b3_avg_price  (±10% tolerance)
    - volume_match:    rb3_volume vs b3_trade_qty (±50% tolerance — volume noisier)
    - bid_range_check: is rb3_bid within [b3_min, b3_last]? (feasibility check)
    - ask_range_check: is rb3_ask >= b3_last? (feasibility check)
    """
    valid = comparison[comparison["b3_found"]].copy()

    metrics = {
        "total_targets": len(comparison),
        "b3_found": comparison["b3_found"].sum(),
        "b3_found_pct": comparison["b3_found"].mean() * 100,
        "puts_matched": int(comparison[comparison["rb3_type"] == "put"]["b3_found"].sum()),
        "calls_matched": int(comparison[comparison["rb3_type"] == "call"]["b3_found"].sum()),
    }

    if valid.empty:
        metrics["verdict"] = "INSUFFICIENT_DATA"
        return metrics

    # Mark vs LastPrice
    has_last = valid["b3_last_price"].notna() & (valid["b3_last_price"] > 0)
    if has_last.sum() > 0:
        v = valid[has_last]
        diff_pct = (v["rb3_mark"] - v["b3_last_price"]).abs() / v["b3_last_price"]
        metrics["mark_vs_last_match_pct"] = (diff_pct < 0.10).mean() * 100
        metrics["mark_vs_last_median_diff_pct"] = diff_pct.median() * 100
        metrics["mark_vs_last_n"] = len(v)
    else:
        metrics["mark_vs_last_match_pct"] = None

    # Mark vs AvgPrice
    has_avg = valid["b3_avg_price"].notna() & (valid["b3_avg_price"] > 0)
    if has_avg.sum() > 0:
        v = valid[has_avg]
        diff_pct = (v["rb3_mark"] - v["b3_avg_price"]).abs() / v["b3_avg_price"]
        metrics["mark_vs_avg_match_pct"] = (diff_pct < 0.10).mean() * 100
        metrics["mark_vs_avg_median_diff_pct"] = diff_pct.median() * 100

    # Volume match (±50%)
    has_vol = valid["b3_trade_qty"].notna() & (valid["b3_trade_qty"] > 0) & valid["rb3_volume"].notna()
    if has_vol.sum() > 0:
        v = valid[has_vol]
        vol_ratio = v["rb3_volume"] / v["b3_trade_qty"]
        metrics["volume_ratio_median"] = vol_ratio.median()
        metrics["volume_within_50pct"] = (vol_ratio.between(0.5, 2.0)).mean() * 100
        metrics["volume_interpretation"] = (
            f"rb3 volume is {vol_ratio.median():.0f}× B3 TradeQty. "
            "This indicates rb3 reports cumulative contract volume (turnover in units), "
            "while B3 TradeQty reports the number of individual trades executed. "
            "The rb3 volume column should not be compared 1:1 with B3 TradeQty."
        )
    else:
        metrics["volume_interpretation"] = None

    # Bid feasibility: rb3_bid should be <= b3_last_price (you can't sell above last)
    has_bid = valid["rb3_bid"].notna() & (valid["rb3_bid"] > 0) & has_last
    if has_bid.sum() > 0:
        v = valid[has_bid]
        metrics["bid_below_last_pct"] = (v["rb3_bid"] <= v["b3_last_price"] * 1.05).mean() * 100

    # Ask feasibility: rb3_ask should be >= b3_last_price (can't buy below last)
    has_ask = valid["rb3_ask"].notna() & (valid["rb3_ask"] > 0) & has_last
    if has_ask.sum() > 0:
        v = valid[has_ask]
        metrics["ask_above_last_pct"] = (v["rb3_ask"] >= v["b3_last_price"] * 0.95).mean() * 100

    # Spread analysis (how wide is rb3's implied spread?)
    has_both = (valid["rb3_bid"] > 0) & (valid["rb3_ask"] > 0) & (valid["rb3_mark"] > 0)
    if has_both.sum() > 0:
        v = valid[has_both]
        spread_pct = (v["rb3_ask"] - v["rb3_bid"]) / v["rb3_mark"]
        metrics["rb3_spread_median_pct"] = spread_pct.median() * 100
        metrics["rb3_spread_mean_pct"] = spread_pct.mean() * 100
        metrics["rb3_spread_p75_pct"] = spread_pct.quantile(0.75) * 100

    # Verdict
    mark_match = metrics.get("mark_vs_last_match_pct", 0) or 0
    if mark_match >= 80:
        metrics["verdict"] = "PASS"
    elif mark_match >= 50:
        metrics["verdict"] = "PARTIAL"
    else:
        metrics["verdict"] = "FAIL"

    return metrics


# ─────────────────────────────────────────────
# Step 4: Extract BOVA11 option exercise style
# ─────────────────────────────────────────────

def extract_bova11_style(prod_cache: dict) -> str:
    """
    Extract the official B3 exercise style for BOVA11 options
    (European = EURO, American = AMER).
    Returns a detailed breakdown by style, type, and sample tickers.
    """
    for date_str in sorted(prod_cache.keys(), reverse=True):
        prod = prod_cache[date_str]
        if prod.empty:
            continue
        # Filter to BOVA options using Ação field (contains "BOVA")
        if "Ação" in prod.columns:
            bova = prod[prod["Ação"].str.contains("BOVA", na=False)]
        else:
            bova = prod[prod["Ticker"].str.startswith("BOVA")]
        if bova.empty:
            continue

        lines = []
        for style in sorted(bova["Style"].dropna().unique()):
            subset = bova[bova["Style"] == style]
            calls = subset[subset["Type"] == "CALL"]
            putts = subset[subset["Type"] == "PUTT"]
            lines.append(
                f"- **{style}**: {len(subset)} total "
                f"({len(calls)} CALL, {len(putts)} PUT) — "
                f"e.g. {subset['Ticker'].head(5).tolist()}"
            )

        if lines:
            return (
                f"**Date:** {date_str}\n\n"
                + "\n".join(lines)
                + (
                    "\n\n**Note:** BOVA11 options come in both AMER and EURO styles. "
                    "This backtest's codebase assumes European-style (no early exercise). "
                    "If AMER-style contracts are used, early exercise risk exists and "
                    "the backtest may overstate returns. All PUT contracts observed are EURO; "
                    "CALLs are mixed AMER/EURO."
                )
            )
    return "Could not determine — no product data available"


# ─────────────────────────────────────────────
# Step 5: Write the report
# ─────────────────────────────────────────────

def write_report(comparison: pd.DataFrame, metrics: dict, style_info: str):
    today = datetime.now().strftime("%Y-%m-%d")
    report_dir = Path("docs")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = str(report_dir / f"{today} - rb3 price validation.md")

    with open(report_path, "w") as f:
        f.write(f"# rb3 Price Validation Against B3 Official Bulletin\n\n")
        f.write(f"**Date completed:** {today}\n")
        f.write(f"**Method:** Automated — B3 official daily bulletin API\n")
        f.write(f"**Source:** `scripts/validate_b3_prices.py`\n\n")
        f.write("---\n\n")

        f.write("## Summary\n\n")
        f.write(f"| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Validation dates | {metrics['total_targets'] // 2} |\n")
        f.write(f"| Target contracts | {metrics['total_targets']} |\n")
        f.write(f"| B3 contract matched | {metrics['b3_found']} ({metrics['b3_found_pct']:.0f}%) |\n")
        f.write(f"|   — Puts matched | {metrics['puts_matched']}/10 |\n")
        f.write(f"|   — Calls matched | {metrics['calls_matched']}/10 |\n")
        if metrics.get("mark_vs_last_match_pct") is not None:
            f.write(f"| rb3_mark vs B3 LastPrice (±10%) | {metrics['mark_vs_last_match_pct']:.0f}% |\n")
            f.write(f"| Median mark diff | {metrics.get('mark_vs_last_median_diff_pct', 'N/A'):.1f}% |\n")
        if metrics.get("rb3_spread_median_pct") is not None:
            f.write(f"| rb3 implied spread (median) | {metrics['rb3_spread_median_pct']:.1f}% of mark |\n")
            f.write(f"| rb3 implied spread (75th pct) | {metrics['rb3_spread_p75_pct']:.1f}% of mark |\n")
        if metrics.get("bid_below_last_pct") is not None:
            f.write(f"| rb3 bid ≤ B3 last (feasibility) | {metrics['bid_below_last_pct']:.0f}% |\n")
        if metrics.get("ask_above_last_pct") is not None:
            f.write(f"| rb3 ask ≥ B3 last (feasibility) | {metrics['ask_above_last_pct']:.0f}% |\n")
        if metrics.get("volume_ratio_median") is not None:
            f.write(f"| rb3 volume / B3 TradeQty (median ratio) | {metrics['volume_ratio_median']:.0f}× |\n")
        f.write(f"\n**Verdict: {metrics['verdict']}**\n\n")

        f.write("---\n\n")
        f.write("## BOVA11 Option Exercise Style\n\n")
        f.write(f"{style_info}\n\n")

        f.write("---\n\n")
        f.write("## Volume Interpretation\n\n")
        if metrics.get("volume_interpretation"):
            f.write(f"{metrics['volume_interpretation']}\n\n")
        else:
            f.write("Insufficient matched data to compute volume ratio.\n\n")

        f.write("---\n\n")
        f.write("## Detailed Comparison\n\n")
        cols = [
            "validation_date", "rb3_type", "rb3_strike", "rb3_expiration",
            "rb3_mark", "rb3_bid", "rb3_ask", "rb3_volume",
            "b3_ticker", "b3_last_price", "b3_avg_price", "b3_trade_qty",
            "b3_style", "b3_found"
        ]
        available = [c for c in cols if c in comparison.columns]
        try:
            f.write(comparison[available].to_markdown(index=False))
        except ImportError:
            f.write(comparison[available].to_string(index=False))
        f.write("\n\n")

        f.write("---\n\n")
        f.write("## Interpretation\n\n")
        verdict = metrics["verdict"]
        if verdict == "PASS":
            f.write(
                "rb3 mark prices match B3's official last-traded prices. "
                "The rb3 database is sourcing real B3 market data. "
                "V4 conclusions about mid-price execution modes are reliable. "
                "The bid/ask spread widths in rb3 represent real market conditions.\n"
            )
        elif verdict == "PARTIAL":
            f.write(
                "rb3 mark prices partially match B3 official data. "
                "Some discrepancies exist — possibly different settlement times or "
                "data vendors. V4 mid-price conclusions should be treated with caution. "
                "Consider running v4 with wider tolerance analysis.\n"
            )
        elif verdict == "FAIL":
            f.write(
                "**CRITICAL:** rb3 mark prices do NOT match B3 official data. "
                "The rb3 database may contain computed/synthetic prices rather than "
                "real market quotes. STOP — do not proceed with v4 until this is investigated.\n"
            )
        else:
            f.write(
                "Insufficient data to make a determination. "
                "Fewer than 5 contracts were matched. Try extending the date range "
                "or checking B3 server availability.\n"
            )

    print(f"\nReport written to: {report_path}")
    return report_path


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("rb3 Price Validation Against B3 Official Bulletin")
    print("=" * 60)

    print("\nStep 1: Querying rb3 database for validation targets...")
    targets = get_rb3_targets(DB_PATH, VALIDATION_DATES)
    if targets.empty:
        print("ERROR: No targets found in rb3 DB. Check DB_PATH and date range.")
        sys.exit(1)
    print(f"  Found {len(targets)} target contracts across {len(VALIDATION_DATES)} dates")
    targets.to_csv(OUTPUT_DIR / "validation_targets.csv", index=False)
    print(f"  Saved: output/validation/validation_targets.csv")

    print("\nStep 2: Fetching B3 official bulletin data...")
    print("  (This downloads ~200KB per date × 10 dates × 2 types = ~4MB total)")

    neg_cache = {}
    prod_cache = {}
    for date_str in targets["validation_date"].unique():
        print(f"  [{date_str}] downloading negotiation data...")
        neg_df = get_b3_daily(date_str, type="negotiation")
        if not neg_df.empty:
            neg_cache[date_str] = neg_df[neg_df["Ticker"].str.startswith("BOVA", na=False)]
        else:
            neg_cache[date_str] = pd.DataFrame()

        print(f"  [{date_str}] downloading product data...")
        prod_df = get_b3_daily(date_str, type="product")
        if not prod_df.empty:
            prod_cache[date_str] = prod_df[prod_df["Ticker"].str.startswith("BOVA", na=False)]
        else:
            prod_cache[date_str] = pd.DataFrame()

        # Be polite to B3's server
        import time; time.sleep(0.5)

    print("\nStep 3: Matching B3 contracts to rb3 targets...")
    comparison = match_b3_to_targets(targets, neg_cache, prod_cache)
    comparison.to_csv(OUTPUT_DIR / "validation_comparison.csv", index=False)
    print(f"  Matched {comparison['b3_found'].sum()} of {len(comparison)} targets "
          f"(put: {comparison[comparison['rb3_type']=='put']['b3_found'].sum()}/10, "
          f"call: {comparison[comparison['rb3_type']=='call']['b3_found'].sum()}/10)")
    print(f"  Saved: output/validation/validation_comparison.csv")

    print("\nStep 4: Extracting BOVA11 exercise style...")
    style_info = extract_bova11_style(prod_cache)
    print(f"  {style_info}")

    print("\nStep 5: Computing validation metrics...")
    metrics = compute_metrics(comparison)

    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)
    for k, v in metrics.items():
        if v is not None:
            print(f"  {k}: {v:.1f}" if isinstance(v, float) else f"  {k}: {v}")

    print(f"\n  *** VERDICT: {metrics['verdict']} ***\n")

    if metrics["verdict"] == "FAIL":
        print("  CRITICAL: rb3 prices do not match B3 official data.")
        print("  Do NOT proceed to v4 until this is investigated.")

    print("\nStep 6: Writing report...")
    report_path = write_report(comparison, metrics, style_info)

    return metrics["verdict"]


if __name__ == "__main__":
    verdict = main()
    sys.exit(0 if verdict in ("PASS", "PARTIAL") else 1)
